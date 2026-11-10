# Repository Guidelines

## 專案結構與模組組織
- 後端位於 `src/`，入口 `src/app.py`，API 路由在 `src/api/routes/`，服務層在 `src/services/`，領域模型在 `src/domain/`，基礎設施在 `src/infrastructure/`。
- 前端在 `web-ui/`（Vue 3 + Vite），檢視放於 `web-ui/src/views/`，元件在 `web-ui/src/components/`，構建產物會複製到根目錄 `dist/`。
- 測試位於 `tests/`，命名遵循 `test_*.py` 或 `tests/*/test_*.py`。
- 執行資料與資源：`prompts/`、`jsonl/`、`logs/`、`images/`、`static/`、`state/`，配置檔案 `config.json` 與 `.env` 位於倉庫根目錄。

## 構建、測試與本地開發
- 後端開發：`python -m src.app` 或 `uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload`。
- 爬蟲任務：`python spider_v2.py --task-name "MacBook Air M1" --debug-limit 3`（可用 `--config` 指定自定義配置）。
- 前端開發：`cd web-ui && npm install && npm run dev`；構建：`cd web-ui && npm run build`（產物複製到根目錄 `dist/`）。
- 一鍵本地啟動：`bash start.sh`（自動安裝依賴、前端構建並啟動後端）。
- Docker：`docker compose up --build -d`，檢視日誌 `docker compose logs -f app`，停止 `docker compose down`。

## 編碼風格與命名約定
- 保持分層：API → services → domain → infrastructure，避免跨層耦合，模組保持精簡。
- Python 測試函式命名為 `test_*`，檔案與路徑遵循上述測試目錄規範。
- 使用描述性、任務導向的命名（如爬蟲任務名、配置鍵），與業務含義對應。

## 架構與執行時
- 後端使用 FastAPI 提供 API 與靜態資源，爬蟲與 AI 推理在獨立任務程序中協作，前後端透過 HTTP/Web UI 互動。
- 任務執行會在 `jsonl/` 寫入結果、在 `logs/` 留存執行日誌、在 `images/` 下載圖片，前端監控頁面依賴這些資料。
- 預設監聽 8000 連接埠，前端構建後靜態檔案可由後端或 Docker 映象直接提供。

## 測試指南
- 測試框架：`pytest`（預設同步測試，無需 `pytest-asyncio`）。
- 執行全部測試：`pytest`；覆蓋率：`pytest --cov=src` 或 `coverage run -m pytest`；定向測試：`pytest tests/test_utils.py::test_safe_get`。
- 優先覆蓋核心服務、爬蟲管道的異常分支與重試邏輯，避免迴歸。
- PR 前請執行相關測試，新增邏輯補充針對性用例。

## 提交與 PR 規範
- Commit 採用類 Conventional Commits：`feat(...)`、`fix(...)`、`refactor(...)`、`chore(...)`、`docs(...)` 等。
- PR 需說明變更範圍與影響模組；UI 變更在 `web-ui/` 提供截圖；關聯相關 Issue；提及配置或遷移步驟。

## 安全與配置提示
- 複製 `.env.example` 為 `.env`，設定必填項 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL_NAME` 等。
- 不要提交真實憑據或 cookies（如 `state.json`）；Playwright 需本地瀏覽器，Docker 映象已預裝 Chromium。
- Web 認證預設 `admin/admin123`，生產環境務必修改，推薦啟用 HTTPS 並限制訪問來源。
