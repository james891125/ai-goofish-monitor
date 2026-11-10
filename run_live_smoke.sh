#!/bin/bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_CMD="${PYTHON_CMD:-python3}"
MARK_EXPRESSION=""
DRY_RUN=false
WITH_GENERATION=true
PYTEST_ARGS=()
TASK_CREATE_TEST="tests/integration/test_api_tasks.py::test_create_list_update_delete_task"
TEST_TARGETS=(
    "$TASK_CREATE_TEST"
    "tests/live"
)

usage() {
    cat <<'EOF'
用法:
  ./run_live_smoke.sh [選項] [-- pytest額外參數]

選項:
  --keyword <關鍵詞>           覆蓋 LIVE_TEST_KEYWORD
  --account-file <路徑>        覆蓋 LIVE_TEST_ACCOUNT_STATE_FILE
  --task-name <名稱>           覆蓋 LIVE_TEST_TASK_NAME
  --timeout <秒>               覆蓋 LIVE_TIMEOUT_SECONDS
  --min-items <數量>           覆蓋 LIVE_EXPECT_MIN_ITEMS
  --debug-limit <數量>         覆蓋 LIVE_TEST_DEBUG_LIMIT（預設 1，僅分析前 N 個新商品）
  --with-generation            顯式開啟 live_slow（預設已開啟）
  --without-generation         關閉 live_slow，只執行主 smoke
  --dry-run                    只列印配置和將執行的命令，不真正執行
  --help                       顯示幫助

示例:
  ./run_live_smoke.sh
  ./run_live_smoke.sh --keyword "MacBook Air M1" --min-items 2
  ./run_live_smoke.sh --without-generation
  ./run_live_smoke.sh -- -k live_real_traffic

說明:
  0. 預設先執行任務建立 CRUD 整合測試，再執行 tests/live 真實流量 smoke
  1. 腳本會自動設定 RUN_LIVE_TESTS=1
  2. 若未設定 LIVE_TEST_ACCOUNT_STATE_FILE，會自動嘗試使用 state/ 下第一個 *.json
  3. 預設使用 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，避免本機第三方 pytest 外掛干擾
  4. 預設設定 LIVE_TEST_DEBUG_LIMIT=1，使冒煙測試只抓取並分析 1 個新商品
EOF
}

require_value() {
    local option="$1"
    local value="${2:-}"
    if [[ -z "$value" ]]; then
        echo -e "${RED}錯誤:${NC} ${option} 需要一個值"
        exit 1
    fi
}

resolve_default_account_file() {
    local first_match=""
    while IFS= read -r file; do
        first_match="$file"
        break
    done < <(find "$SCRIPT_DIR/state" -maxdepth 1 -type f -name '*.json' | sort)
    printf '%s' "$first_match"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --keyword)
            require_value "$1" "${2:-}"
            export LIVE_TEST_KEYWORD="$2"
            shift 2
            ;;
        --account-file)
            require_value "$1" "${2:-}"
            export LIVE_TEST_ACCOUNT_STATE_FILE="$2"
            shift 2
            ;;
        --task-name)
            require_value "$1" "${2:-}"
            export LIVE_TEST_TASK_NAME="$2"
            shift 2
            ;;
        --timeout)
            require_value "$1" "${2:-}"
            export LIVE_TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        --min-items)
            require_value "$1" "${2:-}"
            export LIVE_EXPECT_MIN_ITEMS="$2"
            shift 2
            ;;
        --debug-limit)
            require_value "$1" "${2:-}"
            export LIVE_TEST_DEBUG_LIMIT="$2"
            shift 2
            ;;
        --with-generation)
            WITH_GENERATION=true
            shift
            ;;
        --without-generation)
            WITH_GENERATION=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            PYTEST_ARGS+=("$@")
            break
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
    echo -e "${RED}錯誤:${NC} 未找到 Python 命令: $PYTHON_CMD"
    exit 1
fi

if ! "$PYTHON_CMD" -m pytest --version >/dev/null 2>&1; then
    echo -e "${RED}錯誤:${NC} 目前 Python 環境缺少 pytest"
    exit 1
fi

