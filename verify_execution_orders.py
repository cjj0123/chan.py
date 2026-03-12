#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from App.HKTradingController import HKTradingController
from Trade.RiskManager import RiskManager

class TestExecutionOrders(unittest.TestCase):
    def setUp(self):
        from PyQt6.QtCore import QThread
        with patch.object(HKTradingController, '__init__', lambda self: QThread.__init__(self)):
            self.controller = HKTradingController()
            self.controller.log_message = MagicMock()
            self.controller.trd_ctx = MagicMock()
            self.controller.trd_env = MagicMock()
            self.controller.risk_manager = MagicMock(spec=RiskManager)
            self.controller.discord_bot = MagicMock()
            
    def test_execute_trade_buy(self):
        # Mock Futu trade context
        import pandas as pd
        mock_data = pd.DataFrame([{'order_id': '12345'}])
        self.controller.trd_ctx.place_order.return_value = (0, mock_data)
        self.controller.is_in_continuous_trading_session = MagicMock(return_value=True)
        
        result = self.controller.execute_trade("HK.00700", "BUY", 200, 300.0)
        self.assertTrue(result, "Order placement should succeed")
        self.controller.trd_ctx.place_order.assert_called_once()

    def test_execute_trade_sell(self):
        import pandas as pd
        mock_data = pd.DataFrame([{'order_id': '12346'}])
        self.controller.trd_ctx.place_order.return_value = (0, mock_data)
        self.controller.is_in_continuous_trading_session = MagicMock(return_value=True)
        
        result = self.controller.execute_trade("HK.00700", "SELL", 200, 305.0)
        self.assertTrue(result, "Sell order placement should succeed")
        self.controller.trd_ctx.place_order.assert_called_once()
        
    def test_execute_trade_futu_failure(self):
        # Simulate Futu API returning an error
        self.controller.trd_ctx.place_order.return_value = (1, "API Error")
        self.controller.is_in_continuous_trading_session = MagicMock(return_value=True)
        
        result = self.controller.execute_trade("HK.00700", "BUY", 200, 300.0)
        self.assertFalse(result, "Futu failure should return False")
        self.controller.trd_ctx.place_order.assert_called_once()

if __name__ == '__main__':
    unittest.main()
