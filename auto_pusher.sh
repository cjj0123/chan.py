#!/bin/bash

# 这是一个自动监听并推送到远端的脚本

echo "🤖 [自动提交员] 已启动！正在闭目养神，等待 AI 提交 READY_FOR_REVIEW.txt 信号..."

while true; do
    # 检查是否存在信号文件
    if [ -f "READY_FOR_REVIEW.txt" ]; then
        echo "====================================="
        echo "🚨 收到 AI 交卷信号！开始打包代码..."
        
        # 1. 删掉信号文件（不需要把它传到云端）
        rm READY_FOR_REVIEW.txt
        
        # 2. 生成一个带时间戳的专属分支名 (例如: ai-fix-20231025-1430)
        BRANCH_NAME="ai-fix-$(date +%Y%m%d-%H%M)"
        
        # 3. 创建并切换到新分支
        git checkout -b $BRANCH_NAME
        
        # 4. 把 AI 改动的所有文件加进暂存区
        git add .
        
        # 5. 提交代码
        git commit -m "🤖 AI 自动提交：等待老板 (手机端) 审查合并"
        
        # 6. 推送到云端 (GitHub/Gitee)
        echo "🚀 正在将分支 $BRANCH_NAME 推送到云端..."
        git push -u origin $BRANCH_NAME
        
        # 7. （关键安全步）切回主分支，并清空本地改动，保持本地干净，等老板合并后再拉取
        git checkout main
        git reset --hard origin/main
        
        echo "✅ 提交流程完毕！已清扫本地战场。老板请看手机！"
        echo "🤖 继续监听下一个任务..."
        echo "====================================="
    fi
    
    # 每 10 秒钟睁眼看一次
    sleep 10
done