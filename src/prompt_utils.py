import json
import os
import re
import sys
from typing import Awaitable, Callable, Optional

import aiofiles

from src.infrastructure.external.ai_client import AIClient

# The meta-prompt to instruct the AI
META_PROMPT_TEMPLATE = """
你是一位世界級的AI提示詞工程大師。你的任務是根據使用者提供的【購買需求】，模仿一個【參考範例】，為蝦皮(Shopee)商品監控機器人的AI分析模組（代號 EagleEye）生成一份全新的【分析標準】文字。

你的輸出必須嚴格遵循【參考範例】的結構、語氣和核心原則，但內容要完全針對使用者的【購買需求】進行定製。最終生成的文字將作為AI分析模組的思考指南。

---
這是【參考範例】（`macbook_criteria.txt`）：
```text
{reference_text}
```
---

這是使用者的【購買需求】：
```text
{user_description}
```
---

請現在開始生成全新的【分析標準】文字。請注意：
1.  **只輸出新生成的文字內容**，不要包含任何額外的解釋、標題或程式碼塊標記。
2.  保留範例中的 `[V6.3 核心升級]`、`[V6.4 邏輯修正]` 等版本標記，這有助於保持格式一致性。
3.  將範例中所有與 "RTX 5070 Ti 顯示卡" 相關的內容，替換為與使用者需求商品相關的內容。
4.  思考並生成針對新商品型別的“一票否決硬性原則”和“危險訊號清單”。
5.  蝦皮沒有賣家信用等級，也沒有二手商品的成色、維修歷史欄位，不要要求 AI 評估這些項目；只依據價格、型號規格、商品描述、圖片、已售數量、評價與賣場資訊判斷。
"""

ProgressCallback = Callable[[str, str], Awaitable[None]]
# 參考標準大約一千多 token。思考模型還會先輸出推理，800 會把正文截掉。
CRITERIA_MAX_OUTPUT_TOKENS = 8192
_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking)>.*?</(?:think|thinking)>",
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_THINK_RE = re.compile(r"<(?:think|thinking)>", re.IGNORECASE)


async def _report_progress(
    progress_callback: Optional[ProgressCallback],
    step_key: str,
    message: str,
) -> None:
    if progress_callback:
        await progress_callback(step_key, message)


def _read_reference_text(reference_file_path: str) -> str:
    try:
        with open(reference_file_path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"參考檔案未找到: {reference_file_path}")
    except IOError as exc:
        raise IOError(f"讀取參考檔案失敗: {exc}")


def _strip_reasoning_blocks(text: str) -> str:
    stripped = _THINK_BLOCK_RE.sub("", text).strip()
    if _UNCLOSED_THINK_RE.search(stripped):
        raise RuntimeError(
            "生成分析標準時，模型的思考過程佔滿了輸出長度，正文被截斷。"
            "請換一個不輸出長思考過程的模型，或提高模型服務允許的輸出長度。"
        )
    if not stripped:
        raise RuntimeError("AI 沒有生成分析標準正文。")
    return stripped


async def _request_generated_text(ai_client: AIClient, prompt: str) -> str:
    print("正在呼叫AI生成新的分析標準，請稍候...")
    try:
        generated_text = await ai_client._call_ai(
            [{"role": "user", "content": prompt}],
            temperature=0.5,
            max_output_tokens=CRITERIA_MAX_OUTPUT_TOKENS,
            enable_json_output=False,
        )
    except Exception as exc:
        print(f"呼叫 OpenAI API 時出錯: {exc}")
        raise

    generated_text = _strip_reasoning_blocks(generated_text)
    print("AI已成功生成內容。")
    return generated_text


async def _close_ai_client(
    ai_client: AIClient,
    active_error: BaseException | None,
) -> None:
    try:
        await ai_client.close()
    except Exception as close_error:
        print(f"關閉 AI 客戶端時出錯: {close_error}")
        if active_error is None:
            raise


async def generate_criteria(
    user_description: str,
    reference_file_path: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    """
    Generates a new criteria file content using AI.
    """
    ai_client = AIClient()
    active_error: BaseException | None = None
    try:
        if not ai_client.is_available():
            ai_client.refresh()
        if not ai_client.is_available():
            raise RuntimeError("AI客戶端未初始化，無法生成分析標準。請檢查.env配置。")

        await _report_progress(progress_callback, "reference", "正在讀取參考檔案。")
        print(f"正在讀取參考檔案: {reference_file_path}")
        reference_text = _read_reference_text(reference_file_path)

        await _report_progress(progress_callback, "prompt", "正在構建傳送給 AI 的指令。")
        print("正在構建傳送給AI的指令...")
        prompt = META_PROMPT_TEMPLATE.format(
            reference_text=reference_text,
            user_description=user_description,
        )

        await _report_progress(progress_callback, "llm", "正在呼叫 AI 生成分析標準。")
        return await _request_generated_text(ai_client, prompt)
    except Exception as exc:
        active_error = exc
        raise
    finally:
        await _close_ai_client(ai_client, active_error)


async def update_config_with_new_task(new_task: dict, config_file: str = "config.json"):
    """
    將一個新任務新增到指定的JSON配置檔案中。
    """
    print(f"正在更新配置檔案: {config_file}")
    try:
        # 讀取現有配置
        config_data = []
        if os.path.exists(config_file):
            async with aiofiles.open(config_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                # 處理空檔案的情況
                if content.strip():
                    try:
                        config_data = json.loads(content)
                        print(f"成功讀取現有配置，目前任務數量: {len(config_data)}")
                    except json.JSONDecodeError as e:
                        print(f"解析配置檔案失敗，將建立新配置: {e}")
                        config_data = []
        else:
            print(f"配置檔案不存在，將建立新檔案: {config_file}")

        # 追加新任務
        config_data.append(new_task)

        # 寫回配置檔案
        async with aiofiles.open(config_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(config_data, ensure_ascii=False, indent=2))
            print(f"配置檔案寫入完成")

        print(f"成功！新任務 '{new_task.get('task_name')}' 已新增到 {config_file} 並已啟用。")
        return True
    except json.JSONDecodeError as e:
        error_msg = f"錯誤: 配置檔案 {config_file} 格式錯誤，無法解析: {e}"
        sys.stderr.write(error_msg + "\n")
        print(error_msg)
        return False
    except IOError as e:
        error_msg = f"錯誤: 讀寫配置檔案失敗: {e}"
        sys.stderr.write(error_msg + "\n")
        print(error_msg)
        return False
    except Exception as e:
        error_msg = f"錯誤: 更新配置檔案時發生未知錯誤: {e}"
        sys.stderr.write(error_msg + "\n")
        print(error_msg)
        import traceback
        print(traceback.format_exc())
        return False
