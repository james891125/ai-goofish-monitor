#!/bin/bash

# 蝦皮監控系統本地啟動腳本
# 功能：清理舊構建、安裝依賴、構建前端、啟動服務

set -e  # 遇到錯誤立即退出

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 獲取腳本所在目錄
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}蝦皮監控系統 - 本地啟動腳本${NC}"
echo -e "${GREEN}========================================${NC}"

# 0. 環境與依賴檢查
echo -e "\n${YELLOW}[1/6] 檢查環境與依賴...${NC}"

OS_FAMILY="unknown"
LINUX_ID=""
LINUX_LIKE=""
PYTHON_CMD="python3"
PIP_CMD="python3 -m pip"

if [ -f /etc/os-release ]; then
    . /etc/os-release
    LINUX_ID="$ID"
    LINUX_LIKE="$ID_LIKE"
fi

case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin)
        OS_FAMILY="macos"
        ;;
    Linux)
        if grep -qi microsoft /proc/version 2>/dev/null; then
            OS_FAMILY="wsl"
        else
            OS_FAMILY="linux"
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        OS_FAMILY="windows"
        ;;
    *)
        OS_FAMILY="unknown"
        ;;
esac

MISSING_ITEMS=()

if ! command -v python3 >/dev/null 2>&1; then
    MISSING_ITEMS+=("python3(>=3.10)")
else
    if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        MISSING_ITEMS+=("python3(>=3.10)")
    fi
fi

if ! python3 -m pip --version >/dev/null 2>&1; then
    MISSING_ITEMS+=("pip")
fi

if ! command -v node >/dev/null 2>&1; then
    MISSING_ITEMS+=("node")
fi

if ! command -v npm >/dev/null 2>&1; then
    MISSING_ITEMS+=("npm")
fi

if ! python3 -m playwright --version >/dev/null 2>&1; then
    MISSING_ITEMS+=("playwright")
fi

has_browser=false
case "$OS_FAMILY" in
    macos)
        if [ -d "/Applications/Google Chrome.app" ] || [ -d "/Applications/Microsoft Edge.app" ]; then
            has_browser=true
        fi
        ;;
    linux|wsl)
        if command -v google-chrome >/dev/null 2>&1 \
            || command -v google-chrome-stable >/dev/null 2>&1 \
            || command -v chromium >/dev/null 2>&1 \
            || command -v chromium-browser >/dev/null 2>&1 \
            || command -v microsoft-edge >/dev/null 2>&1 \
            || command -v microsoft-edge-stable >/dev/null 2>&1; then
            has_browser=true
        fi
        ;;
    windows)
        if [ -d "/c/Program Files/Google/Chrome/Application" ] \
            || [ -d "/c/Program Files (x86)/Google/Chrome/Application" ] \
            || [ -d "/c/Program Files (x86)/Microsoft/Edge/Application" ] \
            || [ -d "/c/Program Files/Microsoft/Edge/Application" ]; then
            has_browser=true
        fi
        ;;
esac

if [ "$has_browser" = false ]; then
    MISSING_ITEMS+=("瀏覽器(Chrome 或 Edge)")
fi


print_solution_macos() {
    cat <<'EOF'
macOS 解決辦法:
1) 安裝 Homebrew:
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
2) 安裝 Python 與 Node:
   brew install python@3.11 node
3) 安裝 Playwright:
   python3 -m pip install playwright
   python3 -m playwright install chromium
4) 安裝瀏覽器:
   brew install --cask google-chrome
   # 或
   brew install --cask microsoft-edge
5) 配置檔案（可選）:
   cp .env.example .env
   cp config.json.example config.json
EOF
}

print_solution_linux_deb() {
    cat <<'EOF'
Linux (Debian/Ubuntu) 解決辦法:
1) 安裝 Python 與 pip:
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip python3-venv
2) 安裝 Node.js 與 npm (LTS):
   curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
   sudo apt-get install -y nodejs
3) 安裝 Playwright:
   python3 -m pip install playwright
   python3 -m playwright install chromium
   python3 -m playwright install-deps chromium
4) 安裝瀏覽器:
   sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium
   # 或安裝 Edge:
   sudo apt-get install -y microsoft-edge-stable
5) 配置檔案（可選）:
   cp .env.example .env
   cp config.json.example config.json
EOF
}

print_solution_linux_rpm() {
    cat <<'EOF'
Linux (RHEL/CentOS/Fedora) 解決辦法:
1) 安裝 Python 與 pip:
   sudo dnf install -y python3 python3-pip
2) 安裝 Node.js 與 npm (LTS):
   sudo dnf install -y nodejs
3) 安裝 Playwright:
   python3 -m pip install playwright
   python3 -m playwright install chromium
   python3 -m playwright install-deps chromium
4) 安裝瀏覽器:
   sudo dnf install -y chromium
   # 或安裝 Edge:
   sudo dnf install -y microsoft-edge-stable
5) 配置檔案（可選）:
   cp .env.example .env
   cp config.json.example config.json
EOF
}

print_solution_linux_arch() {
    cat <<'EOF'
Linux (Arch) 解決辦法:
1) 安裝 Python 與 pip:
   sudo pacman -S --noconfirm python python-pip
2) 安裝 Node.js 與 npm:
   sudo pacman -S --noconfirm nodejs npm
