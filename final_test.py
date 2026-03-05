"""
最终完整测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import SQLiteAPI, download_and_save_all_stocks
from Common.CEnum import AUTYPE, KL_TYPE
from Chan import CChan
from ChanConfig import CChanConfig
from Monitoring.FutuMonitor import FutuMonitor

def test_sqlite_api_interface():
    """测试 SQLiteAPI 接口"""
    print("1. 测试 SQLiteAPI 接口...")
    try:
        api = SQLiteAPI("TEST.001", k_type=KL_TYPE.K_DAY, begin_date="2024-01-01", end_date="2024-01-05", autype=AUTYPE.QFQ)
        data = list(api.get_kl_data())
        assert len(data) > 0
        print("✅ SQLiteAPI 接口正常")
        return True
    except Exception as e:
        print(f"❌ SQLiteAPI 接口错误: {e}")
        return False

def test_custom_data_source():
    """测试自定义数据源"""
    print("2. 测试自定义数据源...")
    try:
        chan = CChan(
            code="TEST.001",
            begin_time="2024-01-01",
            end_time="2024-01-05",
            data_src="custom:SQLiteAPI.SQLiteAPI",
            lv_list=[KL_TYPE.K_DAY],
            config=CChanConfig(),
            autype=AUTYPE.QFQ,
        )
        kline_count = len(chan[0]) if len(chan.lv_list) > 0 else 0
        assert kline_count > 0
        print("✅ 自定义数据源正常")
        return True
    except Exception as e:
        print(f"❌ 自定义数据源错误: {e}")
        return False

def test_futu_monitor_init():
    """测试 FutuMonitor 初始化"""
    print("3. 测试 FutuMonitor 初始化...")
    try:
        monitor = FutuMonitor()
        # 不需要连接到实际的富途服务器，只要初始化不报错就行
        print("✅ FutuMonitor 初始化正常")
        return True
    except Exception as e:
        print(f"❌ FutuMonitor 初始化错误: {e}")
        return False

if __name__ == "__main__":
    print("=== 最终完整测试 ===")
    
    success1 = test_sqlite_api_interface()
    success2 = test_custom_data_source()
    success3 = test_futu_monitor_init()
    
    if success1 and success2 and success3:
        print("\n✅ 所有测试通过！系统完全正常。")
    else:
        print("\n❌ 测试失败，请检查实现。")