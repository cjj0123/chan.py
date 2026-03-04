"""
单元测试：测试 Trade/db_util.py 中的 CChanDB 类。
"""

import os
import unittest
import tempfile
from Trade.db_util import CChanDB


class TestCChanDB(unittest.TestCase):

    def setUp(self):
        """在每个测试前创建一个临时数据库。"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        # 由于 CChanDB 从配置读取路径，这里我们直接修改实例的 db_path
        self.db = CChanDB()
        self.db.db_path = self.temp_db.name
        self.db._init_database()  # 初始化临时数据库的表结构

    def tearDown(self):
        """在每个测试后删除临时数据库文件。"""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    def test_save_and_get_signal(self):
        """测试保存和获取信号。"""
        signal_id = self.db.save_signal("HK.00700", "buy", 85.5, "/path/to/chart.png")
        self.assertIsInstance(signal_id, int)
        self.assertGreater(signal_id, 0)

        signals = self.db.get_active_signals("HK.00700")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['code'], "HK.00700")
        self.assertEqual(signals[0]['signal_type'], "buy")
        self.assertAlmostEqual(signals[0]['score'], 85.5)

    def test_update_signal_status(self):
        """测试更新信号状态。"""
        signal_id = self.db.save_signal("HK.00700", "sell", 70.0, "/path/to/chart2.png")
        signals_before = self.db.get_active_signals("HK.00700")
        self.assertEqual(len(signals_before), 1)

        self.db.update_signal_status(signal_id, "executed")
        signals_after = self.db.get_active_signals("HK.00700")
        self.assertEqual(len(signals_after), 0)

    def test_save_and_get_order(self):
        """测试保存和获取订单。"""
        order_id = self.db.save_order("HK.00700", "BUY", 100, 350.5)
        self.assertIsInstance(order_id, int)
        self.assertGreater(order_id, 0)

        pending_orders = self.db.get_pending_orders("HK.00700")
        self.assertEqual(len(pending_orders), 1)
        self.assertEqual(pending_orders[0]['action'], "BUY")
        self.assertEqual(pending_orders[0]['quantity'], 100)
        self.assertAlmostEqual(pending_orders[0]['price'], 350.5)

    def test_update_order_status(self):
        """测试更新订单状态。"""
        order_id = self.db.save_order("HK.00700", "SELL", 50, 400.0)
        orders_before = self.db.get_pending_orders("HK.00700")
        self.assertEqual(len(orders_before), 1)

        self.db.update_order_status(order_id, "filled")
        orders_after = self.db.get_pending_orders("HK.00700")
        self.assertEqual(len(orders_after), 0)

    def test_save_and_get_position(self):
        """测试保存和获取持仓。"""
        self.db.save_position("HK.00700", 200, 360.25)

        position = self.db.get_position("HK.00700")
        self.assertIsNotNone(position)
        self.assertEqual(position['quantity'], 200)
        self.assertAlmostEqual(position['avg_cost'], 360.25)

        # 测试更新持仓
        self.db.save_position("HK.00700", 150, 365.0)
        updated_position = self.db.get_position("HK.00700")
        self.assertEqual(updated_position['quantity'], 150)
        self.assertAlmostEqual(updated_position['avg_cost'], 365.0)

    def test_get_nonexistent_position(self):
        """测试获取不存在的持仓应返回 None。"""
        position = self.db.get_position("HK.NONEXISTENT")
        self.assertIsNone(position)

    def test_execute_query_returns_dataframe(self):
        """测试 execute_query 方法返回 pandas DataFrame。"""
        df = self.db.execute_query("SELECT * FROM signals")
        self.assertTrue(hasattr(df, 'empty'))  # 检查是否是 DataFrame
        self.assertEqual(len(df), 0)  # 初始应为空


if __name__ == '__main__':
    unittest.main()