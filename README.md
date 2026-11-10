# 臺灣蝦皮 AI 二手商品監控

以 FastAPI、Vue 3、SQLite、APScheduler 與 OpenAI 相容 API 建立的臺灣商品監控工具。介面採繁體中文，價格統一使用新臺幣（NT$），排程時區為 `Asia/Taipei`。**這是非蝦皮官方專案，不隸屬於蝦皮，也未宣稱獲得蝦皮核准。**

> **目前狀態：等待資料來源授權。**
> 可測試模擬搜尋、合法商品資料匯入、任務管理、AI 分析、價格歷史與通知流程。尚未取得並驗證可搜尋其他賣家商品的正式資料來源，**不能宣稱已提供蝦皮全站自動搜尋或正式完成上線驗收**。模擬價格不是市場行情。

## 已提供的功能

- 建立、修改、停用與刪除監控任務；刪除任務仍保留商品與執行歷史。
- 依關鍵字、NT$ 價格、分類、排除詞與來源實際支援的欄位篩選。
- 手動執行、每 15／30 分鐘、每小時及自訂 Cron。
- 統一商品模型、來源標記、商品 ID 去重、新商品判斷與價格變動紀錄。
- 關鍵字判斷或 AI 分析，保留自訂 Prompt。缺少賣家、保固或行情證據時標示「資訊不足」。
- Discord 通知去重及可選降價再次通知。模擬商品不發送外部通知。
- 本機登入驗證與同源工作階段；沒有預設帳號密碼。
- 可插拔資料來源介面。未授權的蝦皮來源會明確阻擋執行，不會退回 Cookie 擷取或私有 API。

目前的頁數設定是離線資料集上限，每頁折算 50 筆，實際筆數同時受「搜尋筆數」限制；不代表已呼叫蝦皮分頁 API。未知的新舊程度、地區、賣家類型或廣告標記不會被推定成符合條件。

## Windows 11 啟動

需求：Python 3.11 以上、Node.js 22.12 以上（含 npm）。使用 ZIP 測試不需要 Git，也不需要 Docker。首次安裝需要連線至官方套件來源。使用 PowerShell 5.1 或 7，以下命令在本專案根目錄執行。

### 從 GitHub 分支下載 ZIP

1. 開啟自己的 Fork：`https://github.com/james891125/ai-goofish-monitor`。
2. 用左上方分支選單選擇 `feature/shopee-tw-migration`，確認不是 `master`。
3. 選擇 **Code → Download ZIP**。
4. 下載後按右鍵選擇 **全部解壓縮**，例如解壓縮到 `C:\Users\你的名稱\Downloads\shopee-tw-monitor`。不要在壓縮檔預覽視窗內直接執行。
5. 開啟解壓縮後包含 `start.ps1`、`.env.example`、`web-ui` 的資料夾。在檔案總管位址列輸入 `powershell` 或從右鍵選單開啟終端機。
6. 依下列步驟建立設定並啟動。第一次啟動會下載套件，請保留終端機直到看到本機網址。

ZIP 不包含使用者帳密、API Key、資料庫或已安裝的依賴。再次下載新版 ZIP 時，先備份舊資料夾的 `.env`、`data` 與自訂 Prompt，不要直接刪除舊資料夾。

```powershell
Copy-Item .env.example .env
notepad .env
```

設定 `WEB_USERNAME` 與至少 12 字元的自訂 `WEB_PASSWORD`。不要沿用舊版密碼。若只測試模擬／匯入資料的關鍵字模式，AI 與 Discord 設定可留白。

```powershell
.\start.ps1
```

腳本會建立 `.venv`、安裝 Python 依賴、執行 `npm ci` 與前端建置，最後只在 `http://127.0.0.1:8000` 啟動。以自己的帳密登入，按 Ctrl+C 停止。可用 `SERVER_PORT` 更改本機連接埠。本機 `.env` 的同名值優先於程序環境變數。

安裝完成後，可執行不修改檔案、不啟動服務的檢查：

```powershell
.\start.ps1 -CheckOnly
```

