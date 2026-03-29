#!/bin/bash
# 缠论交易系统 - Web 版一键全链路启动脚本 (Chanlun Bot Pro Web Launcher)

# 1. 设置项目路径 (Force change to project root directory)
PROJECT_DIR="/Users/jijunchen/Documents/Projects/Chanlun_Bot"

echo "📂 正在进入项目目录: $PROJECT_DIR"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ 错误: 找不到项目目录，请检查路径 $PROJECT_DIR 是否正确。"
    read -p "按回车键退出..."
    exit 1
fi
cd "$PROJECT_DIR"

# 0. 清理残留进程 (Cleanup zombie processes)
echo "🧹 正在彻底清理残留进程..."
# 1. 杀掉 Python 后端所有实例 (Target by module name)
pkill -f "python3 -m WebService.main" 2>/dev/null
# 2. 杀掉 Node 前端所有实例 (Target by directory/command)
pkill -f "next-dev" 2>/dev/null
# 3. 释放端口 (Port based fallback)
lsof -ti :3000 | xargs kill -9 2>/dev/null
lsof -ti :8000 | xargs kill -9 2>/dev/null
echo "⏳ 等待端口资源彻底释放..."
sleep 2

# 2. 自动化交易环境自检 (Trade Readiness Check)
echo "🔍 正在进行自动化交易环境自检..."
if ! pgrep -x "FutuOpenD" > /dev/null; then
    echo "⚠️  警告: 未检测到 FutuOpenD 在其运行环境中运行。"
    echo "   [!] 如果您不准备使用自动交易功能，可以忽略此消息。"
    echo "   [!] 如果需要交易，请先启动 FutuOpenD 并确保登录成功。"
    sleep 2
else
    echo "✅ FutuOpenD 已就绪 (FutuOpenD is running)."
fi

# 3. 启动后台服务 (FastAPI Backend Control Center)
# 显式注入 WEB_MODE=1 确保交易逻辑绕过 GUI 信号干扰
echo "🚀 启动后端交易引擎 (WebService)..."
osascript -e "tell application \"Terminal\"
    do script \"cd '$PROJECT_DIR' && source ./.venv/bin/activate && export PYTHONPATH=\$PYTHONPATH:. && export WEB_MODE=1 && while true; do echo '🔄 [Chanlun Engine] Starting Execution Controller...'; python3 -m WebService.main; echo '🛑 [Chanlun Engine] Process Exited. Restarting in 2s...'; sleep 2; done\"
    set custom title of selected tab of front window to \"Chanlun API Backend (AUTO-TRADE ON)\"
end tell"

# 4. 启动前端服务 (Nex.js Dashboard)
echo "🚀 启动前端可视化台 (WebApp)..."
osascript -e "tell application \"Terminal\"
    do script \"cd '$PROJECT_DIR/WebApp' && npm run dev\"
    set custom title of selected tab of front window to \"Chanlun Web Dashboard\"
end tell"

# 5. 等待并引导浏览器访问
echo "🌐 正在验证服务可用性并引导浏览器..."
sleep 5
open "http://localhost:3000"

echo "✅ 缠论全链路系统启动指令已发送。"
echo "请在弹出的专用终端窗口中查看[Backend]和[Frontend]的具体日志。"
sleep 2
exit 0
