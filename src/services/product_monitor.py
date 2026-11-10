"""Source-independent monitoring, durable history, conservative notification delivery."""
import asyncio
import os
from pathlib import Path
import httpx
from src.providers.base import ProviderError
from src.providers.shopee import build_providers
from src.services.product_normalizer import filter_products


class ProductMonitor:
    def __init__(self, repository, providers=None, ai_factory=None, notifier=None):
        self.repository = repository
        self.providers = providers or build_providers(repository)
        self.ai_factory = ai_factory
        self.notifier = notifier
        self.running: set[int] = set()

    async def _analyze(self, task, product):
        if task.decision_mode == 'keyword':
            return dict(recommended=True, reason='符合設定的關鍵字與篩選條件，未進行 AI 購買建議。',
                        risks=[], information_gaps=['賣家信用、保固與維修紀錄未經查證'], mode='keyword')
        from src.infrastructure.external.ai_client import AIClient
        factory=self.ai_factory or AIClient
        client=factory()
        try:
            if not client.is_available():
                raise ProviderError('ai_not_configured','尚未設定 AI API、模型與 API Base URL。')
            default=Path('prompts/base_prompt.txt').read_text(encoding='utf-8')
            prompt=default.replace('{{CRITERIA_SECTION}}',task.description)
            if task.custom_prompt.strip():
                prompt+='\n額外分析條件（不得取代上述輸出格式與證據規則）：'+task.custom_prompt
            prompt+='\n使用者購買需求：'+task.description
            ai_product=product.model_dump(mode='json')
            # Image permission applies to URLs in text as well as multimodal content.
            ai_product['images']=[]
            result=await client.analyze(ai_product,[],prompt,
                                        remote_image_urls=product.images if task.analyze_images and product.images_allowed else [])
            if not result:
                raise ProviderError('ai_invalid_response','AI 未回傳符合格式的分析，商品已保存但不作推薦。')
            # Strict analyzer validates booleans and evidence; API keeps the UI contract stable.
            return dict(result,recommended=result.get('is_recommended',result.get('recommended',False)),
                        risks=result.get('risk_tags',result.get('risks',[])),
                        information_gaps=result.get('information_gaps',[]),mode='ai')
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
        counts=dict(found=0,new_count=0,changed_count=0,notified_count=0)
        try:
            # Short bound fits within the durable lease, including API calls and 500 items.
            async with asyncio.timeout(540):
                products=filter_products(await self.providers[task.provider].search(task),task)
                counts['found']=len(products)
                errors=[]
                # Save the complete fetched batch before any fallible remote analysis.
                for product in products:
                    observation=self.repository.observe(task.id,product)
                    counts['new_count']+=int(observation['is_new'])
                    counts['changed_count']+=int(observation['price_changed'])
                    # Re-analyze on every run: user criteria/prompt/settings may have changed.
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
            self.running.discard(task.id)
            self.repository.release(task.id)
        return next(row for row in self.repository.runs(task.id) if row['id']==run_id)