若 PowerShell 的執行原則阻擋腳本，請依電腦或組織的安全政策處理；本腳本不會修改執行原則、關閉防護或要求管理員權限。可改用下列不需執行 `.ps1` 的手動步驟：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime.txt
.\.venv\Scripts\python.exe scripts/check_config.py
Push-Location web-ui
npm.cmd ci
npm.cmd run build
Pop-Location
.\.venv\Scripts\python.exe -m uvicorn src.app:app --host 127.0.0.1 --port 8000 --env-file .env
```

手動啟動命令的 `--port` 應與你選定的連接埠一致。不要同時啟動多個後端程序或使用 `--workers`；目前工作階段與排程是單一程序設計。

Linux／macOS 提供相同流程：

```bash
cp .env.example .env
# 編輯 .env 後：
bash start.sh
# 安裝／建置完成後：
bash start.sh --check-only
```

## Docker Compose

安裝 Docker Desktop（Windows 使用 Linux containers），先依上節建立 `.env`。映像從**目前 Fork 的工作目錄**建置，不下載上游的閒魚 `latest` 應用程式映像。

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail 100 app
```

瀏覽 `http://127.0.0.1:8000`。容器內部監聽 `0.0.0.0:8000`，主機連接埠只發布至 `127.0.0.1`。容器以非 root 使用者執行，資料庫、介面儲存的設定及自訂 Prompt 使用具名磁碟區保存。請勿把 `.env` 加入映像。

Docker 首次以主機 `.env` 注入環境；設定頁變更存到資料磁碟區的 `settings.env`，透過容器內 `.env` 連結載入。**已儲存的介面設定優先於主機環境值**，重建容器仍保留。登入帳密不開放在設定頁修改，應在主機 `.env` 更新後執行 `docker compose up -d --force-recreate`。備份資料磁碟區時也要保護 `settings.env` 中的 API Key 與 Webhook。

```powershell
docker compose down
```

停止服務不會刪除具名磁碟區。**不要使用 `down -v` 或清除磁碟區，否則會刪除資料。** 初次導入既有資料庫、備份與還原請依 [遷移文件](docs/MIGRATION.md) 操作，勿假設新的具名磁碟區已包含主機舊資料。

Docker 與 Windows 實機驗證狀態以 [測試報告](docs/TEST_REPORT.md) 為準，不以提供設定檔代替實際驗收。

## 第一次測試

1. 登入後確認頁面顯示「等待資料來源授權」。
2. 建立關鍵字任務，選擇「模擬資料」，例如 `RTX 5070 Ti`。價格 `15000` 至 `25000` 僅供測試。
3. 手動執行，查看商品與執行紀錄；再執行一次，確認相同商品不重複建立。
4. 測試 `Mac mini M4` 時可加入「空盒」、「配件」等排除詞。價格請自行設定。
5. 有合法資料後，到匯入頁貼上商品 JSON、確認使用權，再選擇「合法匯入資料」建立任務。

匯入只搜尋你已提供的資料集，不會自動從商品網址補抓內容。資料集必須由你或授權來源更新，排程不會讓過時的匯入資料自動變成即時行情。

### 合法匯入格式

UI 接受商品陣列。API `POST /api/shopee/import` 接受 `{"rights_confirmed": true, "products": [...]}`。單次最多 500 筆。只能匯入有權保存、分析及在設定通知目的地分享的內容；只有確認圖片可供顯示、分析及通知分享時才設定 `images_allowed: true`；預設為 `false`，沒有使用權時請留空 `images`。

```json
[
  {
    "platform": "shopee_tw",
    "product_id": "example-user-record-001",
    "title": "【格式範例】RTX 5070 Ti 16GB",
    "price_twd": 20000,
    "original_price_twd": null,
    "condition": null,
    "description": "格式示範，不是真實販售商品；請替換成你有權使用的資料。",
    "images": [],
    "images_allowed": false,
    "product_url": "",
    "seller": {
      "seller_id": null,
      "name": null,
      "rating": null,
      "review_count": null,
      "location": null,
      "verified_type": null
    },
    "listed_at": null
  }
]
```

金額必須直接使用新臺幣，不猜測其他來源的整數倍率。缺少資料填 `null`，沒有圖片填 `[]`。`data_source`、`data_quality`、`collected_at` 由系統標記。商品連結只接受完整的 HTTPS `shopee.tw`／`www.shopee.tw` 網址；不自動展開短網址。圖片只接受符合模型驗證的蝦皮公開 CDN URL。

## AI 與 Prompt

在設定頁或 `.env` 設定：

- `OPENAI_API_KEY`：使用者自有 API Key。
- `OPENAI_BASE_URL`：供應商提供的 OpenAI 相容端點，例如其文件指定的 `/v1`。
- `OPENAI_MODEL_NAME`：該供應商實際支援的模型名稱。

模型可能不支援圖片、JSON 格式、temperature 或部分 token 參數。相容層處理 Chat Completions 的 `max_tokens`／`max_completion_tokens`、Responses 的 `max_output_tokens`，並依模型與明確 API 錯誤調整；不能保證所有相容供應商皆可用。正式使用前應以自己的端點驗證。

