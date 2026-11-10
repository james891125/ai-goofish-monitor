# 測試報告

狀態：**等待資料來源授權**。本文件區分已執行測試、靜態檢查與尚未驗證項目，不以模擬資料證明真實蝦皮搜尋可用。使用者目前優先採用 Windows ZIP 測試，Docker 可稍後驗收。

## 本次整體結果

測試日期：2026-11-10。完整預覽版首次發布為 `a4abe63`；本次修正 Windows 備份檔案鎖、跨平台測試、明確 .env 路徑並更新套件，後續 CI 結果以 PR #1 的檢查為準。

| 命令／項目 | 實際結果 | 說明 |
|---|---|---|
| `.venv/bin/python -m pytest -q` | **179 passed** | 僅計新蝦皮流程及仍適用的保留測試，不含已移除的舊平台測試 |
| `cd web-ui` 後 `npm test` | **7 passed** | 前端純邏輯測試，不等於瀏覽器互動驗證 |
| `cd web-ui` 後 `npm run build` | **通過** | `vue-tsc -b` 與 Vite 正式建置成功，輸出至根目錄 `dist/` |
| Chrome 瀏覽器操作 | **Windows 通過** | 真實 Chrome 執行登入、建立／修改／刪除、取消／Escape、商品／歷史、匯入、設定／Prompt、返回、手機版與登出／再登入。測試使用隔離資料；首次測試需關閉隱含 .env 搜尋，本次已修正為明確本目錄路徑 |
| Windows 11 ZIP 啟動 | **通過** | PowerShell 5.1、PATH Python 3.14.7、Node 24.13.0：建立 venv、安裝、前端建置、Uvicorn 啟動、健康檢查成功；-CheckOnly 於 PS5.1 與 PS7 通過 |
| Docker 建置／執行 | **GitHub CI 通過** | 初版 CI 已建置並通過容器健康與登入保護檢查；本機沒有 Docker。Compose 磁碟區還原尚未驗證 |
| GitHub Actions | **修正後重跑中** | 初版 Linux／Docker 通過；Windows 5 項失敗已定位並修正，詳見下方。未以警告誤當根因 |

依實際 npm audit 修補既有版本範圍內的依賴，未使用 --force 或主要版本升級。重新 npm ci、npm audit、前端測試及建置全部通過；audit 由 12 項（9 高、3 中）降為 0。這不代表所有未知風險均不存在。

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

使用者後續指定移除所有舊平台程式；清理前的較大測試總數不作為最後版本的驗收結果。本次已重跑清理後的 179 項 Python 測試、7 項前端邏輯測試及 Vue 建置，全部通過。Windows ZIP 啟動與 Chrome 操作另有實機驗證，沒有用 Linux 結果代替。

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

- Windows 完整回歸：等待修正後 CI 與最新快照重跑；ZIP 啟動、HTTP 操作及 Chrome 操作已通過。
- 雲端 Chromium 因 socket 系統限制無法啟動，已改在 Windows 的真實 Chrome 完成操作驗證。
- Docker 本機／Compose 磁碟區還原：未驗證。本次 GitHub CI 映像建置與容器測試通過不代表已驗證實機 Compose 還原。
- 正式蝦皮搜尋、OAuth／Access Token、配額與服務條款：等待合法資料來源與授權。
- 真實 AI 供應商呼叫與圖片理解：尚無指定測試端點／金鑰，本地相容測試不代表正式端點驗證。
- 真實 Discord 收訊：尚無指定測試 Webhook／頻道，模擬 HTTP 測試不代表已送達 Discord。

## 上線驗收

只有來源授權、真實商品搜尋、AI 有效 JSON、排程穩定性、Discord 收訊、Windows 11 啟動及主要測試全部完成，才能宣告正式完成。現階段應標示為可測試預覽版。

## Windows 首次 CI 的發現與修正

初次結果為 168 passed、5 failed、6 skipped。真正問題是 SQLite 備份使用連線 context manager 卻未 close，失敗清理在 Windows 遭檔案鎖阻擋；已改用 contextlib.closing。另兩項讀檔測試未指定 UTF-8、兩項代理測試假設環境變數名稱區分大小寫，已依跨平台語意修正。Node 20 淘汰提醒不是失敗原因。

Windows 本機 HTTP 實測：Cookie 登入、任務 CRUD、兩次執行去重、NT$20,000 模擬歷史、授權確認匯入、NT$17,000→16,000 價格歷史、刪除保留歷史、舊路由 404、登出後 API 401 均通過。
