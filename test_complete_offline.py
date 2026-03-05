"""
完整离线模式测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks
from Common.CEnum import AUTYPE, KL_TYPE
from Chan import CChan
from ChanConfig import CChanConfig

def test_download_data():
    """测试下载数据到数据库"""
    print("测试下载数据到数据库...")
    
    # 下载测试数据
    test_codes = ["TEST.001", "TEST.002"]
    try:
        download_and_save_all_stocks(test_codes, days=5)
        print("✅ 数据下载成功")
        return True
    except Exception as e:
        print(f"❌ 数据下载失败: {e}")
        return False

def test_offline_scan():
    """测试离线扫描功能"""
    print("\n测试离线扫描功能...")
    
    try:
        # 创建配置
        config = CChanConfig()
        
        # 创建 CChan 对象
        chan = CChan(
            code="TEST.001",
            begin_time="2024-01-01",
            end_time="2024-01-05",
            data_src="custom:SQLiteAPI.SQLiteAPI",
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        # 检查K线数量
        kline_count = len(chan[0]) if len(chan.lv_list) > 0 else 0
        print(f"✅ 成功创建 CChan 对象，包含 {kline_count} 个K线")
        
        if kline_count > 0:
            return True
        else:
            print("❌ K线数量为0")
            return False
            
    except Exception as e:
        print(f"❌ 离线扫描失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=== 完整离线模式测试 ===")
    
    success1 = test_download_data()
    success2 = test_offline_scan()
    
    if success1 and success2:
        print("\n✅ 所有测试通过！离线模式完全正常。")
    else:
        print("\n❌ 测试失败，请检查实现。")