# 架構盤點與重構範圍

## 產品邊界

狀態：**等待資料來源授權**。這次重構提供可測試的臺灣版監控流程，沒有已驗證的全站商品搜尋介接器。保留 FastAPI、Vue 3、SQLite、AI 相容層與 APScheduler。依使用者後續要求，原平台專屬程式、擴充功能、介面、文件與不再需要的依賴自本分支移除；歷史版本仍可從 Git 記錄查閱。

## 現行資料流

```text
Vue 3 繁體中文介面
  → 已驗證的 /api/shopee/* 與 /api/prompts/*
  → ShopeeRuntime（手動／Asia/Taipei Cron）
  → ProductMonitor
  → ProductProvider（mock / import / 等待授權的 shopee）
  → Product 正規化與篩選
  → SQLite 商品、價格歷史與執行紀錄
  → 關鍵字結果或 AIClient → JSON／證據驗證
  → Discord 通知政策與持久去重
```

`mock` 與 `import` 為本機資料來源，前者為明確標記的合成商品，後者為使用者依法提供的資料集。`shopee` 預設不可用，執行會回報 `authorization_required`。來源能力、可用狀態與到期欄位透過 `/api/shopee/status` 提供；未實作 OAuth 或自動重新授權，不顯示假的有效期限。

`browser_experiment` 是明確標記「未驗證平台授權」的實驗快照來源，不等於正式 `shopee` 來源。可選的 `scripts/browser_collect.py` 在獨立本機程序使用標準可見瀏覽器，由人手動登入；僅讀正常搜尋首頁的有限可見連結與最多 5 個商品頁。它不從後端、排程或 Docker 自動啟動，不讀取／匯出 Cookie，不呼叫私有 API，遇阻擋停止。匯出 JSON 後須再次由人確認使用權及風險，透過 `/api/shopee/browser-import` 保存至獨立快照表；後續任務只做離線分析。相關限制見 [實驗逐件瀏覽](BROWSER_EXPERIMENT.md)。

AI 分析快取以商品有意義內容、任務分析條件、Prompt、模型與輸入／輸出策略建立雜湊鍵。僅重用通過格式驗證的結果；不得因快取省略價格變更或需求更新。原本的全批商品保存及通知去重順序維持不變。執行紀錄分開顯示新的 AI 分析、快取重用與免 AI 項數，並非供應商實際計費 token。詳見 [AI token 用量](AI_TOKEN_USAGE.md)。

## 必查原始模組盤點

下表記錄移植前的原始路徑及審查結論，不代表這些檔案仍存在於新分支。移除的是程式碼與舊說明，不是使用者既有 SQLite、JSON 或備份資料。

| 原始路徑 | 審查結果 | 本版處置 |
|---|---|---|
| `src/scraper.py` | 直接依賴閒魚頁面、登入狀態、回應攔截、賣家資料與圖片下載 | 移除；由 Provider 介面替代，不改網域冒充蝦皮介接 |
| `src/parsers.py` | 閒魚巢狀回應、人民幣及原平台欄位解析 | 移除；新模型與 `product_normalizer.py` 明確使用 TWD |
| `src/services/search_pagination.py` | 特定閒魚 DOM 選擇器及搜尋回應路徑 | 移除；合法來源可自行實作分頁 |
| `src/services/item_analysis_dispatcher.py` | 分離抓取、賣家資訊、圖片、AI 與通知的思路可保留；欄位含舊平台資訊 | 移除平台專屬實作；新流程由 `ProductMonitor` 依來源中立模型協調 |
| `src/ai_handler.py` | 舊入口含平台資料、圖片下載、通知與 AI 格式處理 | 移除舊入口；新監控使用 `AIClient` |
| `src/infrastructure/external/ai_client.py` | OpenAI 相容呼叫與資源生命週期可沿用 | 維護，增強參數相容、JSON 結果及缺少證據的驗證 |
| `src/domain/models/task.py` | 原任務包含登入帳號策略、中國地區、包郵等欄位 | 移除舊模型；現行 API 使用 `domain/models/shopee.py` |
| `src/services/scheduler_service.py` | 原排程呼叫舊 ProcessService，時區為 Asia/Shanghai | 移除；改為 `shopee_runtime.py` 的 Asia/Taipei 排程 |
| `src/services/process_service.py` | 啟動 `spider_v2.py` 子程序，關聯 Cookie 與閒魚設定 | 移除；以來源中立 asyncio 工作與 SQLite 鎖替代 |
| `src/infrastructure/persistence/` | 已有 SQLite、WAL、busy timeout、舊 JSON／JSONL 匯入與價格記錄 | 維護連線基礎與 ShopeeRepository；新增 `shopee_` 表，保留使用者資料庫舊表，但不保留舊平台資料存取服務 |
| `chrome-extension/` | 權限與邏輯為閒魚 Cookie／localStorage／瀏覽器環境擷取 | 整個目錄移除，不改為蝦皮 Cookie 工具 |
| `web-ui/src/components/tasks/` | 原表單、排程與任務互動可參考，資料合約包含平台專屬欄位 | 移除舊元件；以 Shopee 元件與型別取代 |
| `web-ui/src/components/results/` | 原商品卡使用中文鍵值與人民幣相關資料 | 移除舊元件；新結果採正規化欄位與 NT$ |
| `web-ui/src/data/goofishRegions.json` | 中國行政區清單 | 移除中國行政區；臺灣縣市及可用篩選依來源能力呈現 |
| `spider_v2.py` | 原 CLI 直接載入閒魚 scraper | 移除；現行 Web 入口為 `src/app.py`，蝦皮命令列入口為 `monitor.py` |
| Docker 與啟動檔 | 原 Compose 使用上游 latest、主機公開埠與瀏覽器；缺 Windows 入口 | 由本 Fork 原始碼建置、localhost、非 root、資料磁碟區、PowerShell 與 Bash 入口 |
| `tests/` | 含舊平台單元、整合及真實流量測試 | 保留仍適用的 AI／工具測試，移除舊平台測試，新增 Shopee 與部署測試；真實外部來源仍須另行驗證 |

