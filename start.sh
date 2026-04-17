#!/usr/bin/env bash
# ============================================================
#  OpenClaw 一键启动脚本
#  用法: bash start.sh
# ============================================================

set -euo pipefail

# ---------- 颜色定义 ----------
BOLD="\033[1m"
GREEN="\033[1;32m"
CYAN="\033[1;36m"
YELLOW="\033[1;33m"
RED="\033[1;31m"
RESET="\033[0m"

# ---------- 路径 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/src/server.py"
URL="http://127.0.0.1:5000"

echo ""
echo -e "${CYAN}${BOLD}  ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗██╗      █████╗ ██╗    ██╗"
echo -e "${CYAN}  ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝██║     ██╔══██╗██║    ██║"
echo -e "${CYAN}  ██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║     ██║     ███████║██║ █╗ ██║"
echo -e "${CYAN}  ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║     ██║     ██╔══██║██║███╗██║"
echo -e "${CYAN}  ╚██████╔╝██║     ███████╗██║ ╚████║╚██████╗███████╗██║  ██║╚███╔███╔╝"
echo -e "${CYAN}   ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝ ${RESET}"
echo ""
echo -e "${BOLD}  🤖 OpenClaw AI Trading Engine${RESET}"
echo -e "  ──────────────────────────────────────────"
echo ""

# ---------- 检测 Python ----------
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY_VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}  ✗ 未找到 Python 3.9+，请先安装 Python: https://python.org${RESET}"
    exit 1
fi

echo -e "${GREEN}  ✓${RESET} 检测到 Python → $($PYTHON_CMD --version)"

# ---------- 检测并安装依赖 ----------
echo -e "  📦 检查 Python 依赖..."
MISSING=()
for pkg in flask flask_cors requests; do
    if ! $PYTHON_CMD -c "import $pkg" &>/dev/null 2>&1; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "${YELLOW}  ⚠ 缺少依赖: ${MISSING[*]}，正在自动安装...${RESET}"
    $PYTHON_CMD -m pip install --quiet "${MISSING[@]}"
    echo -e "${GREEN}  ✓${RESET} 依赖安装完成"
else
    echo -e "${GREEN}  ✓${RESET} 所有依赖已满足"
fi

# ---------- 检测端口是否被占用 ----------
if lsof -i :5000 -sTCP:LISTEN &>/dev/null 2>&1; then
    echo ""
    echo -e "${YELLOW}  ⚠ 端口 5000 已被占用，可能服务已经在运行。${RESET}"
    echo -e "  → 直接打开: ${CYAN}${URL}${RESET}"
    echo ""
    # 尝试打开浏览器
    if command -v open &>/dev/null; then
        open "$URL"
    fi
    exit 0
fi

# ---------- 加载 .env（如果存在）----------
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo -e "${GREEN}  ✓${RESET} 加载 .env 环境变量"
    set -a
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/.env"
    set +a
fi

# ---------- 启动服务 ----------
echo ""
echo -e "${BOLD}  🚀 启动 OpenClaw 服务器...${RESET}"
echo -e "  ──────────────────────────────────────────"

# 优雅退出处理
cleanup() {
    echo ""
    echo -e "${YELLOW}  ⏹  正在关闭服务器...${RESET}"
    kill "$SERVER_PID" 2>/dev/null || true
    echo -e "${GREEN}  ✓  已安全退出。再见！${RESET}"
    echo ""
    exit 0
}
trap cleanup INT TERM

# 后台启动服务器
PYTHON_CMD="$PYTHON_CMD" $PYTHON_CMD "$SERVER" &
SERVER_PID=$!

# ---------- 等待服务就绪 ----------
echo -ne "  ⏳ 等待服务就绪"
READY=false
for i in $(seq 1 20); do
    sleep 0.5
    if curl -s --max-time 1 "$URL" &>/dev/null; then
        READY=true
        break
    fi
    echo -ne "."
done
echo ""

if [ "$READY" = true ]; then
    echo -e "${GREEN}  ✓${RESET} 服务已就绪！"
else
    echo -e "${YELLOW}  ⚠ 服务启动中，请稍候手动访问...${RESET}"
fi

echo ""
echo -e "  ┌─────────────────────────────────────────┐"
echo -e "  │  📊 Dashboard:  ${CYAN}${BOLD}${URL}${RESET}        │"
echo -e "  │  ⌨️  按 Ctrl+C 停止服务                  │"
echo -e "  └─────────────────────────────────────────┘"
echo ""

# 自动打开浏览器（macOS）
if command -v open &>/dev/null && [ "$READY" = true ]; then
    open "$URL"
fi

# 等待服务器进程（保持前台运行）
wait "$SERVER_PID"
