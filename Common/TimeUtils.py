import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

def get_trading_duration_hours(start_time: datetime, end_time: datetime) -> float:
    """
    计算两个时间点之间的港股交易小时数（排除非交易时段）
    
    港股交易时间：
    - 上午：09:30 - 12:00 (2.5h)
    - 下午：13:00 - 16:00 (3.0h)
    - 全天共 5.5h
    - 周末和节假日不交易
    
    Args:
        start_time: 信号产生时间
        end_time: 当前时间
        
    Returns:
        交易小时数（浮点数）
    """
    try:
        import pandas_market_calendars as mcal
        
        # 获取港股交易日历
        hkex = mcal.get_calendar('XHKG')
        
        # 获取交易时间段
        # 注意：end_time 可能早于 start_time (极罕见)，或者同一天
        schedule = hkex.schedule(start_date=start_time.date(), end_date=end_time.date())
        if schedule.empty:
            return 0.0
        
        total_hours = 0.0
        
        # 遍历每个交易日
        for index, row in schedule.iterrows():
            market_open = row['market_open'].to_pydatetime().replace(tzinfo=None)
            market_close = row['market_close'].to_pydatetime().replace(tzinfo=None)
            
            # 港股通常有午休，market_calendars 返回的是全天范围
            # 对于更精确的港股计算，我们需要手动扣除午休或分段计算
            # 简化逻辑：如果是同一天，分别计算上午和下午
            
            # 理想做法：拆分上/下午
            morning_s = market_open.replace(hour=9, minute=30, second=0, microsecond=0)
            morning_e = market_open.replace(hour=12, minute=0, second=0, microsecond=0)
            afternoon_s = market_open.replace(hour=13, minute=0, second=0, microsecond=0)
            afternoon_e = market_open.replace(hour=16, minute=0, second=0, microsecond=0)
            
            # 计算上午时段
            m_start = max(start_time, morning_s)
            m_end = min(end_time, morning_e)
            if m_start < m_end:
                total_hours += (m_end - m_start).total_seconds() / 3600
                
            # 计算下午时段
            a_start = max(start_time, afternoon_s)
            a_end = min(end_time, afternoon_e)
            if a_start < a_end:
                total_hours += (a_end - a_start).total_seconds() / 3600
        
        return total_hours
    except Exception as e:
        # 备选方案：如果 mcal 失败，使用简单逻辑
        # 只扣除周末，不处理节假日，固定交易时间
        from config import TRADING_CONFIG
        
        current = start_time
        total_seconds = 0
        
        while current <= end_time:
            # 检查是否为周末
            if current.weekday() < 5:
                # 只在交易时间段内累计
                # 上午 09:30-12:00
                m_s = current.replace(hour=9, minute=30, second=0, microsecond=0)
                m_e = current.replace(hour=12, minute=0, second=0, microsecond=0)
                # 下午 13:00-16:00
                a_s = current.replace(hour=13, minute=0, second=0, microsecond=0)
                a_e = current.replace(hour=16, minute=0, second=0, microsecond=0)
                
                # 计算范围内重合部分
                # 由于是循环，这里需要处理 start_time 和 end_time 在当天的截断
                overlap_m_s = max(start_time, m_s)
                overlap_m_e = min(end_time, m_e)
                if overlap_m_s < overlap_m_e and overlap_m_s.date() == current.date():
                    total_seconds += (overlap_m_e - overlap_m_s).total_seconds()
                
                overlap_a_s = max(start_time, a_s)
                overlap_a_e = min(end_time, a_e)
                if overlap_a_s < overlap_a_e and overlap_a_s.date() == current.date():
                    total_seconds += (overlap_a_e - overlap_a_s).total_seconds()
            
            # 移动到下一天
            current = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            
        return total_seconds / 3600