本版不提供雙平台支援。主應用只掛載蝦皮管理 API 與 Prompt API，舊帳號、登入狀態、爬蟲與搜尋路由已移除。歷史操作說明不留在下載 ZIP 中，也不得以舊工具補足未授權來源。

## 現行維護模組

- `src/app.py`：登入、工作階段、同源限制、靜態前端與應用程式生命週期。
- `monitor.py`：執行已儲存的蝦皮任務，不載入舊平台爬蟲。
- `src/api/routes/shopee.py`：任務 CRUD、執行、商品、歷史、匯入、狀態與設定。
- `src/domain/models/shopee.py`：Product、Seller、ShopeeTask；保留缺值與篩選可驗證性。
- `src/providers/base.py`、`src/providers/shopee.py`：來源合約、能力、來源錯誤、模擬與匯入、待授權邊界。
- `src/services/product_normalizer.py`：TWD 正規化、關鍵字與篩選、同一結果集去重。
- `src/services/product_monitor.py`：執行流程、來源錯誤分類、AI、通知政策、完成狀態。
- `src/services/shopee_runtime.py`：單一程序工作管理、Cron、取消與關閉。
- `src/infrastructure/persistence/shopee_repository.py`：新增資料表、軟刪除、價格歷史、通知認領與工作鎖。
- `src/infrastructure/external/ai_client.py`、`src/services/ai_request_compat.py`、AI 回應解析／驗證模組：可重用的模型相容層。
- `src/services/discord_notifier.py`：限縮 Webhook 目的地、NT$ 通知、關閉 mentions、隱藏 Webhook 憑證。
- `web-ui/src/components/shopee/`、`web-ui/src/api/shopee.ts`：現行臺灣版介面。
- `start.ps1`、`start.sh`、`scripts/check_config.py`、`scripts/backup_database.py`、Docker 設定：部署與遷移工具。

## 資料與執行語意

- 商品鍵為任務、資料來源、商品 ID，避免模擬／匯入混為同一商品。
- 初次觀察與價格改變寫入價格歷史；重跑同價格不建立另一份相同商品。
- 即使 AI 失敗也保存取得的商品；不把無效 JSON 當成推薦。
- 缺乏可靠資料的地區、新舊程度、賣家類型與廣告標記不符合已指定的篩選。
- `recommended` 關鍵字結果只表示符合條件，不等於 AI 或人工驗證商品品質。
- 同一商品／價格先記錄通知嘗試，再呼叫外部服務；不確定是否送達時不盲目重送。這是避免重複的取捨，不是保證每則至少送達一次。
- 工作在單一 Python 程序運行，SQLite 鎖防止重複觀察；不提供多副本排程協調或跨程序登入工作階段。

## 正式上線前缺口

合法全站來源、OAuth／金鑰保存與更新策略、真實頻率配額、來源資料更新 SLA、Windows 11 與 Docker 實機驗收、真實 AI／Discord 驗收均需依測試報告逐項完成。不得以模擬通過取代外部服務的驗證。
