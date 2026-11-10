import asyncio
import sys
import os
import argparse
import json
import signal
import contextlib
import re

from src.config import STATE_FILE
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
from src.scraper import scrape_shopee


async def main():
    parser = argparse.ArgumentParser(
        description="蝦皮商品監控腳本，支援多任務配置和即時AI分析。",
        epilog="""
使用示例:
  # 執行 config.json 中定義的所有任務
  python spider_v2.py

  # 只執行名為 "Sony A7M4" 的任務 (通常由排程器呼叫)
  python spider_v2.py --task-name "Sony A7M4"

  # 除錯模式: 執行所有任務，但每個任務只處理前3個新發現的商品
  python spider_v2.py --debug-limit 3
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--debug-limit", type=int, default=0, help="除錯模式：每個任務僅處理前 N 個新商品（0 表示無限制）")
    parser.add_argument("--config", type=str, help="指定任務配置檔案路徑（傳入時優先讀取 JSON）")
    parser.add_argument("--task-name", type=str, help="只執行指定名稱的單個任務 (用於定時任務排程)")
    args = parser.parse_args()

    if args.config:
        if not os.path.exists(args.config):
            sys.exit(f"錯誤: 配置檔案 '{args.config}' 不存在。")
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                tasks_config = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            sys.exit(f"錯誤: 讀取或解析配置檔案 '{args.config}' 失敗: {e}")
    else:
        repository = SqliteTaskRepository()
        tasks = await repository.find_all()
        tasks_config = [task.model_dump() for task in tasks]

    def normalize_keywords(value):
        if value is None:
            return []
        if isinstance(value, str):
            raw_values = re.split(r"[\n,]+", value)
        elif isinstance(value, (list, tuple, set)):
            raw_values = list(value)
        else:
            raw_values = [value]

        normalized = []
        seen = set()
        for item in raw_values:
            text = str(item).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return normalized

    def flatten_legacy_groups(groups):
        merged = []
        for group in groups or []:
            if isinstance(group, dict):
                merged.extend(normalize_keywords(group.get("include_keywords")))
        return normalize_keywords(merged)

    def has_bound_account(tasks: list) -> bool:
        for task in tasks:
            account = task.get("account_state_file")
            if isinstance(account, str) and account.strip():
                return True
        return False

    def has_any_state_file() -> bool:
        state_dir = os.getenv("ACCOUNT_STATE_DIR", "state").strip().strip('"').strip("'")
        if os.path.isdir(state_dir):
            for name in os.listdir(state_dir):
                if name.endswith(".json"):
                    return True
        return False

    if not os.path.exists(STATE_FILE) and not has_bound_account(tasks_config) and not has_any_state_file():
        sys.exit(
            f"錯誤: 未找到登入狀態檔案。請在 state/ 中新增帳號或配置 account_state_file。"
        )

    # 讀取所有prompt檔案內容（關鍵詞模式不需要載入prompt）
    for task in tasks_config:
        decision_mode = str(task.get("decision_mode", "ai")).strip().lower()
        if decision_mode not in {"ai", "keyword"}:
            decision_mode = "ai"
        task["decision_mode"] = decision_mode
        keyword_rules = task.get("keyword_rules")
        if keyword_rules is None and task.get("keyword_rule_groups") is not None:
            task["keyword_rules"] = flatten_legacy_groups(task.get("keyword_rule_groups") or [])
        else:
            task["keyword_rules"] = normalize_keywords(keyword_rules)

        if decision_mode == "keyword":
            task["ai_prompt_text"] = ""
            continue

        if task.get("enabled", False) and task.get("ai_prompt_base_file") and task.get("ai_prompt_criteria_file"):
            try:
                with open(task["ai_prompt_base_file"], 'r', encoding='utf-8') as f_base:
                    base_prompt = f_base.read()
                with open(task["ai_prompt_criteria_file"], 'r', encoding='utf-8') as f_criteria:
                    criteria_text = f_criteria.read()
                
                # 動態組合成最終的Prompt
                task['ai_prompt_text'] = base_prompt.replace("{{CRITERIA_SECTION}}", criteria_text)
                
                # 驗證生成的prompt是否有效
                if len(task['ai_prompt_text']) < 100:
                    print(f"警告: 任務 '{task['task_name']}' 生成的prompt過短 ({len(task['ai_prompt_text'])} 字元)，可能存在問題。")
                elif "{{CRITERIA_SECTION}}" in task['ai_prompt_text']:
                    print(f"警告: 任務 '{task['task_name']}' 的prompt中仍包含佔位符，替換可能失敗。")
                else:
                    print(f"✅ 任務 '{task['task_name']}' 的prompt生成成功，長度: {len(task['ai_prompt_text'])} 字元")

            except FileNotFoundError as e:
                print(f"警告: 任務 '{task['task_name']}' 的prompt檔案缺失: {e}，該任務的AI分析將被跳過。")
                task['ai_prompt_text'] = ""
            except Exception as e:
                print(f"錯誤: 任務 '{task['task_name']}' 處理prompt檔案時發生異常: {e}，該任務的AI分析將被跳過。")
                task['ai_prompt_text'] = ""
        elif task.get("enabled", False) and task.get("ai_prompt_file"):
            try:
                with open(task["ai_prompt_file"], 'r', encoding='utf-8') as f:
                    task['ai_prompt_text'] = f.read()
                print(f"✅ 任務 '{task['task_name']}' 的prompt檔案讀取成功，長度: {len(task['ai_prompt_text'])} 字元")
            except FileNotFoundError:
                print(f"警告: 任務 '{task['task_name']}' 的prompt檔案 '{task['ai_prompt_file']}' 未找到，該任務的AI分析將被跳過。")
                task['ai_prompt_text'] = ""
            except Exception as e:
                print(f"錯誤: 任務 '{task['task_name']}' 讀取prompt檔案時發生異常: {e}，該任務的AI分析將被跳過。")
                task['ai_prompt_text'] = ""

    print("\n--- 開始執行監控任務 ---")
    if args.debug_limit > 0:
        print(f"** 除錯模式已啟用，每個任務最多處理 {args.debug_limit} 個新商品 **")
    
    if args.task_name:
        print(f"** 定時任務模式：只執行任務 '{args.task_name}' **")

    print("--------------------")

    active_task_configs = []
    if args.task_name:
        # 如果指定了任務名稱，只查詢該任務
        task_found = next((task for task in tasks_config if task.get('task_name') == args.task_name), None)
        if task_found:
            if task_found.get("enabled", False):
                active_task_configs.append(task_found)
            else:
                print(f"任務 '{args.task_name}' 已被禁用，跳過執行。")
        else:
            print(f"錯誤：在配置檔案中未找到名為 '{args.task_name}' 的任務。")
            return
    else:
        # 否則，按原計劃載入所有啟用的任務
        active_task_configs = [task for task in tasks_config if task.get("enabled", False)]

    if not active_task_configs:
        print("沒有需要執行的任務，程式退出。")
        return

    # 為每個啟用的任務建立一個非同步執行協程
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    tasks = []
    for task_conf in active_task_configs:
        print(f"-> 任務 '{task_conf['task_name']}' 已加入執行佇列。")
        tasks.append(asyncio.create_task(scrape_shopee(task_config=task_conf, debug_limit=args.debug_limit)))

    async def _shutdown_watcher():
        await stop_event.wait()
        print("\n收到終止訊號，正在優雅退出，取消所有爬蟲任務...")
        for t in tasks:
            if not t.done():
                t.cancel()

    shutdown_task = asyncio.create_task(_shutdown_watcher())

    try:
        # 併發執行所有任務
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        shutdown_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await shutdown_task

    print("\n--- 所有任務執行完畢 ---")
    for i, result in enumerate(results):
        task_name = active_task_configs[i]['task_name']
        if isinstance(result, Exception):
            print(f"任務 '{task_name}' 因異常而終止: {result}")
        else:
            print(f"任務 '{task_name}' 正常結束，本次執行共處理了 {result} 個新商品。")

if __name__ == "__main__":
    asyncio.run(main())
