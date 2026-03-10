#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多市场监控控制器 (A股/美股)

负责对 A股、美股或其它指定分组进行定期缠论扫描。
逻辑：每 30 分钟扫描一次，发现新信号（1小时内）后推送 Discord 并记录日志。
特点：无交易执行，不干扰主笔港股交易，提供延迟避让。
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TRADING_CONFIG, CHAN_CONFIG, CHART_CONFIG, CHART_PARA
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE
from Plot.PlotDriver import CPlotDriver
from App.ScannerThreads import LEVEL_DATA_DAYS
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 导入 Futu
from futu import OpenQuoteContext, RET_OK

# 导入 DiscordBot (复用现有逻辑)
from App.DiscordBot import DiscordBot

logger = logging.getLogger(__name__)

class MarketMonitorController(QObject):
    """
    多市场监控控制器
    """
    log_message = pyqtSignal(str)
    
    def __init__(self, watchlist_group: str, discord_bot: DiscordBot = None, parent=None):
        super().__init__(parent)
        self.watchlist_group = watchlist_group
        self._is_running = False
        self.quote_ctx = None
        self.discord_bot = discord_bot
        
        # 创建图表临时存放目录
        self.charts_dir = "charts_monitor"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        # 信号历史记录，用于去重
        self.notified_signals_file = "monitor_notified_signals.json"
        self.notified_signals = self._load_notified_signals()

    def _load_notified_signals(self) -> Dict:
        """加载已通知信号记录"""
        if os.path.exists(self.notified_signals_file):
            try:
                with open(self.notified_signals_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载监控信号记录失败: {e}")
        return {}

    def _save_notified_signals(self):
        """同步信号记录到文件"""
        try:
            # 只保留最近 3 天的记录，防止文件无限增长
            cutoff = datetime.now() - timedelta(days=3)
            cleaned_cache = {}
            for k, v in self.notified_signals.items():
                try:
                    # 假设值是时间戳字符串 YYYY-MM-DD ...
                    t = datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
                    if t > cutoff:
                        cleaned_cache[k] = v
                except:
                    cleaned_cache[k] = v # 无法解析则保留
            
            self.notified_signals = cleaned_cache
            with open(self.notified_signals_file, 'w', encoding='utf-8') as f:
                json.dump(self.notified_signals, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存监控信号记录失败: {e}")

    def _init_futu(self):
        """初始化富途连接"""
        if self.quote_ctx is None:
            futu_config = TRADING_CONFIG.get('futu', {})
            host = futu_config.get('host', '127.0.0.1')
            port = futu_config.get('port', 11111)
            self.quote_ctx = OpenQuoteContext(host=host, port=port)
            self.log_message.emit(f"🔌 [监控] 已连接富途行情接口 ({host}:{port})")

    def _init_discord(self):
        """初始化 Discord 推送"""
        if self.discord_bot is None and TRADING_CONFIG.get('discord') and TRADING_CONFIG['discord'].get('token'):
            try:
                self.discord_bot = DiscordBot(
                    token=TRADING_CONFIG['discord']['token'],
                    channel_id=TRADING_CONFIG['discord']['channel_id'],
                    allowed_user_ids=TRADING_CONFIG['discord']['allowed_user_ids'],
                    controller=None # 仅用于监控，不接收反向指令
                )
                self.discord_bot.start()
                self.log_message.emit("🤖 [监控] Discord 推送已就绪")
            except Exception as e:
                self.log_message.emit(f"⚠️ [监控] Discord 启动失败: {e}")
        elif self.discord_bot:
            self.log_message.emit("🤖 [监控] 已关联现有 Discord 推送服务")

    def stop(self):
        self._is_running = False
        if self.quote_ctx:
            self.quote_ctx.close()
            self.quote_ctx = None
        self.log_message.emit("🛑 [监控] 监控进程已停止")

    def get_status_summary(self) -> str:
        """获取监控状态摘要"""
        run_status = "🟢 正在运行" if self._is_running else "🛑 已停止"
        summary = (
            f"🔍 **多市场监控状态摘要**\n"
            f"----------------------------------\n"
            f"▸ 监控状态: {run_status}\n"
            f"▸ 监控分组: `{self.watchlist_group}`\n"
            f"▸ 监控范围: A股/美股\n"
            f"▸ 监控周期: 30分钟 (Bar)\n"
            f"▸ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return summary

    def get_watchlist_data(self) -> Dict[str, str]:
        """获取所选自选股分组的代码和名称清单"""
        if not self.quote_ctx:
            self._init_futu()
            
        group = self.watchlist_group if self.watchlist_group not in ["全部", "All", ""] else ""
        
        ret, data = self.quote_ctx.get_user_security(group_name=group)
        if ret == RET_OK:
            # 返回 code -> name 的映射
            # 注意: get_user_security 返回的列名通常是 'name'
            name_col = 'name' if 'name' in data.columns else 'stock_name'
            return dict(zip(data['code'].tolist(), data[name_col].tolist()))
        else:
            self.log_message.emit(f"❌ [监控] 获取分组 {self.watchlist_group} 失败: {data}")
            return {}

    def run_monitor_loop(self):
        """主监控循环"""
        self._is_running = True
        self._init_futu()
        self._init_discord()
        
        self.log_message.emit(f"🚀 [监控] 开始监控分组: {self.watchlist_group} (周期: 30m)")
        
        last_scan_bar = None
        
        while self._is_running:
            try:
                now = datetime.now()
                # 计算 30 分钟 Bar 的起始时间
                current_bar = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
                
                # 如果是新的 Bar，且已经过了前 5 分钟 (避让港股交易峰值)
                if last_scan_bar is None or current_bar > last_scan_bar:
                    if now.minute % 30 >= 5: # 延迟 5 分钟扫描
                        self.log_message.emit(f"🔍 [监控] 触发周期性扫描 ({current_bar.strftime('%H:%M')})...")
                        self._perform_scan()
                        last_scan_bar = current_bar
                
                # 每分钟检查一次
                for _ in range(60):
                    if not self._is_running: break
                    time.sleep(1)
                    
            except Exception as e:
                self.log_message.emit(f"⚠️ [监控] 循环遇到异常: {e}")
                time.sleep(10)

    def _perform_scan(self):
        """执行实际的扫描任务"""
        watchlist = self.get_watchlist_data()
        if not watchlist:
            return
            
        codes = list(watchlist.keys())
        self.log_message.emit(f"📋 [监控] 正在扫描 {len(codes)} 只股票...")
        
        for code in codes:
            if not self._is_running: break
            try:
                name = watchlist.get(code, "")
                self._scan_single_stock(code, name=name)
            except Exception as e:
                logger.error(f"Scan error for {code}: {e}")
            # 稍微降低频率，避免 API 频率超限
            time.sleep(0.5)
            
        self.log_message.emit(f"✅ [监控] 本轮扫描完成.")

    def _scan_single_stock(self, code: str, name: str = ""):
        """分析单只股票"""
        days = LEVEL_DATA_DAYS.get(KL_TYPE.K_30M, 90)
        begin_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # 数据源选择逻辑
        data_src = DATA_SRC.FUTU # 默认使用富途
        
        # 美股逻辑：识别 US. 前缀，切换到更高质量的数据源
        if code.upper().startswith("US."):
            from config import API_CONFIG
            if API_CONFIG.get('POLYGON_API_KEY'):
                data_src = DATA_SRC.POLYGON
                # self.log_message.emit(f"📡 [监控] {code} 使用 Polygon 数据源")
            else:
                data_src = DATA_SRC.YFINANCE
                # self.log_message.emit(f"📡 [监控] {code} 使用 YFinance 数据源")

        chan = CChan(
            code=code,
            begin_time=begin_time,
            data_src=data_src,
            lv_list=[KL_TYPE.K_30M],
            config=CChanConfig(CHAN_CONFIG),
            autype=AUTYPE.QFQ
        )
        
        if not chan.lv_list or len(chan[chan.lv_list[0]]) == 0:
            return

        # 获取最新买卖点
        bsp_list = chan.get_latest_bsp(number=0)
        now = datetime.now()
        
        # 信号时效性过滤 (1小时内)
        new_signals = []
        for bsp in bsp_list:
            b_time = bsp.klu.time
            bsp_dt = datetime(b_time.year, b_time.month, b_time.day, b_time.hour, b_time.minute, b_time.second)
            # 简单时差判断 (A/US 通用，不涉及复杂的港股日历计算)
            if (now - bsp_dt).total_seconds() <= 3600:
                new_signals.append(bsp)

        if new_signals:
            for sig in new_signals:
                # 去重逻辑：代码 + 信号时间 + 类型
                sig_key = f"{code}_{str(sig.klu.time)}_{sig.type2str()}"
                if sig_key in self.notified_signals:
                    continue
                
                # 记录并保存
                self.notified_signals[sig_key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save_notified_signals()
                
                self._notify_signal(code, sig, chan, name=name)

    def _notify_signal(self, code: str, bsp, chan, name: str = ""):
        """推送信号日志和 Discord 图表"""
        sig_type = "买点" if bsp.is_buy else "卖点"
        msg = f"🌟 [A/US 监控信号] {code} ({name}) 发现 {sig_type} {bsp.type2str()} | 时间: {bsp.klu.time} | 价格: {bsp.klu.close:.2f}"
        
        self.log_message.emit(msg)
        
        # 生成图表
        chart_path = os.path.abspath(os.path.join(self.charts_dir, f"{code.replace('.', '_')}_{datetime.now().strftime('%H%M%S')}.png"))
        try:
            # 使用完整的图表配置和参数，确保 K线、笔、段、中枢和 MACD 全部显示
            plot_driver = CPlotDriver(chan, plot_config=CHART_CONFIG, plot_para=CHART_PARA)
            # 使用 tight 布局防止标签被裁剪，并设置高分辨率
            plt.savefig(chart_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            
            # Discord 推送
            if self.discord_bot:
                import asyncio
                # 注意：DiscordBot.send_notification 是协程，需要通过 run_coroutine_threadsafe 在 bot 线程执行
                if hasattr(self.discord_bot, 'loop') and self.discord_bot.loop:
                    coro = self.discord_bot.send_notification(f"📈 **多市场预警**\n{msg}", chart_path)
                    asyncio.run_coroutine_threadsafe(coro, self.discord_bot.loop)
                else:
                    self.log_message.emit("⚠️ [监控] Discord 机器人循环未绪，无法推送")
        except Exception as e:
            self.log_message.emit(f"⚠️ [监控] 信号图表生成或推送失败: {e}")

    def _cleanup_charts(self):
        """清理过期的图表图片"""
        now = time.time()
        for f in os.listdir(self.charts_dir):
            path = os.path.join(self.charts_dir, f)
            if os.stat(path).st_mtime < now - 86400: # 超过24小时
                os.remove(path)
