# 測試報告

狀態：**等待資料來源授權**。本文件區分已執行測試、靜態檢查與尚未驗證項目，不以模擬資料證明真實蝦皮搜尋可用。使用者目前優先採用 Windows ZIP 測試，Docker 可稍後驗收。

## 本次整體結果

程式版本：`52f4280`（移除舊平台程式後的版本；本次另更新文件與授權檔打包設定）。測試日期：2026-11-10。

| 命令／項目 | 實際結果 | 說明 |
|---|---|---|
| `.venv/bin/python -m pytest -q` | **179 passed** | 僅計新蝦皮流程及仍適用的保留測試，不含已移除的舊平台測試 |
| `cd web-ui` 後 `npm test` | **7 passed** | 前端純邏輯測試，不等於瀏覽器互動驗證 |
| `cd web-ui` 後 `npm run build` | **通過** | `vue-tsc -b` 與 Vite 正式建置成功，輸出至根目錄 `dist/` |
| Chromium 瀏覽器操作與截圖 | **未執行成功** | Chromium 因執行環境 socket 權限限制無法啟動；未進行 UI 點擊／操作，未產生驗收截圖 |
| Windows 11 完整啟動 | **待驗證** | 目前優先交付 ZIP 供 Windows 本機測試，未以 Linux 結果代替 Windows 驗收 |
| Docker 建置／執行 | **未執行** | 環境沒有 Docker；依使用者優先順序後續再驗收 |
| GitHub Actions | **待執行／查核** | 已有工作流程，尚不宣稱遠端 CI 通過 |

前端建置出現 Browserslist 資料過期及 npm 環境設定警告，但命令成功結束。套件更新須另行測試，沒有為消除提示而盲目升級。

## 部署工具：已執行

測試日期：2026-11-10。執行環境：Linux、Python 3.12.14、Node.js 24.22.1、npm 11.9.0。

| 命令／項目 | 結果 | 範圍 |
|---|---|---|
| `.venv/bin/python -m pytest --noconftest tests/test_deployment.py tests/test_frontend_build_paths.py -q` | **27 passed** | 帳密／埠號、WAL 備份、拒絕覆寫、失敗清理、Compose／Docker 安全設定、PowerShell 靜態檢查、前端輸出路徑、6 種 Bash 檢查模式、release Dockerfile 一致性 |
| `bash -n start.sh` | 通過 | Bash 語法，非完整啟動驗收 |
| `python -m py_compile scripts/check_config.py scripts/backup_database.py` | 通過 | 兩個部署工具的 Python 語法 |
| Compose YAML 解析與本地建置設定檢查 | 通過 | 靜態結構，非 Docker 引擎驗證 |
| `git diff --check`、現行文件本機連結檢查 | 通過 | 空白錯誤與文件連結 |

上述 27 項部署測試是 179 項 Python 測試的子集，不另外加總。

Bash 的 6 種實際檢查模式涵蓋：完整準備、缺少 `.env`、缺少虛擬環境、弱密碼、缺少前端與額外參數。測試確認檢查模式沒有建立檔案、安裝依賴、啟動服務或輸出密碼。

SQLite 備份測試包含尚未 checkpoint 的已提交 WAL 資料、完整性檢查、拒絕覆寫既有檔案，以及無效來源失敗時只清理由工具新建的不完整備份。

## 整合驗證狀態

使用者後續指定移除所有舊平台程式；清理前的較大測試總數不作為最後版本的驗收結果。本次已重跑清理後的 179 項 Python 測試、7 項前端邏輯測試及 Vue 建置，全部通過。瀏覽器操作與 Windows 實機啟動仍分開列為未驗證。

新增自動化包含 Linux／Windows Python 與 Vue 建置，以及 Docker 建置、健康檢查與未登入 API 的 401 檢查。工作流程位於 `.github/workflows/shopee-tests.yml`；工作流程存在不代表已在 GitHub 上執行成功。

## 驗收範圍對照

| 要求 | 驗證方式與限制 |
|---|---|
| 任務建立／修改／刪除 | Shopee API 自動化；刪除須保留歷史 |
| 關鍵字、篩選、正規化與未知賣家欄位 | 固定合法匯入／模擬資料測試，不是全站資料驗證 |
| 去重、價格變動、歷史、資料遷移 | 臨時 SQLite 測試，保留既有表與紀錄 |
| AI JSON、token／temperature／JSON 格式相容性 | 模擬相容 API 回應與嚴格驗證；真實模型仍需另外驗證 |
| Discord 格式、限流、逾時與去重 | 模擬 HTTP；不代表真實頻道收到訊息 |
| 排程、重複執行、來源授權失效／429／逾時／連線錯誤 | 來源與工作 runtime 的自動化；不代表已驗證長期正式來源穩定性 |
| Windows／Docker／Vue | 啟動與操作結果須分別記錄，不能由其他平台測試推定 |

## 尚未驗證／外部阻礙

- Windows 11 PowerShell 完整實機啟動：尚待測試；已完成的腳本靜態檢查不等於 Windows 驗收。
- 真實瀏覽器 UI 操作：本次 Chromium 未能啟動，因此沒有點擊測試或截圖證據。前端邏輯測試與建置通過不能替代此項。
- Docker 映像建置、Compose 啟動與磁碟區還原：目前執行環境沒有 `docker`，未執行本機建置。使用者已指定不急，保留設定與 CI 供後續驗收。
- 正式蝦皮搜尋、OAuth／Access Token、配額與服務條款：等待合法資料來源與授權。
- 真實 AI 供應商呼叫與圖片理解：尚無指定測試端點／金鑰，本地相容測試不代表正式端點驗證。
- 真實 Discord 收訊：尚無指定測試 Webhook／頻道，模擬 HTTP 測試不代表已送達 Discord。

## 上線驗收

只有來源授權、真實商品搜尋、AI 有效 JSON、排程穩定性、Discord 收訊、Windows 11 啟動及主要測試全部完成，才能宣告正式完成。現階段應標示為可測試預覽版。
