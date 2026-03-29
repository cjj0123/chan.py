#!/bin/bash
# 缠论交易系统 - Web 版一键启动脚本 (Chanlun Bot Web Launcher)

# 1. 设置项目路径 (Force change to project root directory)
PROJECT_DIR="/Users/jijunchen/Documents/Projects/Chanlun_Bot"

echo "📂 正在进入项目目录: $PROJECT_DIR"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ 错误: 找不到项目目录，请检查路径是否正确。"
    read -p "按回车键退出..."
    exit 1
fi
cd "$PROJECT_DIR"

# 0. 清理残留进程 (Cleanup zombie processes on ports 3000 and 8000)
echo "🧹 正在检查并清理端口 3000 (前端) 和 8000 (后端) 的残留进程..."
lsof -ti :3000 | xargs kill -9 2>/dev/null
lsof -ti :8000 | xargs kill -9 2>/dev/null
sleep 1

# 2. 检查 .venv 虚拟环境
VENV_PATH="./.venv/bin/activate"
if [ ! -f "$VENV_PATH" ]; then
    echo "⚠️ 找不到 .venv 虚拟环境，后端启动可能受影响。"
fi

# 3. 启动后台服务 (FastAPI Backend)
# 使用 AppleScript 打开一个新窗口运行后端进程
echo "🚀 启动后端服务 (WebService)..."
osascript -e "tell application \"Terminal\"
    do script \"cd '$PROJECT_DIR' && source ./.venv/bin/activate && export PYTHONPATH=\$PYTHONPATH:. && while true; do echo '🔄 [Chanlun Engine] Starting...'; python3 -m WebService.main; echo '🛑 [Chanlun Engine] Process Exited. Restarting in 2s...'; sleep 2; done\"
    set custom title of selected tab of front window to \"Chanlun API Backend\"
end tell"

# 4. 启动前端服务 (Next.js Frontend)
# 使用 AppleScript 打开另一个新窗口运行前端进程
echo "🚀 启动前端服务 (WebApp)..."
osascript -e "tell application \"Terminal\"
    do script \"cd '$PROJECT_DIR/WebApp' && npm run dev\"
    set custom title of selected tab of front window to \"Chanlun Web Frontend\"
end tell"

# 5. 等待稍许并打开浏览器
echo "🌐 正在打开浏览器..."
sleep 3
open "http://localhost:3000"

echo "✅ 启动指令已发送。请在弹出的终端窗口中查看进度。"
sleep 2
exit 0
