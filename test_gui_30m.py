"""
测试GUI的30分钟线功能
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE

def test_30m_analysis():
    """测试30分钟线分析"""
    code = "HK.00700"
    begin_time = "2026-02-01"
    end_time = "2026-03-05"
    
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": "1,1p,2,2s,3a,3b",
        "print_warning": False,
        "zs_algo": "normal",
    })
    
    # 使用SQLite数据源进行30分钟线分析
    chan = CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src="custom:SQLiteAPI.SQLiteAPI",
        lv_list=[KL_TYPE.K_30M],
        config=config,
        autype=AUTYPE.QFQ,
    )
    
    print(f"30分钟线分析完成，共 {len(chan[0])} 个K线")
    if len(chan[0]) > 0:
        print(f"最后一条K线时间: {chan[0][-1][-1].time}")
    
    # 检查是否有买卖点
    bsp_list = chan.get_latest_bsp(number=0)
    buy_points = [bsp for bsp in bsp_list if bsp.is_buy]
    print(f"发现 {len(buy_points)} 个买点")

if __name__ == "__main__":
    test_30m_analysis()