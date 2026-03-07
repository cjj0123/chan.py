#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for real-time trading integration
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from App.HKTradingController import HKTradingController
from PyQt6.QtCore import QCoreApplication
import time


def test_realtime_signal_processing():
    """Test the real-time signal processing functionality"""
    print("Testing real-time signal processing...")
    
    # Create QApplication instance (required for Qt objects)
    app = QCoreApplication(sys.argv)
    
    # Create trading controller
    controller = HKTradingController(dry_run=True)
    
    # Test signal data
    test_signal = {
        'code': 'HK.00700',
        'signal': 'BUY',
        'price': 350.0,
        'time': '2026-03-07 12:00:00'
    }
    
    try:
        # Process the test signal
        result = controller.process_realtime_signal(test_signal)
        print(f"Signal processing result: {result}")
        
        # Test sell signal
        test_signal_sell = {
            'code': 'HK.00700',
            'signal': 'SELL',
            'price': 355.0,
            'time': '2026-03-07 12:05:00'
        }
        
        result_sell = controller.process_realtime_signal(test_signal_sell)
        print(f"Sell signal processing result: {result_sell}")
        
    except Exception as e:
        print(f"Error during testing: {e}")
        return False
    
    finally:
        # Clean up
        controller.close_connections()
    
    print("Real-time signal processing test completed!")
    return True


if __name__ == "__main__":
    test_realtime_signal_processing()