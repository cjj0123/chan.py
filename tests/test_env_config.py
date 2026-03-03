"""
单元测试：测试 Config/EnvConfig.py 中的 EnvConfig 类。
"""

import os
import unittest
import tempfile
from Config.EnvConfig import EnvConfig


class TestEnvConfig(unittest.TestCase):

    def setUp(self):
        """在每个测试前创建一个临时配置文件。"""
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        self.temp_config.write("""
trading:
  hk_watchlist_group: "My HK Watchlist"
  min_visual_score: 70
  max_position_ratio: 0.2
  dry_run: true

database:
  path: "test_trading_data.db"

chan:
  bi_strict: true
  trd_strict: true
  bi_fx_check: true
""")
        self.temp_config.close()

    def tearDown(self):
        """在每个测试后删除临时配置文件。"""
        if os.path.exists(self.temp_config.name):
            os.unlink(self.temp_config.name)

    def test_load_existing_config(self):
        """测试从存在的配置文件加载配置。"""
        config = EnvConfig(self.temp_config.name)
        self.assertEqual(config.get("trading.hk_watchlist_group"), "My HK Watchlist")
        self.assertEqual(config.get("trading.min_visual_score"), 70)
        self.assertEqual(config.get("database.path"), "test_trading_data.db")

    def test_get_with_default(self):
        """测试获取不存在的键时返回默认值。"""
        config = EnvConfig(self.temp_config.name)
        self.assertEqual(config.get("non.existent.key", "default_value"), "default_value")

    def test_attribute_access(self):
        """测试通过属性访问顶级配置项。"""
        config = EnvConfig(self.temp_config.name)
        self.assertTrue(hasattr(config, 'trading'))
        self.assertTrue(hasattr(config, 'database'))
        self.assertEqual(config.trading['min_visual_score'], 70)

    def test_load_nonexistent_config(self):
        """测试加载不存在的配置文件应返回空字典。"""
        config = EnvConfig("nonexistent_config.yaml")
        self.assertEqual(config.get("any.key", "default"), "default")


if __name__ == '__main__':
    unittest.main()