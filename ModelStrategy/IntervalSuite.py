"""
Interval Suite (QuJianTao) Strategy Logic

This module implements the interval suite strategy for confirming 30m buy/sell points
with 5m data structure.
"""

from typing import List, Optional, Tuple
from BuySellPoint.BS_Point import CBS_Point
from Common.CEnum import KL_TYPE
from Chan import CChan


def check_interval_suite(chan_obj: CChan, latest_30m_bsp: CBS_Point) -> Optional[CBS_Point]:
    """
    Check if a 30m buy/sell point is confirmed by the 5m structure.
    
    Args:
        chan_obj: The CChan object containing both 30m and 5m data
        latest_30m_bsp: The latest 30m buy/sell point to be confirmed
        
    Returns:
        The confirming 5m buy/sell point if confirmation exists, None otherwise
    """
    # Get all 5m buy/sell points
    all_5m_bsps: List[CBS_Point] = chan_obj.get_latest_bsp(idx=KL_TYPE.K_5M, number=0)
    
    if not all_5m_bsps:
        return None
    
    # Get the 30m K-line time for reference
    bsp_30m_time = latest_30m_bsp.klu.time
    
    # Find the most recent 5m BSP that is of the same type and occurs around the same time
    for bsp_5m in all_5m_bsps:
        # Check if the 5m BSP is of the same type (buy/sell) as the 30m BSP
        if bsp_5m.is_buy != latest_30m_bsp.is_buy:
            continue
            
        # Check if the 5m BSP time is within a reasonable range of the 30m BSP
        # For interval suite, the 5m confirmation should be close to or after the 30m signal
        if bsp_5m.klu.time >= bsp_30m_time:
            # Found a confirming 5m BSP
            return bsp_5m
    
    # If no direct confirmation found, check if there's a 5m BSP that occurred 
    # just before the 30m BSP (which could still be valid for early detection)
    for bsp_5m in all_5m_bsps:
        if bsp_5m.is_buy != latest_30m_bsp.is_buy:
            continue
            
        # Allow 5m BSP to occur up to 30 minutes before the 30m BSP (one 30m period)
        time_diff = (bsp_30m_time - bsp_5m.klu.time).total_seconds()
        if 0 <= time_diff <= 1800:  # 30 minutes in seconds
            return bsp_5m
    
    return None


def get_interval_suite_signal(chan_obj: CChan) -> Optional[Tuple[str, float, str]]:
    """
    Get the latest interval suite confirmed signal.
    
    Args:
        chan_obj: The CChan object containing both 30m and 5m data
        
    Returns:
        Tuple of (signal_type, price, time) if a confirmed signal exists, None otherwise
    """
    # Get the latest 30m buy/sell points
    latest_30m_bsps: List[CBS_Point] = chan_obj.get_latest_bsp(idx=KL_TYPE.K_30M, number=1)
    
    if not latest_30m_bsps:
        return None
        
    latest_30m_bsp = latest_30m_bsps[0]
    
    # Check for interval suite confirmation
    confirming_5m_bsp = check_interval_suite(chan_obj, latest_30m_bsp)
    
    if confirming_5m_bsp:
        signal_type = "BUY" if latest_30m_bsp.is_buy else "SELL"
        price = latest_30m_bsp.klu.close
        time_str = str(latest_30m_bsp.klu.time)
        return (signal_type, price, time_str)
    
    return None