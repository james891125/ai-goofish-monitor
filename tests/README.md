# 蝦皮預覽版測試

執行 `python -m pytest -q`。測試使用合成／自行提供的資料，不擷取蝦皮網站、不讀取瀏覽器 Cookie、不呼叫真實 AI 或 Discord。

- `integration/test_shopee_api.py`：伺服端登入、跨來源保護、任務 CRUD、手動執行、匯入與歷史保留。
- `unit/test_shopee_monitor.py`：正規化、篩選、去重、價格、排程、通知去重及授權／429／逾時／連線錯誤。
- `unit/test_shopee_ai_analysis.py`、AI client/parser 相容性測試：模型參數、JSON 與證據限制。
- `unit/test_discord_notifier.py`：格式、網址驗證、限流與機密保護。
- `test_deployment.py`：Windows 啟動腳本靜態驗證、Bash 檢查模式、SQLite 備份、Docker 配置。

前端：`cd web-ui && npm ci && npm test && npm run build`。正式來源、AI 端點與 Discord 實際收訊必須在取得授權後另外驗收；見 `docs/TEST_REPORT.md`。

舊平台專用測試隨已移除功能退休，仍可從 Git 歷史取得，不能把新版本測試數量與舊功能測試混為一談。
