#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Trade.RiskManager import RiskManager

class MockChanKLU:
    def __init__(self, high, low, close):
        self.high = high
        self.low = low
        self.close = close

class MockChanList:
    def __init__(self, klus):
        self.klus = klus
    def klu_iter(self):
        return iter(self.klus)
    def __len__(self):
        return len(self.klus)

class TestAutoTrading(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(db_path=":memory:")
        self.rm.max_total_positions = 5
        self.rm.max_position_ratio = 0.2
        self.rm.min_visual_score = 70
        self.rm.circuit_breaker_enabled = False
        
    def test_risk_manager_max_positions(self):
        self.rm.total_positions = 5
        shares = self.rm.calculate_position_size("HK.00700", 100000, 100, 80)
        self.assertEqual(shares, 0, "Should return 0 when max positions reached")
        
        self.rm.total_positions = 4
        shares = self.rm.calculate_position_size("HK.00700", 100000, 100, 80)
        self.assertGreater(shares, 0, "Should return >0 when under max positions")

    def test_risk_manager_atr_fallback_total_assets(self):
        self.rm.total_positions = 0
        total_assets = 100000
        available_cash = 80000
        current_price = 100
        score = 100 # score 1.0
        
        # 100000 * 0.2 = 20000 target investment
        # 20000 / 100 = 200 shares
        shares = self.rm.calculate_position_size(
            "HK.00700", 
            available_funds=available_cash, 
            total_assets=total_assets,
            current_price=current_price, 
            signal_score=score,
            atr=None
        )
        self.assertEqual(shares, 200, "Should use exactly 20% of total assets for fallback")

    def test_risk_manager_cash_limit(self):
        self.rm.total_positions = 0
        total_assets = 100000
        available_cash = 10000 # Only 10k cash
        current_price = 100
        score = 100 # score 1.0
        
        # 100000 * 0.2 = 20000 target investment
        # But only 10000 cash -> 10000 / 100 = 100 shares limit
        shares = self.rm.calculate_position_size(
            "HK.00700", 
            available_funds=available_cash, 
            total_assets=total_assets,
            current_price=current_price, 
            signal_score=score,
            atr=None
        )
        self.assertEqual(shares, 100, "Should be capped by available cash")

    def test_controller_atr_calculation(self):
        from App.HKTradingController import HKTradingController
        
        # We just need to test the ATR method directly, so we patch init to avoid starting threads and connections
        with patch.object(HKTradingController, '__init__', return_value=None):
            controller = HKTradingController()
            
            klus = [
                MockChanKLU(105, 95, 100),
                MockChanKLU(106, 96, 102),
                MockChanKLU(104, 94, 98),
                MockChanKLU(108, 98, 105)
            ] * 4 # Need 15 items for period=14
            
            atr = controller._calculate_atr(klus, period=14)
            self.assertGreater(atr, 0.0, "ATR should be successfully calculated")

if __name__ == '__main__':
    unittest.main()
