# 蝦皮智慧監控（Shopee Monitor）

用 Playwright 開啟蝦皮搜尋頁，依你設定的關鍵字與價格定時抓取商品，交給 AI（或關鍵字規則）判斷是否值得通知，並在 Web 介面查看結果與價格走勢。由閒魚監控專案改造而來，預設站點為臺灣蝦皮 `https://shopee.tw`。

> 本專案僅供個人學習與自用。請自行確認使用方式符合蝦皮的服務條款，並把執行頻率放低。詳見 [DISCLAIMER.md](DISCLAIMER.md)。

## 需要先安裝

- [Python 3.10 以上](https://www.python.org/downloads/)（Windows 安裝時請勾選「Add python.exe to PATH」）
- [Node.js LTS](https://nodejs.org/)（只在建置前端介面時用到）
- Google Chrome（或 Edge）

## 一鍵啟動

| 系統 | 做法 |
| --- | --- |
| Windows | 雙擊 `start.bat` |
| macOS / Linux | 執行 `python3 start.py` |

第一次啟動會自動：

1. 建立虛擬環境 `.venv` 並安裝 Python 套件
2. 安裝並建置前端介面
3. 建立 `.env`，**在視窗中請你設定 Web 介面的登入帳號密碼**（也可以順便選 AI 供應商、貼上 API Key，或按 Enter 略過）
4. 啟動服務並開啟瀏覽器 `http://127.0.0.1:8000`

之後再啟動只會做必要的檢查，幾秒內就能開好。要重設帳密，刪掉 `.env` 裡的 `WEB_PASSWORD` 再啟動一次即可。

## 啟動後的三個設定

### 1. 貼上蝦皮 Cookie（帳號管理）

1. Chrome 開啟 `chrome://extensions`，打開「開發人員模式」，按「載入未封裝項目」，選擇本專案的 `chrome-extension` 資料夾。
2. 開啟 `https://shopee.tw` 並登入。
3. 點擴充功能圖示 →「提取登入狀態」→「複製到剪貼簿」。
4. 回到 Web 介面的「帳號管理」，貼上並按「儲存登入狀態」。

儲存後列表會顯示是否偵測到登入、蝦皮使用者 ID 與到期時間。資料只存在這台電腦的 `state/` 資料夾，重新啟動後仍會保留；Cookie 過期時用同一個名稱重貼即可覆蓋。

### 2. AI 模型（系統設定 → AI 模型）

點一下供應商按鈕會自動帶入 API 位址與建議模型，再貼上 API Key 並按「測試連線」：

| 供應商 | API 位址 | 建議模型 |
| --- | --- | --- |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` |
| OpenRouter | `https://openrouter.ai/api/v1` | `google/gemini-2.5-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |

模型需支援圖片輸入，模型名稱可自行改成想用的版本。請求使用 `max_completion_tokens` 參數。不想用 AI 的話，任務可以改用「關鍵字」判斷模式。

### 3. 通知（系統設定 → 通知推送）

只保留通用 Webhook。可用變數：`{{title}}` `{{content}}` `{{price}}` `{{reason}}` `{{link}}` `{{image_url}}`。

Discord 範例：URL 填 Discord 的 Webhook 位址，Body 填

```json
{"content":"{{title}}\n{{content}}"}
```

## 建立監控任務

在「任務管理」新增任務：

- **關鍵字、價格區間、頁數**：對應蝦皮搜尋條件（建議先用 1 頁）
- **新發布**：有設定時改用「最新上架」排序
- **免運**：只保留免運商品
- **區域**：選縣市後，只保留該縣市出貨的商品
- **判斷方式**：AI（描述你想要的條件）或關鍵字

抓取欄位：標題、售價、原價、折扣、已售數量、庫存、評分、評價數、喜歡數、出貨地、上架時間、圖片、商品描述、規格、屬性，以及賣場名稱、評分、粉絲數、回應率、加入時間。

先小量試跑：

```bash
python spider_v2.py --task-name "你的任務名" --debug-limit 3
```

## 遇到登入失效或人機驗證

任務會直接停止並（若有設定）發出通知，不會嘗試繞過。處理方式：

- 在 `.env` 設定 `RUN_HEADLESS=false`，讓瀏覽器視窗顯示出來手動完成驗證
- 到「帳號管理」重新貼上 Cookie
- 降低任務執行頻率與頁數

## 其他

- 設定檔說明見 `.env.example`；`SHOPEE_BASE_URL` 可切換其他蝦皮站點
- 服務預設只監聽本機 `127.0.0.1`。Web 介面的帳密只擋登入畫面，後端 API 本身沒有驗證，請不要把連接埠開放到外部網路
- 執行測試：`pytest`
- Docker 相關檔案沿用自上游專案，尚未針對蝦皮版本調整，建議先用上面的本機啟動方式
