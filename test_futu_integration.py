#!/usr/bin/env python3
"""
测试富途集成功能的简单脚本
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Monitoring.FutuMonitor import FutuMonitor

def test_futu_connection():
    """测试富途连接和自选股获取"""
    try:
        print("正在测试富途API连接...")
        monitor = FutuMonitor()
        
        # 获取自选股分组
        print("获取自选股分组列表...")
        watchlists = monitor.get_watchlists()
        print(f"找到 {len(watchlists)} 个自选股分组: {watchlists}")
        
        if watchlists:
            # 获取第一个分组的股票
            print(f"获取分组 '{watchlists[0]}' 的股票列表...")
            ret, data = monitor.quote_ctx.get_user_security(group_name=watchlists[0])
            if ret == 0:  # RET_OK
                print(f"成功获取 {len(data)} 只股票")
                print(f"数据类型: {type(data)}")
                # 检查data是否是DataFrame
                if hasattr(data, 'iloc'):
                    # DataFrame格式
                    for i in range(min(5, len(data))):
                        print(f"  - {data.iloc[i]['code']}: {data.iloc[i]['name']}")
                else:
                    # 字典列表格式
                    for stock in data[:5]:  # 只显示前5只
                        print(f"  - {stock['code']}: {stock['name']}")
            else:
                print(f"获取股票失败: {data}")
        else:
            print("没有找到自选股分组")
            
        monitor.quote_ctx.close()
        print("测试完成！")
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        return False

if __name__ == "__main__":
    test_futu_connection()