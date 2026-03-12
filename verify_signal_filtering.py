#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from App.HKTradingController import HKTradingController

class TestHKTradingControllerLogic(unittest.TestCase):
    def setUp(self):
        # We need to call QThread init because HKTradingController inherits from QThread
        from PyQt6.QtCore import QThread
        
        # Prevent initialization of connections in __init__
        with patch.object(HKTradingController, '__init__', lambda self: QThread.__init__(self)):
            self.controller = HKTradingController()
            self.controller.discovered_signals = {}
            self.controller.executed_signals = {}
            self.controller.current_positions = {}
            
            # Setup a mock message logger to catch emitted prints
            self.controller.log_message = MagicMock()
            
    def test_filter_signal_already_discovered(self):
        # Add a signal that was already discovered recently
        self.controller.discovered_signals["HK.00700"] = "2026-03-09 10:00:00"
        
        # Test signal that comes in at identical time
        chan_result = {
            'bsp_datetime_str': "2026-03-09 10:00:00",
            'is_buy_signal': True,
            'bsp_type': "1买"
        }
        
        result = self.controller._validate_and_filter_signal("HK.00700", chan_result, {}, False)
        self.assertFalse(result, "Should filter out signals that are exactly identical to discovered_signals")
        
    def test_filter_signal_already_holding(self):
        # Mock get_position_quantity to return 1000 for this stock
        with patch.object(self.controller, 'get_position_quantity', return_value=1000):
            chan_result = {
                'bsp_datetime_str': "2026-03-09 10:05:00",
                'is_buy_signal': True,
                'bsp_type': "2买"
            }
            
            result = self.controller._validate_and_filter_signal("HK.00700", chan_result, {}, False)
            self.assertFalse(result, "Should filter out buy signals for stocks we already hold")

if __name__ == '__main__':
    unittest.main()