3) 安裝 Playwright:
   python3 -m pip install playwright
   python3 -m playwright install chromium
   python3 -m playwright install-deps chromium
4) 安裝瀏覽器:
   sudo pacman -S --noconfirm chromium
   # 或安裝 Edge:
   yay -S microsoft-edge-stable
5) 配置檔案:
   cp .env.example .env
   cp config.json.example config.json
EOF
}

print_solution_wsl() {
    cat <<'EOF'
WSL 解決辦法:
1) 安裝 Python 與 pip:
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip python3-venv
2) 安裝 Node.js 與 npm (LTS):
   curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
   sudo apt-get install -y nodejs
3) 安裝 Playwright:
   python3 -m pip install playwright
   python3 -m playwright install chromium
   python3 -m playwright install-deps chromium
4) 安裝瀏覽器:
   sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium
   # 或在 Windows 安裝 Chrome/Edge 並在 WSL 使用 Linux 版本瀏覽器
5) 配置檔案:
   cp .env.example .env
   cp config.json.example config.json
EOF
}

print_solution_windows() {
    cat <<'EOF'
Windows (PowerShell) 解決辦法:
1) 安裝 Python 與 Node:
   winget install Python.Python.3.11
   winget install OpenJS.NodeJS.LTS
2) 安裝 Playwright:
   py -m pip install playwright
   py -m playwright install chromium
3) 安裝瀏覽器:
   winget install Google.Chrome
   # 或
   winget install Microsoft.Edge
4) 配置檔案（可選）:
   Copy-Item .env.example .env
   Copy-Item config.json.example config.json
EOF
}

print_solution_generic() {
    cat <<'EOF'
通用解決辦法:
1) 安裝 Python 3.10+ 與 pip
2) 安裝 Node.js 與 npm
3) 安裝 Playwright:
   python3 -m pip install playwright
   python3 -m playwright install chromium
4) 安裝瀏覽器 Chrome 或 Edge
5) 配置檔案（可選）:
   cp .env.example .env
   cp config.json.example config.json
EOF
}

if [ "${#MISSING_ITEMS[@]}" -ne 0 ]; then
    echo -e "${RED}✗ 檢測到缺失的環境/依賴:${NC}"
    for item in "${MISSING_ITEMS[@]}"; do
        echo "  - $item"
    done
    echo ""
    case "$OS_FAMILY" in
        macos)
            print_solution_macos
            ;;
        linux)
            if [ "$LINUX_ID" = "arch" ] || echo "$LINUX_LIKE" | grep -qi "arch"; then
                print_solution_linux_arch
            elif [ "$LINUX_ID" = "fedora" ] || [ "$LINUX_ID" = "rhel" ] || [ "$LINUX_ID" = "centos" ] || echo "$LINUX_LIKE" | grep -qi "rhel\|fedora"; then
                print_solution_linux_rpm
            else
                print_solution_linux_deb
            fi
            ;;
        wsl)
            print_solution_wsl
            ;;
        windows)
            print_solution_windows
            ;;
        *)
            print_solution_generic
            ;;
    esac
    exit 1
fi

echo -e "${GREEN}✓ 環境與依賴檢查透過${NC}"

# 1. 清理舊的 dist 目錄
echo -e "\n${YELLOW}[2/6] 清理舊的構建產物...${NC}"
if [ -d "dist" ]; then
    rm -rf dist
    echo -e "${GREEN}✓ 已刪除舊的 dist 目錄${NC}"
else
    echo -e "${GREEN}✓ dist 目錄不存在，跳過清理${NC}"
fi

# 2. 檢查並安裝 Python 依賴
echo -e "\n${YELLOW}[3/6] 檢查 Python 依賴...${NC}"
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}✗ 錯誤: requirements.txt 檔案不存在${NC}"
    exit 1
fi

echo "正在安裝 Python 依賴..."
python3 -m pip install -r requirements.txt --quiet
echo -e "${GREEN}✓ Python 依賴安裝完成${NC}"

# 3. 構建前端
echo -e "\n${YELLOW}[4/6] 構建前端專案...${NC}"
if [ ! -d "web-ui" ]; then
    echo -e "${RED}✗ 錯誤: web-ui 目錄不存在${NC}"
    exit 1
fi

cd web-ui

# 檢查 node_modules 是否存在
if [ ! -d "node_modules" ]; then
    echo "首次執行，正在安裝前端依賴..."
    npm install
fi

echo "正在構建前端..."
npm run build

cd "$SCRIPT_DIR"

if [ ! -d "dist" ]; then
    echo -e "${RED}✗ 錯誤: 前端構建失敗，dist 目錄未生成${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 前端構建完成，產物已輸出到專案根目錄 dist/${NC}"

# 4. 校驗構建產物
echo -e "\n${YELLOW}[5/6] 校驗構建產物...${NC}"
echo -e "${GREEN}✓ 已確認構建產物位於專案根目錄 dist/${NC}"

# 首次啟動時設定登入帳號密碼（已設定則直接略過）
python3 setup_env.py

# 5. 啟動後端服務
echo -e "\n${YELLOW}[6/6] 啟動後端服務...${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}服務啟動中...${NC}"
echo -e "${GREEN}訪問地址: http://localhost:8000${NC}"
echo -e "${GREEN}API 文件: http://localhost:8000/docs${NC}"
echo -e "${GREEN}========================================${NC}\n"

python3 -m src.app
