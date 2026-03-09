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
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TRADING_CONFIG, CHAN_CONFIG
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
    
    def __init__(self, watchlist_group: str, parent=None):
        super().__init__(parent)
        self.watchlist_group = watchlist_group
        self._is_running = False
        self.quote_ctx = None
        self.discord_bot = None
        
        # 创建图表临时存放目录
        self.charts_dir = "charts_monitor"
        os.makedirs(self.charts_dir, exist_ok=True)

    def _init_futu(self):
        """初始化富途连接"""
        if self.quote_ctx is None:
            host = TRADING_CONFIG['futu'].get('host', '127.0.0.1')
            port = TRADING_CONFIG['futu'].get('port', 11111)
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

    def stop(self):
        self._is_running = False
        if self.quote_ctx:
            self.quote_ctx.close()
            self.quote_ctx = None
        self.log_message.emit("🛑 [监控] 监控进程已停止")

    def get_watchlist_codes(self) -> List[str]:
        """获取所选自选股分组的代码列表"""
        if not self.quote_ctx:
            self._init_futu()
            
        ret, data = self.quote_ctx.get_user_security(self.watchlist_group)
        if ret == RET_OK:
            return data['code'].tolist()
        else:
            self.log_message.emit(f"❌ [监控] 获取分组 {self.watchlist_group} 失败: {data}")
            return []

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
        codes = self.get_watchlist_codes()
        if not codes:
            return
            
        self.log_message.emit(f"📋 [监控] 正在扫描 {len(codes)} 只股票...")
        
        for code in codes:
            if not self._is_running: break
            try:
                self._scan_single_stock(code)
            except Exception as e:
                logger.error(f"Scan error for {code}: {e}")
            # 稍微降低频率，避免 API 频率超限
            time.sleep(0.5)
            
        self.log_message.emit(f"✅ [监控] 本轮扫描完成.")

    def _scan_single_stock(self, code: str):
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
                self._notify_signal(code, sig, chan)

    def _notify_signal(self, code: str, bsp, chan):
        """推送信号日志和 Discord 图表"""
        sig_type = "买点" if bsp.is_buy else "卖点"
        msg = f"🌟 [A/US 监控信号] {code} 发现 {sig_type} {bsp.type2str()} | 时间: {bsp.klu.time} | 价格: {bsp.klu.close:.2f}"
        
        self.log_message.emit(msg)
        
        # 生成图表
        chart_path = os.path.abspath(os.path.join(self.charts_dir, f"{code.replace('.', '_')}_{datetime.now().strftime('%H%M%S')}.png"))
        try:
            # 增加 bsp 绘图配置以在图表中显示买卖点
            plot_driver = CPlotDriver(chan, plot_config='bsp')
            plot_driver.save2img(chart_path)
            
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
