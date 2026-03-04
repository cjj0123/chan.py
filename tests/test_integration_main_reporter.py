"""
集成测试：验证主程序 (futu_hk_visual_trading_fixed.py) 与监控报告模块 (reporter.py) 的集成。
"""

import os
import unittest
import tempfile
from unittest.mock import patch, MagicMock
from Trade.db_util import CChanDB
from Monitoring.metrics import CMetricsCalculator


class TestIntegrationMainReporter(unittest.TestCase):

    def setUp(self):
        """设置临时数据库和模拟数据。"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        
        # 初始化数据库并填充模拟交易数据
        db = CChanDB()
        db.db_path = self.temp_db.name
        db._init_database()
        
        # 模拟一些交易记录
        db.save_order("HK.00700", "BUY", 100, 350.0)
        db.update_order_status(1, "filled")
        db.save_order("HK.00700", "SELL", 100, 360.0)
        db.update_order_status(2, "filled")

    def tearDown(self):
        """清理临时数据库文件。"""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    @patch('Monitoring.reporter.CReporter._generate_html_report')
    @patch('Monitoring.reporter.CReporter._send_email')
    def test_main_program_triggers_report_generation(self, mock_send_email, mock_generate_html):
        """
        测试当主程序完成一轮扫描交易后，能正确触发报告生成。
        此测试通过直接调用 CMetricsCalculator 和模拟 CReporter 来验证数据流。
        """
        # 模拟 CReporter 的行为
        mock_generate_html.return_value = "<html>Mock Report</html>"
        mock_send_email.return_value = True

        # 1. 主程序逻辑会调用 CMetricsCalculator
        calculator = CMetricsCalculator(self.temp_db.name)
        metrics = calculator.get_all_metrics()

        # 2. 验证指标计算是否成功
        self.assertGreater(metrics['total_pnl'], 0)
        self.assertGreaterEqual(metrics['win_rate'], 0)

        # 3. 模拟 CReporter 被调用
        from Monitoring.reporter import CReporter
        reporter = CReporter(db_path=self.temp_db.name)
        success = reporter.generate_and_send_report(recipients=['test@example.com'])

        # 4. 验证报告生成和发送方法被调用
        mock_generate_html.assert_called_once()
        mock_send_email.assert_called_once()
        self.assertTrue(success)


if __name__ == '__main__':
    unittest.main()