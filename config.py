#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局配置文件
"""

import os
from typing import Dict, Any
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 交易系统配置
TRADING_CONFIG = {
    # 富途相关配置
    'hk_watchlist_group': os.getenv('HK_WATCHLIST_GROUP', '港股'),
    'us_watchlist_group': os.getenv('US_WATCHLIST_GROUP', '美股'),
    'min_visual_score': int(os.getenv('MIN_VISUAL_SCORE', '70')),
    'hk_dry_run': os.getenv('HK_DRY_RUN', 'True').lower() in ('true', '1', 'yes'),
    'us_dry_run': os.getenv('US_DRY_RUN', 'False').lower() in ('true', '1', 'yes'), # 默认开通（对应 IB 模拟端口 4002）
    'max_position_ratio': float(os.getenv('MAX_POSITION_RATIO', '0.2')),
    'max_total_positions': int(os.getenv('MAX_TOTAL_POSITIONS', '10')),
    
    # 交易时间配置
    'trading_hours_start': os.getenv('TRADING_HOURS_START', '09:30'),
    'trading_hours_end': os.getenv('TRADING_HOURS_END', '16:00'),
    'lunch_break_start': os.getenv('LUNCH_BREAK_START', '12:00'),
    'lunch_break_end': os.getenv('LUNCH_BREAK_END', '13:00'),
    
    # 信号时间过滤
    'max_signal_age_hours': int(os.getenv('MAX_SIGNAL_AGE_HOURS', '1')),
    
    # 风险管理与 ATR 止损配置 (方案丙)
    'atr_stop_init': float(os.getenv('ATR_STOP_INIT', '1.2')),       # 初始固定止损倍数
    'atr_stop_trail': float(os.getenv('ATR_STOP_TRAIL', '2.5')),     # 移动止损回撤倍数
    'atr_profit_threshold': float(os.getenv('ATR_PROFIT_THRESHOLD', '1.5')), # 触发移动止损的获利倍数
    
    # 策略选型适配 (对齐 30M 无后顾网格)
    'enable_stop_loss': False,               # 港股冠军参数：无硬性止损
    'enable_resonance_5m': True,             # 🌌 恢复 30M + 5M 双周期嵌套共振买入校验
    
    # Discord 配置

    'discord': {
        'token': os.getenv('DISCORD_BOT_TOKEN', ''),
        'channel_id': os.getenv('DISCORD_CHANNEL_ID', ''),
        'allowed_user_ids': os.getenv('DISCORD_ALLOWED_USER_IDS', '').split(',') if os.getenv('DISCORD_ALLOWED_USER_IDS') else [],
    }
}

# 各市场优化后的专属策略参数 (根据 2026-03-24 回测寻优结果更新)
MARKET_SPECIFIC_CONFIG = {
    'CN': {
        'bs_type': '1,1p,2,2s,3a,3b',
        'atr_stop_trail': 1.5,
    },
    'HK': {
        'bs_type': '2,2s,3a,3b',
        'atr_stop_trail': 1.5,
    },
    'US': {
        'bs_type': '2,2s,3a,3b',
        'atr_stop_trail': 3.0,
    }
}

# 内存管理与上下文优化配置
MEMORY_CONFIG = {
    'archive_threshold_hours': 48,  # 信号归档阈值 (小时)
    'keep_daily_reports': 30,       # 保留最近 30 天的每日简报
}

# 缠论配置
CHAN_CONFIG = {
    "bi_strict": True,
    "one_bi_zs": False,
    "seg_algo": "chan",
    "bs_type": '1,1p,2,2s,3a,3b',
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "divergence_rate": float("inf"),  # 无限大，禁用背驰率过滤
    "min_zs_cnt": 0,
    "bsp2_follow_1": False,
    "bsp3_follow_1": False,
    "bs1_peak": False,
    "macd_algo": "peak",
    "zs_algo": "normal",
}

# 图表配置
CHART_CONFIG = {
    "plot_kline": True,
    "plot_kline_combine": True,
    "plot_bi": True,
    "plot_seg": True,
    "plot_eigen": False,
    "plot_zs": True,
    "plot_macd": True,  # 启用MACD
    "plot_mean": False,
    "plot_channel": False,
    "plot_bsp": True,
    "plot_extrainfo": False,
    "plot_demark": False,
    "plot_marker": False,
    "plot_rsi": False,
    "plot_kdj": False,
}

# 图表参数配置
CHART_PARA = {
    "seg": {
        "color": "#9932CC",  # 紫色线段
        "width": 2
    },
    "bi": {
        "color": "#000000",  # 黑色笔
        "show_num": False
    },
    "zs": {
        "color": "#FF8C00",  # 橙色中枢
        "linewidth": 2
    },
    "bsp": {
        "fontsize": 12,
        "buy_color": "#C71585",  # 洋红色买买点 (与 AI 提示词保持高度一致)
        "sell_color": "#C71585"
    },
    "macd": {
        "width": 0.6
    },
    "figure": {
        "w": 16,
        "h": 12,
        "macd_h": 0.25,
        "grid": None
    }
}

# API配置
API_CONFIG = {
    'GOOGLE_API_KEY': os.getenv("GOOGLE_API_KEY"),
    'POLYGON_API_KEY': os.getenv("POLYGON_API_KEY", ""),
    'FINNHUB_API_KEY': os.getenv("FINNHUB_API_KEY", ""),
}

# 数据源配置
DATA_CONFIG = {
    'DEFAULT_DATA_SOURCE': 'FUTU',
    'CACHE_ENABLED': True,
    'CACHE_DIR': 'stock_cache',
}
