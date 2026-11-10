# 專案開發指引

## 產品範圍

- 本分支只維護臺灣蝦皮，介面與文件使用繁體中文（臺灣用語），金額使用 NT$，排程時區使用 `Asia/Taipei`。
- 發行狀態為「等待資料來源授權」。模擬與匯入不能稱為真實全站搜尋。
- 不得重建舊平台爬蟲、Cookie 外掛、驗證碼繞過、反機器人規避或未授權私有 API。
- 使用者目前優先從 GitHub 分支下載 ZIP，在 Windows 11 本機測試；保留 Docker 配置但不以它作為首次測試門檻。

## 分層與入口

- 後端入口：`src/app.py`；現行 API：`src/api/routes/shopee.py` 與 Prompt 路由。
- 模型：`src/domain/models/shopee.py`；資料來源：`src/providers/`。
- 正規化／監控／排程：`product_normalizer.py`、`product_monitor.py`、`shopee_runtime.py`。
- 持久化：`src/infrastructure/persistence/shopee_repository.py`，資料庫預設 `data/app.sqlite3`。
- AI 呼叫與相容性層：`src/infrastructure/external/ai_client.py` 與相關 `src/services/` 模組。
- 前端：Vue 3／Vite，`web-ui/`；建置輸出為根目錄 `dist/`。
- 新邏輯保持 API → services → domain／infrastructure 分層，避免平台資料取得與 AI 分析耦合。

## 啟動與測試

- Windows：雙擊 `啟動蝦皮監控.cmd`，依提示設定自訂帳密；進階使用者仍可執行 `.\start.ps1`。
- Linux／macOS：`bash start.sh`。
- 啟動腳本只綁定 localhost。禁止預設密碼、禁止將機密印入日誌。
- Python 測試：`.venv/bin/python -m pytest -m "not live"`，Windows 對應 `.\.venv\Scripts\python.exe`。
- 前端建置：`cd web-ui`，`npm ci`，`npm run build`。
- 部署靜態／工具測試：`tests/test_deployment.py` 與 `tests/test_frontend_build_paths.py`。
- 未在 Windows、Docker 或真實外部服務執行的驗證，必須明確標示未驗證。

## 資料與安全

- 遷移必須是新增式，不可清空使用者資料。既有資料表保留，舊任務不載入新排程。
- 缺少欄位使用 null；不可推測賣家信用、交易歷史、商品狀態或市場行情。
- 匯入須確認使用權；圖片分享須明確允許。AI 無效 JSON 不得當作推薦。
- 保護 `.env`、Cookie、token、API Key、Webhook、SQLite 與備份，不加入 Git 或映像。
- `Dockerfile` 與 `Dockerfile.release` 須保持一致，從目前分支原始碼建置。

## 提交前

- 依模組提供測試，執行相關測試與前端建置。
- 更新 `docs/TEST_REPORT.md` 的實際結果，不能把模擬測試寫成正式外部服務通過。
- 更新 README、架構與遷移說明；依 Conventional Commits 命名提交。
- PR 說明修改範圍、Windows ZIP 操作、測試結果、待授權功能及其他風險。
