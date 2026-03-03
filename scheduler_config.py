#!/usr/bin/env python3
"""
港股定时扫描任务配置
根据港股交易时间配置扫描周期
"""

from datetime import datetime, time
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 港股交易时间段
# 开市前竞价：09:00-09:15（可撤单 09:00-09:15，不可撤单 09:15-09:20，对盘 09:20-09:22）
# 早市持续交易：09:30-12:00
# 午市持续交易：13:00-16:00
# 收市竞价：16:00-16:10（可撤单 16:00-16:06，不可撤单 16:06-16:08，对盘 16:08-16:10）

SCHEDULE_CONFIG = {
    # 开盘前扫描 - 竞价限价盘（09:22 对盘后分析，09:30 执行）
    'pre_market': {
        'time': '09:24',
        'order_type': '竞价限价盘',
        'description': '开盘前扫描 - 分析竞价对盘结果',
        'enabled': True
    },
    
    # 盘中扫描 - 增强限价盘（每 30 分钟）
    'intraday': {
        'times': [
            '10:01', '10:31', '11:01', 
            # 11:31 的扫描留到 13:00 执行（避开午间休市）
            '13:01', '13:31', '14:01', 
            '14:31', '15:01', '15:31'
        ],
        'order_type': '增强限价盘',
        'description': '盘中定时扫描 - 每 30 分钟',
        'enabled': True,
        'midday_catch': {
            # 11:31 的扫描在 13:00 执行
            '11:31': '13:00'
        }
    },
    
    # 收盘前扫描 - 增强限价盘（16:00 前执行）
    'pre_close': {
        'time': '15:55',
        'order_type': '增强限价盘',
        'description': '收盘前扫描 - 尾盘机会',
        'enabled': True
    },
    
    # 收市竞价扫描 - 竞价限价盘（16:06 前执行，可撤单时段）
    'closing_auction': {
        'time': '16:01',
        'order_type': '竞价限价盘',
        'description': '收市竞价扫描 - 可撤单时段',
        'enabled': True
    }
}

# 周末和节假日不交易
WEEKEND_DAYS = [5, 6]  # Saturday=5, Sunday=6

# 港股节假日（2026 年示例，需要根据实际更新）
HKG_HOLIDAYS_2026 = [
    '2026-01-01',  # 元旦
    '2026-01-22',  # 农历年初三
    '2026-01-23',  # 农历年初四
    '2026-04-03',  # 清明节
    '2026-04-06',  # 复活节星期一
    '2026-05-01',  # 劳动节
    '2026-05-25',  # 佛诞
    '2026-06-19',  # 端午节
    '2026-07-01',  # 香港特区成立纪念日
    '2026-09-28',  # 中秋节
    '2026-10-01',  # 国庆节
    '2026-10-21',  # 重阳节
    '2026-12-25',  # 圣诞节
    '2026-12-26',  # 圣诞节后第一个周日
    '2026-12-28',  # 圣诞节后第一个周日（补假）
]


def is_trading_day(date: datetime = None) -> bool:
    """检查是否为港股交易日"""
    if date is None:
        date = datetime.now()
    
    # 检查周末
    if date.weekday() in WEEKEND_DAYS:
        return False
    
    # 检查节假日
    date_str = date.strftime('%Y-%m-%d')
    if date_str in HKG_HOLIDAYS_2026:
        return False
    
    return True


