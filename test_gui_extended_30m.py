"""
测试GUI中扩展的30分钟扫描功能
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from App.ashare_bsp_scanner_gui import OfflineScanThread
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE
import pandas as pd

def test_gui_extended_30m_scan():
    """测试GUI中扩展的30分钟扫描"""
    # 创建测试股票列表
    stock_list = pd.DataFrame({
        '代码': ['HK.00700'],
        '名称': ['腾讯控股'],
        '最新价': [0.0],
        '涨跌幅': [0.0]
    })
    
    # 创建配置
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
    
    # 创建30分钟级别扫描线程，使用365天数据
    scan_thread = OfflineScanThread(
        stock_list=stock_list,
        config=config,
        days=365,
        kl_type=KL_TYPE.K_30M
    )
    
    # 连接信号
    def on_progress(current, total, stock_info):
        print(f"进度: {current}/{total} - {stock_info}")
    
    def on_found_signal(data):
        print(f"发现买点: {data['code']} {data['name']} - {data['bsp_type']}")
    
    def on_finished(success, fail):
        print(f"扫描完成: 成功{success}, 失败{fail}")
    
    def on_log(msg):
        print(f"日志: {msg}")
    
    scan_thread.progress.connect(on_progress)
    scan_thread.found_signal.connect(on_found_signal)
    scan_thread.finished.connect(on_finished)
    scan_thread.log_signal.connect(on_log)
    
    # 运行扫描
    print("开始扩展30分钟级别扫描（365天数据）...")
    scan_thread.run()
    print("扫描结束")

if __name__ == "__main__":
    test_gui_extended_30m_scan()