預設 Prompt 位於 [`prompts/base_prompt.txt`](prompts/base_prompt.txt)，任務可填寫自訂 Prompt 及自然語言需求，例如：

```text
尋找 RTX 5070 Ti 16GB。請核對完整型號、顯示記憶體、保固證據、維修紀錄與交易風險。
沒有保固或市場比較資料時請標示資訊不足，不得把範例價格當行情。
```

```text
尋找 Mac mini M4。請核對晶片、RAM、SSD、機況與保固，排除空盒、配件及訂金。
缺少配置證據時列為待確認事項，不要自行補上規格。
```

啟用 AI 會把商品內容傳送至你設定的供應商；啟用圖片分析時也會傳送合法圖片 URL。請先確認資料授權與供應商隱私條款。AI 結果僅供購買參考。

## Discord 設定

1. 在你有管理權限的 Discord 伺服器選擇通知頻道，在頻道的整合設定建立 Webhook。
2. 將 Webhook URL 放入設定頁或 `.env` 的 `DISCORD_WEBHOOK_URL`，不要提交至 Git 或公開截圖。
3. 在任務選擇「僅推薦」或「所有符合條件」，以及是否允許降價再次通知。
4. 以你有權分享的匯入資料測試，並確認指定頻道收到訊息。模擬資料不會發送通知。

通知包含商品名稱、NT$ 價格、推薦與理由、風險、原始連結與發現時間，有合法圖片時附圖。關鍵字模式的結果不代表 AI 已推薦購買。逾時或結果不明時不盲目重送，以避免重複；紀錄會標示失敗或結果不明，需要人工檢查 Discord。

## 資料與安全

- 預設資料庫：`data/app.sqlite3`，可用 `APP_DATABASE_FILE` 設定。
- 新表使用 `shopee_` 前綴，保留原有 SQLite 資料；舊閒魚任務不載入、不自動排程。
- 匯入／模擬模式不需蝦皮帳號，不使用登入 Cookie。官方來源只顯示待授權狀態，尚無可執行的 OAuth 介接器。
- 不實作驗證碼繞過、反機器人規避或未授權私有 API。舊登入擴充功能、爬蟲與專屬頁面已自此分支移除，歷史僅保留於 Git 記錄。
- `.env`、資料庫、備份、state、Cookie 與私密金鑰不應加入 Git 或 Docker build context。
- 預設只供本機使用。若要開放其他裝置，需自行規劃 TLS、反向代理、存取限制及正式安全測試。

## 測試與文件

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -m "not live"
Push-Location web-ui
npm.cmd run build
Pop-Location
```

- [來源可行性與上線條件](docs/SHOPEE_FEASIBILITY.md)
- [架構盤點與維護範圍](docs/ARCHITECTURE.md)
- [資料庫遷移、備份與還原](docs/MIGRATION.md)
- [實際測試結果與尚未驗證項目](docs/TEST_REPORT.md)
- [第三方套件與授權聲明](docs/THIRD_PARTY_NOTICES.md)

## 後續維護

目前優先使用 Windows ZIP 測試；Docker 可稍後驗收。先取得明確涵蓋臺灣、其他賣家商品搜尋、自動化使用及資料再利用的來源授權，再實作對應 Provider；補齊權限到期、配額與限流管理，完成真實 AI／Discord、Windows 11 及 Docker 驗收後才評估上線。固定依賴版本、持續整合、資料保留政策與多程序部署均應在正式上線前再檢查。

## 授權與再散布

原專案 [MIT LICENSE](LICENSE) 與 [原始 DISCLAIMER.md](DISCLAIMER.md) 均原文保留，包含原作者版權聲明。MIT 本文包含使用、修改、散布及販售等許可；原免責聲明同時寫有「仅供学习和研究目的使用」。兩份文件的用途文字有需要釐清的差異，本說明不判斷其法律效力，也不保證可以不受限制地商用。**若要商業使用或販售，建議先請原作者釐清，必要時尋求法律意見。**

再散布時應保留適用的原始版權、LICENSE 與 DISCLAIMER。相依套件與圖示各有自己的授權，例如 Vue／Vue Router 為 MIT，Lucide 套件 metadata 為 ISC，並保留部分 Feather 圖示的 MIT 聲明；詳見 [第三方套件清單](docs/THIRD_PARTY_NOTICES.md)。不可把所有依賴一概視為本專案的 MIT 授權。

MIT 是程式碼授權，**不授予蝦皮平台資料、圖片、商標或 API 的存取與再利用權限**。正式資料取得、AI 處理與通知分享仍須符合來源授權及服務條款。