def get_next_scan_time(current_time: datetime = None) -> Dict[str, str]:
    """获取下一次扫描时间"""
    if current_time is None:
        current_time = datetime.now()
    
    current_str = current_time.strftime('%H:%M')
    
    # 收集所有扫描时间点
    all_times = []
    
    # 开盘前
    if SCHEDULE_CONFIG['pre_market']['enabled']:
        all_times.append({
            'time': SCHEDULE_CONFIG['pre_market']['time'],
            'type': 'pre_market',
            'order_type': SCHEDULE_CONFIG['pre_market']['order_type']
        })
    
    # 盘中
    if SCHEDULE_CONFIG['intraday']['enabled']:
        for t in SCHEDULE_CONFIG['intraday']['times']:
            all_times.append({
                'time': t,
                'type': 'intraday',
                'order_type': SCHEDULE_CONFIG['intraday']['order_type']
            })
    
    # 收盘前
    if SCHEDULE_CONFIG['pre_close']['enabled']:
        all_times.append({
            'time': SCHEDULE_CONFIG['pre_close']['time'],
            'type': 'pre_close',
            'order_type': SCHEDULE_CONFIG['pre_close']['order_type']
        })
    
    # 收市竞价
    if SCHEDULE_CONFIG['closing_auction']['enabled']:
        all_times.append({
            'time': SCHEDULE_CONFIG['closing_auction']['time'],
            'type': 'closing_auction',
            'order_type': SCHEDULE_CONFIG['closing_auction']['order_type']
        })
    
    # 排序
    all_times.sort(key=lambda x: x['time'])
    
    # 找到下一个时间点
    for scan in all_times:
        if scan['time'] > current_str:
            return {
                'next_time': scan['time'],
                'type': scan['type'],
                'order_type': scan['order_type'],
                'seconds_until': calculate_seconds_until(scan['time'], current_time)
            }
    
    # 如果今天没有更多扫描，返回明天第一次扫描
    return {
        'next_time': all_times[0]['time'] if all_times else '09:24',
        'type': 'pre_market',
        'order_type': '竞价限价盘',
        'message': '今日扫描已结束，下次扫描为明日开盘前'
    }


def calculate_seconds_until(target_time: str, current_time: datetime) -> int:
    """计算距离目标时间还有多少秒"""
    hour, minute = map(int, target_time.split(':'))
    target = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    if target <= current_time:
        # 目标时间已过，加一天
        from datetime import timedelta
        target += timedelta(days=1)
    
    return int((target - current_time).total_seconds())


def print_schedule():
    """打印完整的扫描时间表"""
    print("\n" + "="*60)
    print("📅 港股定时扫描任务配置")
    print("="*60)
    
    print("\n⏰ 开盘前扫描")
    if SCHEDULE_CONFIG['pre_market']['enabled']:
        print(f"   {SCHEDULE_CONFIG['pre_market']['time']} - {SCHEDULE_CONFIG['pre_market']['description']}")
        print(f"   订单类型：{SCHEDULE_CONFIG['pre_market']['order_type']}")
    
    print("\n⏰ 盘中扫描 (每 30 分钟)")
    if SCHEDULE_CONFIG['intraday']['enabled']:
        for t in SCHEDULE_CONFIG['intraday']['times']:
            print(f"   {t} - {SCHEDULE_CONFIG['intraday']['description']}")
        print(f"   订单类型：{SCHEDULE_CONFIG['intraday']['order_type']}")
        if 'midday_catch' in SCHEDULE_CONFIG['intraday']:
            for orig, new in SCHEDULE_CONFIG['intraday']['midday_catch'].items():
                print(f"   ⚠️  {orig} → {new} (午间休市调整)")
    
    print("\n⏰ 收盘前扫描")
    if SCHEDULE_CONFIG['pre_close']['enabled']:
        print(f"   {SCHEDULE_CONFIG['pre_close']['time']} - {SCHEDULE_CONFIG['pre_close']['description']}")
        print(f"   订单类型：{SCHEDULE_CONFIG['pre_close']['order_type']}")
    
    print("\n⏰ 收市竞价扫描")
    if SCHEDULE_CONFIG['closing_auction']['enabled']:
        print(f"   {SCHEDULE_CONFIG['closing_auction']['time']} - {SCHEDULE_CONFIG['closing_auction']['description']}")
        print(f"   订单类型：{SCHEDULE_CONFIG['closing_auction']['order_type']}")
    
    print("\n" + "="*60)
    print(f"📊 全年交易日：约 250 天 (排除周末和 {len(HKG_HOLIDAYS_2026)} 个港股节假日)")
    print("="*60 + "\n")


if __name__ == '__main__':
    print_schedule()
    
    # 显示下次扫描时间
    next_scan = get_next_scan_time()
    print(f"\n🔜 下次扫描：{next_scan['next_time']} ({next_scan['type']})")
    print(f"   订单类型：{next_scan['order_type']}")
    if 'seconds_until' in next_scan:
        print(f"   距离：{next_scan['seconds_until']} 秒")
    if 'message' in next_scan:
        print(f"   说明：{next_scan['message']}")
