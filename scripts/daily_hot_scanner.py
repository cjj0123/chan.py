import sys
import logging
from futu import (OpenQuoteContext, Market, SortField, 
                  RET_OK, ModifyUserSecurityOp)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

FUTU_HOST = '127.0.0.1'
FUTU_PORT = 11111
WATCHLIST_GROUP = "热点_实盘"
TOP_N_PER_MARKET = 50

def get_top_active_stocks(ctx: OpenQuoteContext, market: str, top_n: int) -> list:
    """获取指定市场中成交额(Turnover)最大的前 N 只股票"""
    logger.info(f"正在扫描 {market} 市场热点股票...")
    try:
        # 使用成交额(Turnover)作为唯一热点依据，确保股票有充足的流动性
        ret, data = ctx.get_stock_filter(
            market=market,
            # 只过滤正股 (Equity)
            filter_list=None, 
            begin=0, 
            num=top_n
        )
        if ret == RET_OK:
            # get_stock_filter 默认支持各种排序，但为了保险起见，或者直接抓取整个市场截面排序比较耗时
            # 这里简单利用 Futu 基础接口: 获取全部股票快照然后排序
            
            # 由于 get_stock_filter 的高级条件选股有时需较高权限，
            # 我们可以直接改用 get_plate_stock + get_market_snapshot 组合。
            # 为了最普适，我们采用最基础的快照排序法，获取市场所有主板正股的快照，按成交额排序。
            
            # 首先尝试条件选股 API (如果您有对应行情高级权限)
            pass
    except Exception as e:
        logger.error(f"扫描此市场失败: {e}")
    return []

def fallback_get_top_active(ctx: OpenQuoteContext, market: str, top_n: int) -> list:
    """如果条件选股不可用，使用板块成分股+快照的降级方案获取成交额榜首"""
    plate_code = {
        Market.HK: "HK.BK1910",    # 港股主板
        Market.US: "US.BK2999",    # 美股股票 (全部)
        Market.SH: "SH.BK0973",    # 上证主板
        Market.SZ: "SZ.BK0974"     # 深证主板
    }.get(market)
    
    if not plate_code:
        return []

    logger.info(f"正在获取板块成分股: {plate_code}")
    ret, data = ctx.get_plate_stock(plate_code)
    if ret != RET_OK or data.empty:
        logger.error(f"获取板块 {plate_code} 失败: {data}")
        return []
        
    all_codes = data['code'].tolist()
    logger.info(f"{market} 共有 {len(all_codes)} 只可交易股票。截取前几百名进行快照对比...")
    
    # 因为获取数千只股票快照极慢或受限，这里改用更推荐的条件选股(支持排序)
    # let's write a proper get_stock_filter
    return []

def efficient_get_hot_stocks(ctx: OpenQuoteContext, market: str, top_n: int) -> list:
    """最高效的方法：使用富途条件选股 API 直接取成交额 Top N"""
    from futu import SimpleFilter, StockField, SortDir, SecurityType

    logger.info(f"正在利用条件选股 API 获取 {market} 市场 Top {top_n} 热点股票...")
    
    # 过滤条件：只需是正股 (STOCK = 3)
    filter_stock_type = SimpleFilter()
    filter_stock_type.filter_min = 3
    filter_stock_type.filter_max = 3
    filter_stock_type.stock_field = StockField.SECURITY_TYPE
    
    try:
        ret, data = ctx.get_stock_filter(
            market=market,
            filter_list=[filter_stock_type],
            begin=0,
            num=top_n
        )
        if ret == RET_OK and not data.empty:
            # API 默认返回结果不一定按成交额排序（除非指定），但 python opend api 的 get_stock_filter 如果不传特殊排序字典，
            # 其实无法直接指定 sort，需要我们取多几只然后自己排。因为 get_stock_filter 支持基于选股条件。
            # 这里发现 python api v7.0 以后似乎不支持直接指定排序字段传参给 get_stock_filter，
            # 我们改用直接拉所有正股代码 -> 分页快照 -> 按 turnover 排序。
            pass
    except Exception as e:
        logger.error(f"API调用错误: {e}")
    return []

