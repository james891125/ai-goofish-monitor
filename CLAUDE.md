# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

基於 Playwright + AI 的蝦皮 (Shopee) 智慧監控機器人（由閒魚監控專案改造而來）。FastAPI 後端 + Vue 3 前端，支援多任務並行監控、多模態 AI 商品分析、Webhook 通知。

## 核心架構

```
API層 (src/api/routes/)
    ↓
服務層 (src/services/)
    ↓
領域層 (src/domain/)
    ↓
基礎設施層 (src/infrastructure/)
```

關鍵入口：
- `src/app.py` - FastAPI 應用主入口
- `spider_v2.py` - 爬蟲 CLI 入口
- `src/scraper.py` - Playwright 爬蟲核心邏輯（`scrape_shopee`）
- `src/shopee.py` - 蝦皮 URL 組裝與 API 響應解析（純函式）

服務層：
- `TaskService` - 任務 CRUD
- `ProcessService` - 爬蟲子程序管理
- `SchedulerService` - APScheduler 定時排程
- `AIAnalysisService` - 多模態 AI 分析
- `NotificationService` - 通知（僅通用 Webhook）

前端 (`web-ui/`)：Vue 3 + Vite + shadcn-vue + Tailwind CSS

## 開發命令

```bash
# 後端開發
python -m src.app
# 或
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# 前端開發
cd web-ui && npm install && npm run dev

# 前端構建
cd web-ui && npm run build

# 一鍵本地啟動（建立 .venv、建置前端、首次詢問帳密、啟動後端）
python3 start.py        # Windows 雙擊 start.bat

# Docker 部署
docker compose up --build -d
```

## 爬蟲命令

```bash
python spider_v2.py                          # 執行所有啟用任務
python spider_v2.py --task-name "MacBook"    # 執行指定任務
python spider_v2.py --debug-limit 3          # 除錯模式，限制商品數
python spider_v2.py --config custom.json     # 自定義配置檔案
```

## 測試

```bash
pytest                              # 執行所有測試
pytest --cov=src                    # 覆蓋率報告
pytest tests/unit/test_utils.py    # 執行單個測試檔案
pytest tests/unit/test_utils.py::test_safe_get  # 執行單個測試函式
```

測試規範：檔案 `tests/**/test_*.py`，函式 `test_*`

## 配置

環境變數 (`.env`)：
- AI 模型：`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL_NAME`
- 通知：`WEBHOOK_URL`, `WEBHOOK_METHOD`, `WEBHOOK_CONTENT_TYPE`, `WEBHOOK_HEADERS`, `WEBHOOK_QUERY_PARAMETERS`, `WEBHOOK_BODY`
- 爬蟲：`RUN_HEADLESS`, `LOGIN_IS_EDGE`, `SHOPEE_BASE_URL`（預設 `https://shopee.tw`）
- Web 認證：`WEB_USERNAME`, `WEB_PASSWORD`
- 連接埠：`SERVER_PORT`

任務配置 (`config.json`)：定義監控任務（關鍵詞、價格範圍、cron 表示式、AI prompt 檔案等）

## 資料流

1. Web UI / config.json 建立任務
2. SchedulerService 按 cron 觸發或手動啟動
3. ProcessService 啟動 spider_v2.py 子程序
4. scraper.py 使用 Playwright 開啟蝦皮搜尋頁/商品頁，攔截頁面自身的 `search_items` / `pdp/get_pc` API 響應
5. AIAnalysisService 呼叫多模態模型分析
6. NotificationService 推送符合條件的商品
7. 結果儲存：`jsonl/`（資料）、`images/`（圖片）、`logs/`（日誌）

## 注意事項

- AI 模型必須支援圖片上傳（多模態）
- Docker 部署需透過 Web UI 手動更新登入狀態（`state.json`）
- 遇到滑動驗證碼時設定 `RUN_HEADLESS=false` 手動處理
- 生產環境務必修改預設 Web 認證密碼
- 專案文字一律使用臺灣繁體中文；資料記錄的鍵名（`商品資訊`、`目前售價`、`出貨地區` 等）前後端共用，修改時要同步
- AI 走 OpenAI 相容的 Chat Completions，token 上限參數為 `max_completion_tokens`；Gemini / OpenRouter / OpenAI 預設值在 `setup_env.py` 與 `web-ui/src/views/SettingsView.vue`
- 蝦皮登入狀態存在 `state/*.json`，由 `src/services/shopee_login_state.py` 檢查與整理
