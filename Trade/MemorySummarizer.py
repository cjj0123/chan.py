#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MemorySummarizer.py - 解决上下文撑爆的核心组件
1. 信号归档: 将 discovered_signals.json 中的旧记录移至 memory/archive/
2. 每日快报: 生成当日交易摘要 memory/daily/YYYY-MM-DD.md
3. 活跃上下文: 维护 memory/active_context.md (AI 专用 Cheat Sheet)
"""

import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

class MemorySummarizer:
    def __init__(self, root_dir=None):
        self.root_dir = root_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.memory_dir = os.path.join(self.root_dir, "memory")
        self.archive_dir = os.path.join(self.memory_dir, "archive")
        self.daily_dir = os.path.join(self.memory_dir, "daily")
        self.size_threshold_kb = 100  # 触发归档的文件大小阈值 (KB)
        self.max_lines_in_log = 5000  # 日志摘要时的行数限制
        
        # 确保目录存在
        for d in [self.memory_dir, self.archive_dir, self.daily_dir]:
            os.makedirs(d, exist_ok=True)

    def archive_signals(self, threshold_hours=48):
        """将过期信号移出主文件以减小上下文压力"""
        signal_file = os.path.join(self.root_dir, "discovered_signals.json")
        if not os.path.exists(signal_file):
            return 0
            
        try:
            with open(signal_file, 'r', encoding='utf-8') as f:
                signals = json.load(f)
        except Exception:
            return 0

        now = datetime.now()
        threshold_dt = now - timedelta(hours=threshold_hours)
        
        active_signals = {}
        archived_signals = {}
        
        for key, ts_str in signals.items():
            try:
                # 兼容多种时间格式
                if ' ' in ts_str:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                else:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d")
                    
                if dt > threshold_dt:
                    active_signals[key] = ts_str
                else:
                    archived_signals[key] = ts_str
            except ValueError:
                active_signals[key] = ts_str # 格式不匹配的保留，防止误删

        if archived_signals:
            # 存入月度归档文件
            archive_filename = f"signals_archive_{now.strftime('%Y%m')}.json"
            archive_path = os.path.join(self.archive_dir, archive_filename)
            
            existing_archive = {}
            if os.path.exists(archive_path):
                try:
                    with open(archive_path, 'r', encoding='utf-8') as f:
                        existing_archive = json.load(f)
                except: pass
            
            existing_archive.update(archived_signals)
            with open(archive_path, 'w', encoding='utf-8') as f:
                json.dump(existing_archive, f, indent=4, ensure_ascii=False)
                
            # 更新主文件
            with open(signal_file, 'w', encoding='utf-8') as f:
                json.dump(active_signals, f, indent=4, ensure_ascii=False)
                
        return len(archived_signals)

    def refresh_active_context(self):
        """生成 AI 专用的 Cheat Sheet: memory/active_context.md"""
        context_file = os.path.join(self.memory_dir, "active_context.md")
        
        # 1. 获取当前持仓 (从 executed_signals.json 简单模拟，实际可从 DB 读取)
        executed_file = os.path.join(self.root_dir, "executed_signals.json")
        positions = {}
        if os.path.exists(executed_file):
            try:
                with open(executed_file, 'r', encoding='utf-8') as f:
                    positions = json.load(f)
            except: pass

        # 2. 获取最新信号
        signal_file = os.path.join(self.root_dir, "discovered_signals.json")
        recent_signals = []
        if os.path.exists(signal_file):
            try:
                with open(signal_file, 'r', encoding='utf-8') as f:
                    all_signals = json.load(f)
                    # 排序取出最近 5 个
                    sorted_sigs = sorted(all_signals.items(), key=lambda x: x[1], reverse=True)
                    recent_signals = sorted_sigs[:5]
            except: pass

        lines = [
            "# 🤖 缠论系统当前上下文摘要 (Active Context)",
            f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "\n## 📈 1. 活跃持仓监控",
            "| 股票代码 | 执行时间 | 备注 |",
            "| --- | --- | --- |"
        ]
        
        if positions:
            for code, ts in list(positions.items())[-10:]: # 只看最近 10 个
                lines.append(f"| {code} | {ts} | 已入场 |")
        else:
            lines.append("| 无活跃持仓 | - | - |")

        lines.append("\n## 🎯 2. 最近捕捉信号 (Top 5)")
        if recent_signals:
            for sig, ts in recent_signals:
                lines.append(f"- **{sig}**: {ts}")
        else:
            lines.append("- 目前无新鲜信号")

        lines.append("\n## 🛡️ 3. 系统状态")
        lines.append(f"- **信号池大小**: {len(recent_signals)} 条活跃记录")
        lines.append(f"- **归档状态**: 48h 前记录已自动移至 `memory/archive/`")
        lines.append(f"\n> [!TIP]\n> 此文件由 MemorySummarizer 自动维护，旨在解决 AI 上下文爆炸问题。")

        with open(context_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
            
        return context_file

    def generate_daily_report(self):
        """生成每日简报"""
        today_str = datetime.now().strftime('%Y-%m-%d')
        report_path = os.path.join(self.daily_dir, f"{today_str}.md")
        
        # 简单实现：将 active_context 复制并增加今日总结标题
        self.refresh_active_context()
        active_context_path = os.path.join(self.memory_dir, "active_context.md")
        
        with open(active_context_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        report_content = f"# 🗓️ 缠论交易日总结 ({today_str})\n\n" + content
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
            
        return report_path

    def check_and_compress(self):
        """主动检查文件大小，如果过载则强制压缩"""
        signal_file = os.path.join(self.root_dir, "discovered_signals.json")
        if os.path.exists(signal_file):
            size_kb = os.path.getsize(signal_file) / 1024
            if size_kb > self.size_threshold_kb:
                # 触发紧急归档 (缩短阈值到 24 小时)
                return self.run(emergency=True)
        return 0, None

    def run(self, emergency=False):
        """执行全套总结流程"""
        threshold = 24 if emergency else 48
        archived_count = self.archive_signals(threshold_hours=threshold)
        report_path = self.generate_daily_report()
        self.refresh_active_context()
        return archived_count, report_path

if __name__ == "__main__":
    summarizer = MemorySummarizer()
    count, r_path = summarizer.run()
    print(f"✅ Memory Summarize 完成!")
    print(f"- 归档旧信号: {count} 条")
    print(f"- 生成每日简报: {r_path}")