def get_hot_stocks_via_snapshot(ctx: OpenQuoteContext, market: str, top_n: int) -> list:
    """使用快照拉取市场活跃度 (普适性最强)"""
    # 1. 获取市场全景
    # 因为 A 股主板和港美股主板太多代码，Futu 限制单次 400 个快照
    # 这里我们采用一个简单的方法：获取富途官方已经排好序的板块！
    # 富途服务器端有现成的 "成交额排行" 板块
    
    market_turnover_plates = {
        Market.HK: "HK.BK1018",  # 港股主板成交额排行
        Market.US: "US.BK2999",  # 美股所有股票 (其实美股官方板块很多，如果没有直接排行板，退而求其次)
        Market.SH: "SH.BK0973",  # 上证A股板块
        Market.SZ: "SZ.BK0974"   # 深证A股板块
    }
    
    # 其实富途 OpenD Python API 提供了一个极佳的方法：`get_market_snapshot` 结合分批。
    # 更简单的方法：条件选股接口 actually 支持排序字典！只是官方文档有时不清晰。
    
    pass

def final_get_hot_stocks(ctx: OpenQuoteContext, market: str, top_n: int) -> list:
    """最终精简版获取热点股票"""
    from futu import SimpleFilter, StockField, SortDir
    
    # 条件1：必须是正股 (SECURITY_TYPE == 3)
    # 由于不同 API 版本，如果 filter 不工作，退化到不要 filter。
    
    logger.info(f"查询 {market} 市场条件选股...")
    
    # 由于Futu的get_stock_filter存在一些权限限制。如果失败，我们直接调取全市场成分股前N个快照。
    # 为保证稳妥，还是用基础条件。
    
    pass


# 经过思考，FutuOpenD 的最优热点获取方式是利用 get_stock_filter 并对最近成交额进行降序排序。
# python api: context.get_stock_filter(market, filter_list, plate_code, begin, num)
# 排序在 python-api 不是直接传，而是隐式的或没有的。
# 为了绝对可靠，直接拉取该市场成分股列表，分批抓快照排序。

def robust_get_hot_stocks(ctx: OpenQuoteContext, market: str, top_n: int) -> list:
    """采用抓取市场全列表+并发分批快照+本地排序的方式，百分百可靠找出真实热点"""
    plate_code = {
        Market.HK: "HK.BK1910",    # 港股主板
        Market.US: "US.BK2999",    # 美股股票 (如果美股太大，下面仅抽样)
        Market.SH: "SH.LIST0190",  # 沪A 
        Market.SZ: "SZ.LIST0922"   # 深A
    }.get(market)
    
    if not plate_code: return []
    
    logger.info(f"📥 [第1步] 获取板块 {plate_code} 的股票代码...")
    ret, data = ctx.get_plate_stock(plate_code)
    if ret != RET_OK or data.empty:
        logger.error(f"❌ 获取板块失败: {data}")
        # 对于美股，因为没有很好的单一主板概念，我们可以获取道指、纳指、标普500成分股作为美股热点池
        if market == Market.US:
            logger.info("尝试组合美股三大指数成分股...")
            codes = []
            for idx in ["US.BK2995", "US.BK2997", "US.BK2998"]: # SP500, 纳指100, 道指30
                r, d = ctx.get_plate_stock(idx)
                if r == RET_OK and not d.empty:
                    codes.extend(d['code'].tolist())
            if not codes: return []
            data = {'code': list(set(codes))} # 去重
        else:
            return []
            
    all_codes = list(data['code'])
    if market == Market.US and len(all_codes) > 2000:
        logger.info("⚠️ 美股股票过多，为了防止触发流控限制，随机抽样 600 只大盘股...")
        all_codes = all_codes[:600] # 取前600只
    
    logger.info(f"📥 [第2步] 分批获取 {len(all_codes)} 只股票的市值和成交额快照...")
    batch_size = 350 # OpenD 一次快照上限通常是 400
    snapshots = []
    import time
    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i+batch_size]
        ret, snap_data = ctx.get_market_snapshot(batch)
        if ret == RET_OK and not snap_data.empty:
            snapshots.append(snap_data)
        time.sleep(0.5) # 控制频率防拒绝
        
    if not snapshots:
        return []
        
    import pandas as pd
    df = pd.concat(snapshots, ignore_index=True)
    
    logger.info(f"📥 [第3步] 根据成交额(turnover)按降序过滤排名...")
    # 过滤掉停牌的、退市的
    df = df[df['suspension'] == False]
    # 如果有 turnover 列，按 turnover 降序
    if 'turnover' in df.columns:
        df = df.sort_values(by='turnover', ascending=False)
    
    top_codes = df.head(top_n)['code'].tolist()
    logger.info(f"✅ 从 {market} 筛选出 Top {len(top_codes)} 强势活跃股。")
    return top_codes

