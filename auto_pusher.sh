#!/bin/bash

# ==========================================
# 自动提交员 (Main 分支直推版)
# 作用：监听 AI 完工信号，自动提交并推送到 main
# ==========================================

echo "🤖 [自动提交员-极速版] 已启动！"
echo "👀 正在当前 main 分支闭目监听 READY_FOR_REVIEW.txt 信号..."

while true; do
    # 检查是否存在信号文件
    if [ -f "READY_FOR_REVIEW.txt" ]; then
        echo "====================================="
        echo "🚨 侦测到 AI 交卷信号！准备提交流程..."
        
        # 1. 删掉信号文件（保持工作区干净）
        rm READY_FOR_REVIEW.txt
        
        # 2. 把 AI 改动的所有文件加进暂存区
        git add .
        
        # 3. 检查是否有实质性的改动（防止 AI 摸鱼没改代码却发了信号）
        if git diff-index --quiet HEAD --; then
            echo "⚠️ AI 好像什么代码都没改，跳过本次提交。"
        else
            # 4. 生成带时间戳的提交信息
            COMMIT_MSG="🤖 AI 自动更新: $(date +%m月%d日-%H:%M) (老板请审查)"
            
            # 5. 提交到本地 main
            git commit -m "$COMMIT_MSG"
            
            # 6. 直接推送到云端 main 分支
            echo "🚀 正在将最新代码推送到 GitHub origin/main..."
            git push origin main
            
            echo "✅ 推送成功！代码已上云！"
            echo "📱 老板，请打开手机 GitHub App 查看最新 Commit 的红绿对比图！"
        fi
        
        echo "🤖 继续监听下一个任务..."
        echo "====================================="
    fi
    
    # 每 10 秒钟睁眼看一次
    sleep 10
done