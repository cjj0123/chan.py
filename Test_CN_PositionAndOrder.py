import time
import logging
from futu import *

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_cn_simulation():
    logger.info("=== 启动 A 股 Futu 模拟盘接口测试 ===")
    
    # 1. 启动交易上下文 (A股通常是 TrdMarket.CN)
    trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.CN, host='127.0.0.1', port=11111)
    # 在 Futu API v9 中，trd_env 必须在每个请求中传入 (AccInfoQuery, PositionListQuery, PlaceOrder, etc.)
    target_env = TrdEnv.SIMULATE
    
    try:
        # 2. 查询账户资产
        logger.info("--- 1. 查询账户资产 ---")
        ret, data = trd_ctx.accinfo_query(trd_env=target_env)
        if ret == RET_OK:
            logger.info("✅ 资产查询成功:")
            print(data)
        else:
            logger.error(f"❌ 资产查询失败: {data}")

        # 3. 查询持仓
        logger.info("\n--- 2. 查询持仓 ---")
        ret, data = trd_ctx.position_list_query(trd_env=target_env)
        if ret == RET_OK:
            logger.info("✅ 持仓查询成功:")
            print(data)
        else:
            logger.error(f"❌ 持仓查询失败: {data}")

        # 4. 尝试下一笔测试单 (限价单)
        logger.info("\n--- 3. 下单测试 ---")
        test_code = "SH.600000"  # 浦发银行，较低价，适合测试
        test_price = 6.50       # 设一个较低的价格防止轻易成交
        test_qty = 100          # A股必需是100的倍数
        
        logger.info(f"正在尝试下达买入单: {test_qty} 股 {test_code} @ ${test_price} ...")
        
        # 模拟盘通常免密，如果需要解锁可补充 trd_ctx.unlock_trade("密码")
        ret, data = trd_ctx.place_order(
            price=test_price, 
            qty=test_qty, 
            code=test_code, 
            trd_side=TrdSide.BUY, 
            order_type=OrderType.NORMAL,
            trd_env=target_env
        )
        
        if ret == RET_OK:
            order_id = data['order_id'][0]
            logger.info(f"✅ 下单测试提交成功! 订单号: {order_id}")
            
            # 立即撤单，防止污染模拟盘或异常成交
            logger.info(f"正在撤销订单 {order_id} ...")
            time.sleep(2)  # 等待订单在柜台注册
            ret_cancel, data_cancel = trd_ctx.cancel_order(order_id, trd_env=target_env)
            if ret_cancel == RET_OK:
                logger.info("✅ 撤单指令发送成功")
            else:
                logger.warning(f"⚠️ 撤单失败: {data_cancel}")
        else:
            logger.error(f"❌ 下单测试失败: {data}")

    except Exception as e:
         logger.error(f"测试过程中发生异常: {e}")
    finally:
        trd_ctx.close()
        logger.info("=== 测试完毕，接口已安全释放 ===")

if __name__ == '__main__':
    test_cn_simulation()
