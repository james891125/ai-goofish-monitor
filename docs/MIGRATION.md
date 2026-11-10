# SQLite 遷移、備份與還原

## 原則

本版不重建或清空舊資料庫。`ShopeeRepository` 在同一 SQLite 檔案中新增 `shopee_` 前綴資料表；原本的 `tasks`、`result_items`、`price_snapshots`、`result_blacklist_rules` 與 `app_metadata` 會保留。舊表不會轉成蝦皮任務或自動執行，舊版程式已移除，歷史可從 Git 記錄查閱。

- 原有閒魚任務不會自動轉成蝦皮任務，也不會載入新的排程。
- 舊 JSON／JSONL 檔案不會被新應用自動當作蝦皮商品。保留原檔供人工查閱。
- 此處「保留歷史資料」代表資料庫／檔案仍存在，不代表新的蝦皮 UI 會顯示舊平台結果。
- 啟動前請備份。不要在未備份的唯一資料庫上直接嘗試升級或還原。

## 1. 停止舊程式並備份

停止所有舊排程、爬蟲與後端程序，確認沒有另一個版本同時寫入。記錄目前 Git commit 與 `.env` 的 `APP_DATABASE_FILE`，另行安全備份 `.env`、`prompts/`、`config.json`、`jsonl/` 及 `price_history/`；這些資料可能含個人資料或憑證，不可提交到 Git。

Windows PowerShell：

```powershell
python scripts/backup_database.py --source data/app.sqlite3
```

Linux／macOS：

```bash
python3 scripts/backup_database.py --source data/app.sqlite3
```

若資料庫路徑不是預設值，請把 `--source` 改成實際檔案。工具使用 SQLite backup API，會包含已提交的 WAL 資料並執行 `PRAGMA integrity_check`；預設輸出至 `backups/app-<UTC時間>.sqlite3`，已有目的地檔案時拒絕覆寫。工具不備份圖片、Prompt 或設定，這些須另行複製。

若舊版只有 `config.json`／JSONL，沒有 SQLite 檔案，先備份原檔，不要把它當作資料庫傳入工具。新程式會建立新的 SQLite；原檔保持不變，不自動執行舊任務。

## 2. 設定並啟動新版

在新分支建立 `.env`，設定新的 `WEB_USERNAME` 與至少 12 字元密碼。`APP_DATABASE_FILE` 指向要沿用的 SQLite 檔案：

```dotenv
APP_DATABASE_FILE=data/app.sqlite3
```

執行 `start.ps1` 或 `start.sh`。新初始化採 `CREATE TABLE IF NOT EXISTS`，標記 `migration:shopee_tw_v1`，可重複啟動。請確認沒有同時啟動舊版。

新增表：

| 表 | 用途 |
|---|---|
| `shopee_tasks` | 任務 JSON 與軟刪除時間 |
| `shopee_imports` | 合法匯入的商品資料集 |
| `shopee_products` | 每任務／來源／商品的最新資料、分析與首次／最近出現時間 |
| `shopee_price_history` | 首次觀察與價格變更紀錄 |
| `shopee_runs` | 執行開始、完成、數量與安全化錯誤訊息 |
| `shopee_notifications` | 通知認領、送出或失敗／結果不明狀態 |
| `shopee_locks` | 防止同一任務並行執行的期限鎖 |

驗收時以備份的舊表列數與抽樣內容比對，確認舊資料未變，再建立一個模擬任務。主應用不會啟動舊表中的閒魚排程。新 UI 刪除任務採軟刪除，歷史商品與執行紀錄保留。

## 3. Docker 導入既有 SQLite

Compose 預設使用 `shopee_data` 具名磁碟區。主機的 `./data` **不會自動掛載進去**，因此須先導入一致性備份，不能只啟動後就假設沿用了舊資料。

以下僅適用於第一次建立、尚無重要資料的新磁碟區。若磁碟區已有資料，先用容器內 SQLite backup API 備份並把備份複製出來，不可覆寫。

1. 停止舊程式，使用上一節工具產生一致性備份。
2. 建立映像與停止狀態的容器：

   ```powershell
   docker compose build
   docker compose create
   ```

3. 確認目標磁碟區尚未有 `app.sqlite3`，再複製剛產生的備份。以下 `app-備份時間.sqlite3` 必須替換成真實檔名。

   ```powershell
   docker compose run --rm --no-deps --entrypoint python app -c "from pathlib import Path; assert not Path('/app/data/app.sqlite3').exists(), '目標已有資料庫，停止導入'"
   docker compose cp .\backups\app-備份時間.sqlite3 app:/app/data/app.sqlite3
   docker compose run --rm --no-deps --user root --entrypoint sh app -c 'chown 10001:10001 /app/data/app.sqlite3'
   docker compose up -d
   ```

   `chown` 只設定匯入資料庫為容器內應用程式使用者，不改變主機安全設定。若任一步失敗，停止並查明原因，不要使用清空資料的方式重試。

4. 檢查 `/health`、登入、舊資料保留與模擬任務，確認才繼續使用。

具名磁碟區由 Compose 專案名稱加上前綴；搬移專案資料夾或修改專案名稱前，先確認仍使用同一個磁碟區。

## 4. 回復舊版本

停止新版並先備份目前新版資料。還原時將升級前備份複製到**新的資料庫檔名**，以 `APP_DATABASE_FILE` 指向該檔案，保留新版檔案供查閱。不要把舊備份直接覆蓋唯一的新資料庫。

需要回復時從 Git 歷史取得升級前版本與原本環境，確認安全設定、舊排程與帳號狀態後才啟動。舊版不會理解 `shopee_` 新任務；回復不代表兩種資料模型能互相轉換。除非已確認不再需要，勿手動 `DROP TABLE`、刪除磁碟區或清除 WAL。

## 升級注意事項

- Docker 的 Prompt 磁碟區會保留自訂內容，不會自動被映像中的新預設 Prompt 覆寫。更新時比較差異、另存備份後再決定是否套用。
- Docker 資料磁碟區的 `settings.env` 保存介面變更，優先於主機 `.env` 的同名值；備份磁碟區時一併安全備份此檔。
- 資料庫、備份與設定包含使用者資料，請保留在授權範圍內。
- 備份工具及非破壞性遷移的自動化測試見 [測試報告](TEST_REPORT.md)。Docker 實機遷移若未執行，報告會明確標為未驗證。
