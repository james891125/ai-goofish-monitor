#!/usr/bin/env bash
# Local-only development/deployment launcher. Never source .env as shell code.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

check_only=false
case "${1:-}" in
  "") ;;
  --check-only) check_only=true ;;
  *) printf '用法：bash start.sh [--check-only]\n' >&2; exit 2 ;;
esac
if (( $# > 1 )); then printf '不支援額外參數。\n' >&2; exit 2; fi

command -v python3 >/dev/null || { echo '請先安裝 Python 3.11 以上版本。' >&2; exit 1; }
command -v node >/dev/null || { echo '請先安裝 Node.js 22.12 以上版本。' >&2; exit 1; }
command -v npm >/dev/null || { echo '請先安裝 npm。' >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "需要 Python 3.11 以上版本。")'
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 12)) { console.error("需要 Node.js 22.12 以上版本。"); process.exit(1); }'
if [[ ! -f .env ]]; then
  echo '請先複製 .env.example 為 .env，並設定 WEB_USERNAME 與 WEB_PASSWORD。' >&2
  exit 1
fi

if "$check_only"; then
  [[ -x .venv/bin/python ]] || { echo '尚無 .venv。請先執行 bash start.sh 安裝依賴；本次未修改檔案。' >&2; exit 1; }
  .venv/bin/python scripts/check_config.py
  [[ -f dist/index.html ]] || { echo '前端尚未建置。請執行 bash start.sh；本次未修改檔案。' >&2; exit 1; }
  echo '環境與設定檢查通過。未啟動伺服器，也未連線至外部服務。'
  exit 0
fi

[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "既有 .venv 需要 Python 3.11 以上版本，請在新資料夾重新建立環境。")'
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python scripts/check_config.py
port="$(.venv/bin/python scripts/check_config.py --port)"
(
  cd web-ui
  npm ci
  npm run build
)
echo "請開啟 http://127.0.0.1:${port} 。按 Ctrl+C 停止。"
exec .venv/bin/python -m uvicorn src.app:app --host 127.0.0.1 --port "$port" --env-file .env
