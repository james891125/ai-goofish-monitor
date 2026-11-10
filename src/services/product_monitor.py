"""Source-independent monitoring, durable history, conservative notification delivery."""
import asyncio
import os
from pathlib import Path
import httpx
from src.providers.base import ProviderError
from src.providers.shopee import build_providers
from src.services.product_normalizer import filter_products
from src.services.ai_analysis_validator import InvalidAIAnalysisError, validate_analysis
from src.services.ai_token_policy import (
    DEFAULT_DESCRIPTION_CHARS, DEFAULT_MAX_IMAGES, DEFAULT_MAX_PROMPT_CHARS,
    analysis_cache_key, project_product,
)
from src.services.remote_image_urls import safe_public_https_url


class ProductMonitor:
    def __init__(self, repository, providers=None, ai_factory=None, notifier=None):
        self.repository = repository
        self.providers = providers or build_providers(repository)
        self.ai_factory = ai_factory
        self.notifier = notifier
        self.running: set[int] = set()
        self._run_counts: dict[int, dict] = {}

    def _count_ai(self, task, field):
        if task.id in self._run_counts:
            self._run_counts[task.id][field] += 1

    async def _analyze(self, task, product):
        if task.decision_mode == 'keyword':
            self._count_ai(task, 'ai_skipped_count')
            return dict(recommended=True, reason='符合設定的關鍵字與篩選條件，未進行 AI 購買建議。',
                        risks=[], information_gaps=['賣家信用、保固與維修紀錄未經查證'], mode='keyword')
        from src.infrastructure.external.ai_client import AIClient
        from src.infrastructure.config.settings import AISettings
        factory = self.ai_factory or AIClient
        client = factory()
        try:
            settings = getattr(client, 'settings', None) or AISettings()
            default = Path('prompts/base_prompt.txt').read_text(encoding='utf-8')
            prompt = default.replace('{{CRITERIA_SECTION}}', '使用者購買需求：' + task.description)
            if task.custom_prompt.strip():
                prompt += '\n額外分析條件（不得取代上述輸出格式與證據規則）：' + task.custom_prompt
            prompt += '\n請精簡各項說明，避免重複敘述；description_truncated=true 表示商品描述有省略，不能推定省略部分的內容。'
            if len(prompt) > getattr(settings, 'max_prompt_chars', DEFAULT_MAX_PROMPT_CHARS):
                self._count_ai(task, 'ai_skipped_count')
                raise ProviderError('ai_prompt_too_large', '需求或自訂 Prompt 超過 AI 文字預算，請精簡後重試。')
            ai_product = project_product(product.model_dump(mode='json'),
                getattr(settings, 'product_description_chars', DEFAULT_DESCRIPTION_CHARS))
            image_urls = []
            if task.analyze_images and product.images_allowed:
                image_urls = [url for raw in product.images
                              if (url := safe_public_https_url(raw)) is not None]
                image_urls = image_urls[:getattr(settings, 'max_images', DEFAULT_MAX_IMAGES)]
            if not client.is_available():
                self._count_ai(task, 'ai_skipped_count')
                raise ProviderError('ai_not_configured', '尚未設定 AI API、模型與 API Base URL。')
            cache_key = analysis_cache_key(task, product, prompt, settings, image_urls)
            cached = self.repository.get_cached_analysis(task.id, product, cache_key)
            if cached:
                try:
                    validate_analysis(cached, ai_product)
                except InvalidAIAnalysisError:
                    pass  # Invalid/old cache entries are never recommendations.
                else:
                    self._count_ai(task, 'ai_reused_count')
                    return dict(cached, recommended=cached['is_recommended'], risks=cached['risk_tags'],
                                information_gaps=cached.get('information_gaps', []), mode='ai')
            self._count_ai(task, 'ai_new_count')
            result = await client.analyze(ai_product, [], prompt, remote_image_urls=image_urls)
            try:
                validate_analysis(result, ai_product)
            except InvalidAIAnalysisError as exc:
                raise ProviderError('ai_invalid_response', 'AI 未回傳符合格式的分析，商品已保存但不作推薦。') from exc
            analysis = dict(result, recommended=result['is_recommended'], risks=result['risk_tags'],
                            information_gaps=result.get('information_gaps', []), mode='ai')
            self.repository.save_cached_analysis(task.id, product, cache_key, analysis)
            return analysis
        finally:
            await client.close()

    async def run(self, task):
        if task.id is None:
            raise ValueError('Task must be persisted before running')
        if not task.enabled:
            raise ProviderError('task_disabled','任務已停用。')
        if task.id in self.running or not self.repository.acquire(task.id):
            raise ProviderError('already_running','任務已在執行，未重複啟動。')
        self.running.add(task.id)
        run_id=self.repository.start_run(task.id)
        counts=dict(found=0,new_count=0,changed_count=0,notified_count=0,
                    ai_new_count=0,ai_reused_count=0,ai_skipped_count=0)
        self._run_counts[task.id] = counts
        try:
            # Short bound fits within the durable lease, including API calls and 500 items.
            async with asyncio.timeout(540):
                fetched=await self.providers[task.provider].search(task)
                products=filter_products(fetched,task)
                counts['ai_skipped_count']=len(fetched)-len(products)
                counts['found']=len(products)
                errors=[]
                # Save the complete fetched batch before any fallible remote analysis.
                for product in products:
                    observation=self.repository.observe(task.id,product)
                    counts['new_count']+=int(observation['is_new'])
                    counts['changed_count']+=int(observation['price_changed'])
                    # Clear old display decisions first; only a matching validated cache can restore them.
                    self.repository.set_analysis(task.id,product,None)
                for product in products:
                    try:
                        analysis=await self._analyze(task,product)
                    except ProviderError as exc:
                        errors.append(exc)
                        continue
                    self.repository.set_analysis(task.id,product,analysis)
                    webhook=os.getenv('DISCORD_WEBHOOK_URL','').strip()
                    should_notify=task.notify=='all' or analysis.get('recommended') is True
                    # Synthetic data must never produce an apparent live deal notification.
                    if webhook and should_notify and product.data_source!='mock':
                        if self.repository.claim_notification(task.id,product,task.notify_price_drop):
                            from src.services.discord_notifier import send
                            success=await (self.notifier or send)(product.model_dump(mode='json'),analysis,webhook)
                            self.repository.notification_result(task.id,product,success)
                            if not success:
                                errors.append(ProviderError('notification_failed','Discord 傳送失敗或結果不明；為避免重複通知，不會自動重送同價格。'))
                                continue
                            counts['notified_count']+=1
            if errors:
                self.repository.finish_run(run_id,status='failed',error_code=errors[0].code,error_message=errors[0].public_message,**counts)
            else:
                self.repository.finish_run(run_id,**counts)
        except asyncio.CancelledError:
            self.repository.finish_run(run_id,status='cancelled',error_code='cancelled',error_message='工作已停止。',**counts)
            raise
        except ProviderError as exc:
            self.repository.finish_run(run_id,status='failed',error_code=exc.code,error_message=exc.public_message,**counts)
        except (TimeoutError,httpx.TimeoutException):
            self.repository.finish_run(run_id,status='failed',error_code='timeout',error_message='資料來源或分析逾時，本次已停止。',**counts)
        except httpx.HTTPStatusError as exc:
            status=exc.response.status_code
            code='authorization_expired' if status in {401,403} else 'rate_limited' if status==429 else 'source_http_error'
            self.repository.finish_run(run_id,status='failed',error_code=code,error_message='資料來源授權失效、限流或回應錯誤，請檢查授權狀態與供應商配額。',**counts)
        except httpx.RequestError:
            self.repository.finish_run(run_id,status='failed',error_code='connection_error',error_message='無法連線至資料來源。',**counts)
        except Exception:
            # Never persist an arbitrary provider exception: it may contain credentials/URLs.
            self.repository.finish_run(run_id,status='failed',error_code='internal_error',error_message='監控發生錯誤，未保存可能含機密的原始例外。',**counts)
        finally:
            self._run_counts.pop(task.id, None)
            self.running.discard(task.id)
            self.repository.release(task.id)
        return next(row for row in self.repository.runs(task.id) if row['id']==run_id)
