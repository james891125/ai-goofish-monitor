# 臺灣蝦皮 AI 商品監控介面

Vue 3、TypeScript 與 Vite 前端，全部使用繁體中文及新臺幣。正式來源尚未取得授權，介面持續顯示「等待資料來源授權」。資料來源只提供模擬測試與合法 JSON 匯入。

## 本機開發

需要 Node.js 22 LTS。先依專案根目錄說明啟動 FastAPI（8000 埠），再執行：

```sh
npm ci
npm run dev
```

開啟 Vite 顯示的本機網址。使用部署時設定的 `WEB_USERNAME` 與 `WEB_PASSWORD` 登入。登入使用後端 HttpOnly 工作階段 Cookie；不要求蝦皮帳號，也不儲存 API Key 到瀏覽器。

```sh
npm test
npm run build
```

建置包含 TypeScript 檢查，輸出到根目錄 `dist/`，供 FastAPI 提供靜態頁面。

## 功能

- 任務建立、編輯、啟停、刪除、手動執行與 Cron 排程。
- 關鍵字及 AI 模式、圖片分析選項、NT$ 價格範圍、排除詞、通知規則。
- 依來源能力停用新舊程度、地區、賣家類型與廣告篩選。
- 模擬與合法匯入來源清楚標示，商品、推薦、價格歷史與執行錯誤可查詢。
- AI 服務與 Discord 設定、預設與個別任務的自訂提示詞。
- JSON 匯入需明確確認資料使用權，圖片另以 `images_allowed` 標記使用權。

## 測試

`npm test` 使用 Node.js 內建測試執行器，涵蓋表單驗證、來源能力、範本、NT$ 與臺灣時區、安全網址及匯入格式。`tests/browser_smoke.py` 可搭配本機測試後端執行瀏覽器操作驗證，詳細參數見檔案說明。測試不代表已驗證正式來源、外部 AI 或 Discord 服務。