if ! "$PYTHON_CMD" -m playwright --version >/dev/null 2>&1; then
    echo -e "${RED}錯誤:${NC} 目前 Python 環境缺少 Playwright，請先安裝瀏覽器依賴"
    exit 1
fi

export RUN_LIVE_TESTS=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-1}"
export LIVE_TEST_KEYWORD="${LIVE_TEST_KEYWORD:-MacBook Pro M2}"
export LIVE_TEST_TASK_NAME="${LIVE_TEST_TASK_NAME:-Live Smoke Task}"
export LIVE_EXPECT_MIN_ITEMS="${LIVE_EXPECT_MIN_ITEMS:-1}"
export LIVE_TEST_DEBUG_LIMIT="${LIVE_TEST_DEBUG_LIMIT:-1}"
export LIVE_TIMEOUT_SECONDS="${LIVE_TIMEOUT_SECONDS:-180}"

if [[ -z "${LIVE_TEST_ACCOUNT_STATE_FILE:-}" ]]; then
    DEFAULT_ACCOUNT_FILE="$(resolve_default_account_file)"
    if [[ -n "$DEFAULT_ACCOUNT_FILE" ]]; then
        export LIVE_TEST_ACCOUNT_STATE_FILE="$DEFAULT_ACCOUNT_FILE"
    fi
fi

if [[ -z "${LIVE_TEST_ACCOUNT_STATE_FILE:-}" ]]; then
    echo -e "${RED}錯誤:${NC} 未找到 live 登入態檔案。請使用 --account-file 指定，或在 state/ 下放置 *.json"
    exit 1
fi

if [[ ! -f "${LIVE_TEST_ACCOUNT_STATE_FILE}" ]]; then
    echo -e "${RED}錯誤:${NC} 登入態檔案不存在: ${LIVE_TEST_ACCOUNT_STATE_FILE}"
    exit 1
fi

if [[ "$WITH_GENERATION" == "true" ]]; then
    export LIVE_ENABLE_TASK_GENERATION=1
    MARK_EXPRESSION=""
else
    export LIVE_ENABLE_TASK_GENERATION=0
    MARK_EXPRESSION="not live_slow"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}蝦皮真實流量 Live Smoke 一鍵測試${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${YELLOW}Python:${NC} $PYTHON_CMD"
echo -e "${YELLOW}關鍵詞:${NC} ${LIVE_TEST_KEYWORD}"
echo -e "${YELLOW}任務名:${NC} ${LIVE_TEST_TASK_NAME}"
echo -e "${YELLOW}登入態:${NC} ${LIVE_TEST_ACCOUNT_STATE_FILE}"
echo -e "${YELLOW}最少結果數:${NC} ${LIVE_EXPECT_MIN_ITEMS}"
echo -e "${YELLOW}抓取/分析商品上限:${NC} ${LIVE_TEST_DEBUG_LIMIT}"
echo -e "${YELLOW}超時(秒):${NC} ${LIVE_TIMEOUT_SECONDS}"
echo -e "${YELLOW}任務生成慢用例:${NC} ${LIVE_ENABLE_TASK_GENERATION}"
echo -e "${YELLOW}任務建立前置用例:${NC} ${TASK_CREATE_TEST}"
if [[ -n "$MARK_EXPRESSION" ]]; then
    echo -e "${YELLOW}Pytest Marker:${NC} ${MARK_EXPRESSION}"
else
    echo -e "${YELLOW}Pytest Marker:${NC} <none>"
fi
echo -e "${YELLOW}禁用外掛自動載入:${NC} ${PYTEST_DISABLE_PLUGIN_AUTOLOAD}"

CMD=(
    "$PYTHON_CMD" -m pytest
    "${TEST_TARGETS[@]}"
    -v
)

if [[ -n "$MARK_EXPRESSION" ]]; then
    CMD+=(-m "$MARK_EXPRESSION")
fi

if [[ ${#PYTEST_ARGS[@]} -gt 0 ]]; then
    CMD+=("${PYTEST_ARGS[@]}")
fi

echo -e "${YELLOW}執行命令:${NC} ${CMD[*]}"

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${GREEN}Dry run 完成，未實際執行測試。${NC}"
    exit 0
fi

"${CMD[@]}"
