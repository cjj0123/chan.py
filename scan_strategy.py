# 文件位置: /workspaces/chan.py/scan_strategy.py
import sys
import os
import time
from datetime import datetime

# 1. 确保根目录在 Python 路径中 (防止 ModuleNotFoundError)
sys.path.append(os.path.abspath("."))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
# 导入您自定义的第二定理策略
from CustomBuySellPoint.StrategySecondTheorem import CStrategySecondTheorem

def run_scanner():
    print(f"🚀 开始执行选股扫描 - {datetime.now()}")
    
    # -----------------------------------------------------------
    # 【配置区域】
    # -----------------------------------------------------------
    # A. 定义股票池 (示例代码，实战可接入板块数据接口)
    # 注意：Futu 接口有频率限制，模拟盘建议先用少量股票测试
    stock_pool = [
        "HK.00700", # 腾讯
        "HK.03690", # 美团
        "HK.09988", # 阿里
        "HK.01810", # 小米
        "HK.00981", # 中芯国际

    ]
    
    # B. 策略配置
    config = CChanConfig({
        "bi_strict": True,          # 严格笔
        "zs_combine": True,         # 中枢合并
        "cbsp_strategy": CStrategySecondTheorem, # 挂载第二定理策略
        "strategy_para": {
            "strict_open": True,    # 严格开仓
        }
    })

    # C. 扫描级别 (30分钟抓趋势)
    scan_lv = KL_TYPE.K_30M
    # -----------------------------------------------------------

    valid_stocks = []

    for code in stock_pool:
        try:
            print(f"正在分析: {code} ...", end="", flush=True)
            
            # 初始化计算 (获取最近数据)
            # 这里的 lv_list 必须包含 scan_lv
            chan = CChan(
                code=code,
                begin_time=None,        # None 表示取最近数据
                end_time=None,
                #data_src=DATA_SRC.FUTU, # 必须确保富途 OpenD 已开启
                data_src=DATA_SRC.AKSHARE,
                lv_list=[scan_lv],      
                config=config,
                autype=AUTYPE.QFQ
            )

            # 核心检查逻辑
            # 1. 获取该级别数据对象
            kl_data = chan[scan_lv]
            
            # 2. 检查是否有买卖点列表
            if not hasattr(kl_data, 'bs_point_lst') or len(kl_data.bs_point_lst) == 0:
                print(" [无信号]")
                continue

            # 3. 获取最后一个买卖点
            last_bsp = kl_data.bs_point_lst[-1]
            last_klu = kl_data[-1][-1] # 最后一根K线

            # 4. 判断是否为目标信号 (3类买点)
            # 注意：这里我们利用 bsp.type2str() 判断是否包含 "3"
            # 并且必须是买点 (is_buy=True)
            if last_bsp.is_buy and "3" in last_bsp.type2str():
                
                # 5. 时效性检查：必须是最近 3 根K线内触发的才算数
                # 否则可能是很久以前的买点，现在已经过气了
                dist = len(kl_data) - 1 - last_bsp.klu.idx
                
                if dist <= 3:
                    print(f" 🔥【发现猎物】 {last_bsp.type2str()} @ 价格 {last_bsp.price}")
                    valid_stocks.append({
                        "code": code,
                        "type": last_bsp.type2str(),
                        "price": last_bsp.price,
                        "time": last_klu.time
                    })
                else:
                    print(f" [信号太久远: {dist}根K线前]")
            else:
                print(" [不符合策略]")

        except Exception as e:
            print(f" ❌ 出错: {e}")
            # 如果是 Futu 连接错误，可能需要中断
            if "Connection" in str(e):
                break

    # -----------------------------------------------------------
    # 【结果汇报】
    # -----------------------------------------------------------
    print("\n" + "="*30)
    print(f"📊 扫描结束，共发现 {len(valid_stocks)} 只标的")
    print("="*30)
    for stock in valid_stocks:
        print(f"🎯 代码: {stock['code']} | 类型: {stock['type']} | 价格: {stock['price']}")
    
    return valid_stocks

if __name__ == "__main__":
    run_scanner()