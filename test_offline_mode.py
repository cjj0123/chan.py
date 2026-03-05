"""
测试离线模式功能
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import SQLiteAPI
from Common.CEnum import AUTYPE, KL_TYPE, DATA_SRC
from Chan import CChan
from ChanConfig import CChanConfig

def test_sqlite_api():
    """测试 SQLiteAPI 是否能正确返回 CKLine_Unit"""
    print("测试 SQLiteAPI...")
    
    # 创建 SQLiteAPI 实例，使用数据库中存在的代码
    api = SQLiteAPI("SZ.300772", k_type=KL_TYPE.K_DAY, begin_date="2025-01-01", end_date="2026-12-31", autype=AUTYPE.QFQ)
    
    # 获取数据
    kl_data = list(api.get_kl_data())
    print(f"获取到 {len(kl_data)} 根K线")
    
    if kl_data:
        print(f"第一根K线时间: {kl_data[0].time}")
        print(f"第一根K线开盘价: {kl_data[0].open}")
        print(f"第一根K线收盘价: {kl_data[0].close}")
    
    return len(kl_data) > 0

def test_chan_with_sqlite():
    """测试使用 SQLite 数据创建 CChan 对象"""
    print("\n测试 CChan 与 SQLiteAPI 集成...")
    
    try:
        chan_config = CChanConfig()
        # 使用字符串方式指定 custom 数据源
        chan = CChan(
            code="SZ.300772",
            begin_time="2025-01-01",
            end_time="2026-12-31",
            data_src="custom:SQLiteAPI.SQLiteAPI",  # 正确的方式
            lv_list=[KL_TYPE.K_DAY],
            config=chan_config,
            autype=AUTYPE.QFQ,
        )
        
        # 正确获取K线数量
        kline_count = len(chan[0]) if len(chan.lv_list) > 0 else 0
        print(f"成功创建 CChan 对象，包含 {kline_count} 个K线")
        
        return True
    except Exception as e:
        print(f"创建 CChan 失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=== 离线模式测试 ===")
    
    success1 = test_sqlite_api()
    success2 = test_chan_with_sqlite()
    
    if success1 and success2:
        print("\n✅ 所有测试通过！离线模式功能正常。")
    else:
        print("\n❌ 测试失败，请检查实现。")