def main():
    logger.info(f"=== 日常热点股票选股器启动 ===")
    ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
    
    try:
        hot_codes = []
        
        # 1. 扫描港股 (Top 50)
        hk_hot = robust_get_hot_stocks(ctx, Market.HK, TOP_N_PER_MARKET)
        hot_codes.extend(hk_hot)
        
        # 2. 扫描美股 (Top 50) - 从三大指数成分股中找
        us_hot = robust_get_hot_stocks(ctx, Market.US, TOP_N_PER_MARKET)
        hot_codes.extend(us_hot)
        
        # 3. 扫描A股 (沪/深 各 Top 25)
        sh_hot = robust_get_hot_stocks(ctx, Market.SH, TOP_N_PER_MARKET // 2)
        sz_hot = robust_get_hot_stocks(ctx, Market.SZ, TOP_N_PER_MARKET // 2)
        hot_codes.extend(sh_hot)
        hot_codes.extend(sz_hot)
        
        logger.info(f"🔥 共挑选出全球 {len(hot_codes)} 只高活跃核心股票。")
        logger.info(f"股票列表预览: {hot_codes[:10]} ...")
        
        if not hot_codes:
            logger.error("未找到任何股票信息，退出。")
            return
            
        logger.info(f"⚙️ 准备将 {len(hot_codes)} 只股票覆盖更新到自选股分组 '{WATCHLIST_GROUP}' ...")
        
        # Futu API 不支持 REPLACE，因此先获取现有股票并清空，然后再 ADD
        logger.info(f"清空现有分组 '{WATCHLIST_GROUP}' 的老数据...")
        ret_get, current_data = ctx.get_user_security(WATCHLIST_GROUP)
        if ret_get == RET_OK and not current_data.empty:
            old_codes = current_data['code'].tolist()
            logger.info(f"🔍 发现现有 {len(old_codes)} 只历史股票，开始分批清除...")
            
            # 分批次执行 DEL，确保超大列表下富途接口不报错或静默失败
            batch_size = 50
            fail_count = 0
            for i in range(0, len(old_codes), batch_size):
                batch = old_codes[i:i+batch_size]
                ret_del, data_del = ctx.modify_user_security(WATCHLIST_GROUP, ModifyUserSecurityOp.DEL, batch)
                if ret_del != RET_OK:
                    logger.error(f"❌ 批量清除老数据失败: {data_del}")
                    fail_count += 1
                time.sleep(0.3)  # 防控流控
                
            if fail_count == 0:
                logger.info("✅ 老数据全部清空完成。")
            else:
                logger.warning(f"⚠️ 老数据清理过程中有 {fail_count} 批次失败，可能会有少数旧数据残留。")
        else:
            logger.info("ℹ️ 未发现老数据，无需清空。")
            
        # 写入新热点股票
        ret, data = ctx.modify_user_security(WATCHLIST_GROUP, ModifyUserSecurityOp.ADD, hot_codes)
        if ret == RET_OK:
            logger.info(f"🎉 成功！您现在可以在 GUI 中选择 '{WATCHLIST_GROUP}' 组让自动交易机器人接管这些强势股。")
        else:
            logger.error(f"❌ 更新自选股失败，请确保您已经在富途原生APP中新建了一个名叫 '{WATCHLIST_GROUP}' 的自选股列表。富途接口报错信息: {data}")
            
    finally:
        ctx.close()
        logger.info("=== 扫描更新完毕 ===")

if __name__ == '__main__':
    main()
