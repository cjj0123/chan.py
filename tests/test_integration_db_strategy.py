"""
集成测试：验证 HkVisualStrategy 与 CChanDB 的集成。
"""

import os
import unittest
import tempfile
from unittest.mock import Mock, patch
from Trade.db_util import CChanDB
# 假设策略类在 CustomBuySellPoint/HkVisualStrategy.py 中
# from CustomBuySellPoint.HkVisualStrategy import HkVisualStrategy


class TestIntegrationDBStrategy(unittest.TestCase):

    def setUp(self):
        """设置临时数据库。"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()

    def tearDown(self):
        """清理临时数据库文件。"""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    def test_strategy_saves_signal_to_db(self):
        """
        测试策略在生成信号后，能正确调用 db_util 保存到数据库。
        由于 HkVisualStrategy 尚未实现，此测试使用模拟对象来验证集成逻辑。
        """
        # 创建数据库实例
        db = CChanDB()
        db.db_path = self.temp_db.name
        db._init_database()

        # 模拟一个信号
        mock_signal = {
            'code': 'HK.00700',
            'signal_type': 'buy',
            'score': 85.5,
            'chart_path': '/fake/path/chart.png'
        }

        # 直接调用 db 的方法来模拟策略的行为
        signal_id = db.save_signal(
            code=mock_signal['code'],
            signal_type=mock_signal['signal_type'],
            score=mock_signal['score'],
            chart_path=mock_signal['chart_path']
        )

        # 验证信号已保存
        signals = db.get_active_signals('HK.00700')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['code'], 'HK.00700')
        self.assertEqual(signals[0]['signal_type'], 'buy')
        self.assertAlmostEqual(signals[0]['score'], 85.5)

        # 验证返回的 signal_id 是有效的
        self.assertIsInstance(signal_id, int)
        self.assertGreater(signal_id, 0)


if __name__ == '__main__':
    unittest.main()