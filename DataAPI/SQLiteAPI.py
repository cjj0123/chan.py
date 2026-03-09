"""
DataAPI for SQLite
"""
import pandas as pd
import sqlite3
from datetime import datetime
from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CommonStockAPI import CCommonStockApi
from Trade.db_util import CChanDB


def convert_stock_code_for_akshare(code):
    """
    Convert stock code format from Futu/OpenD to AKShare format
    
    Args:
        code: Stock code in Futu format (e.g., "HK.02649", "SZ.300772", "SH.600000")
    
    Returns:
        str: Stock code in AKShare format (e.g., "hk.02649", "000001")
    """
    if code.startswith("HK."):
        # 港股: HK.02649 -> hk.02649
        return "hk." + code.split(".")[1]
    elif code.startswith("SZ.") or code.startswith("SH."):
        # A股: SZ.300772 -> 300772, SH.600000 -> 600000
        return code.split(".")[1]
    elif code.startswith("US."):
        # 美股: US.AAPL -> us.AAPL
        return "us." + code.split(".")[1].upper()
    else:
        # 如果已经是纯数字格式，直接返回
        return code


def create_item_dict_from_db(row, autype):
    """从数据库行创建 item dict"""
    item = {}
    
    # 处理时间
    date_val = row['date']
    if isinstance(date_val, str):
        # 尝试不同的日期格式
        if ' ' in date_val and ':' in date_val:
            # 包含时间的格式，如 "2026-03-05 10:00:00"
            try:
                dt = datetime.strptime(date_val, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # 如果秒数不是00，可能需要其他格式
                try:
                    dt = datetime.strptime(date_val, "%Y-%m-%d %H:%M")
                except ValueError:
                    # 回退到只解析日期部分
                    date_part = date_val.split(' ')[0]
                    dt = datetime.strptime(date_part, "%Y-%m-%d")
        else:
            # 只有日期的格式，如 "2026-03-05"
            dt = datetime.strptime(date_val, "%Y-%m-%d")
    else:
        dt = date_val
    
    # 检查是否是分钟级别数据但只有日期信息
    # 如果是这种情况，我们需要确保时间戳是唯一的
    # 从调用上下文获取k_type信息比较困难，所以我们在SQLiteAPI.get_kl_data中处理
    
    item[DATA_FIELD.FIELD_TIME] = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
    
    # 提取价格
    o = str2float(row['open'])
    h = str2float(row['high'])
    l = str2float(row['low'])
    c = str2float(row['close'])
    
    # --- 核心修正逻辑：处理 0.0 价格 ---
    # 首先，确保所有价格至少为一个极小的正数，以防止后续计算出错
    EPSILON = 1e-6
    o = max(o, EPSILON)
    h = max(h, EPSILON)
    l = max(l, EPSILON)
    c = max(c, EPSILON)
    
    # 然后，确保价格之间的逻辑关系：low <= open/close <= high
    low_val = min(o, h, l, c)
    high_val = max(o, h, l, c)
    o = max(min(o, high_val), low_val)
    c = max(min(c, high_val), low_val)
    h = high_val
    l = low_val
    # --------------------------------

    item[DATA_FIELD.FIELD_OPEN] = o
    item[DATA_FIELD.FIELD_HIGH] = h
    item[DATA_FIELD.FIELD_LOW] = l
    item[DATA_FIELD.FIELD_CLOSE] = c
    item[DATA_FIELD.FIELD_VOLUME] = str2float(row['volume'])
    item[DATA_FIELD.FIELD_TURNOVER] = str2float(row.get('turnover', 0))
    item[DATA_FIELD.FIELD_TURNRATE] = str2float(row.get('turnrate', 0))

    return item


class SQLiteAPI(CCommonStockApi):
    """
    SQLite data API
    """

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        self.db = CChanDB()
        super(SQLiteAPI, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        """
        get kline data from sqlite
        """
        # Map KL_TYPE to table names
        table_map = {
            KL_TYPE.K_DAY: "kline_day",
            KL_TYPE.K_30M: "kline_30m",
            KL_TYPE.K_5M: "kline_5m",
            KL_TYPE.K_1M: "kline_1m",
        }
        
        if self.k_type not in table_map:
            raise ValueError(f"KLine type {self.k_type} is not supported for SQLiteAPI")
            
        table_name = table_map[self.k_type]
        # 使用 ORDER BY date 保证时间先后顺序 (主键已保证去重)
        sql = f"SELECT * FROM {table_name} WHERE code = '{self.code}'"
        if self.begin_date:
            sql += f" AND date >= '{self.begin_date}'"
        if self.end_date:
            sql += f" AND date <= '{self.end_date}'"
        sql += " ORDER BY date"
            
        df = self.db.execute_query(sql)
        if not df.empty:
            # 遍历生成 K 线单元
            prev_time = None
            minute_counter = 0  # 用于为分钟级别数据生成唯一时间戳
            
            # 判断是否是分钟级别
            is_minute_level = self.k_type in [KL_TYPE.K_1M, KL_TYPE.K_5M, KL_TYPE.K_15M, KL_TYPE.K_30M, KL_TYPE.K_60M]
            
            for _, row in df.iterrows():
                klu = CKLine_Unit(create_item_dict_from_db(row, self.autype))
                
                # 对于分钟级别数据，如果时间戳只有日期部分（小时和分钟都是0），则需要生成合理的时间戳
                if is_minute_level and klu.time.hour == 0 and klu.time.minute == 0:
                    # 检查原始日期字符串是否包含时间信息
                    date_str = row['date']
                    if isinstance(date_str, str) and (' ' in date_str and ':' in date_str):
                        # 如果原始数据包含时间信息，保持原样
                        pass
                    else:
                        # 如果原始数据只有日期，为分钟级别数据生成递增的时间戳
                        # 从9:30开始（美股交易时间）
                        hour = 9 + (minute_counter // 60)
                        minute = 30 + (minute_counter % 60)
                        if minute >= 60:
                            minute -= 60
                            hour += 1
                        # 美股交易时间通常是9:30-16:00，所以限制在合理范围内
                        if hour > 16:
                            hour = 9
                            minute = 30
                            minute_counter = 0
                        klu.time = CTime(klu.time.year, klu.time.month, klu.time.day, hour, minute)
                        minute_counter += 5  # 假设5分钟间隔
                
                # 检查时间是否严格递增，避免重复时间戳导致的错误
                if prev_time is not None and klu.time <= prev_time:
                    # 如果时间不严格递增，跳过这条数据
                    continue
                prev_time = klu.time
                yield klu
        else:
            return

    def SetBasciInfo(self):
        """设置基本信息"""
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass


def download_and_save_all_stocks(stock_codes, days=365, log_callback=None):
    """
    Download and save all stock data to SQLite database using multiple data sources
    
    Args:
        stock_codes: list of stock codes to download
        days: number of days to download, default 365
        log_callback: optional callback function for logging messages
    """
    from datetime import datetime, timedelta
    from Trade.db_util import CChanDB
    from Common.CEnum import AUTYPE, KL_TYPE
    import sqlite3
    import pandas as pd
    
    db = CChanDB()
    
    begin_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_time = datetime.now().strftime("%Y-%m-%d")
    
    for code in stock_codes:
        kl_data = None
        source_used = None
        
        try:
            # Determine market type and select appropriate data source
            if code.startswith("US."):
                # 美股: 优先使用AKShare
                kl_data, source_used = _download_us_stock_data(code, begin_time, end_time)
                
            elif code.startswith("HK."):
                # 港股: 优先使用Futu，失败则使用AKShare
                kl_data, source_used = _download_hk_stock_data(code, begin_time, end_time)
                
            elif code.startswith("SZ.") or code.startswith("SH."):
                # A股: 优先使用BaoStock，失败则使用AKShare
                kl_data, source_used = _download_a_stock_data(code, begin_time, end_time)
                
            else:
                # 默认使用AKShare
                kl_data, source_used = _download_with_akshare(code, begin_time, end_time)
            
            if kl_data:
                # Save to database
                df = pd.DataFrame(kl_data)
                # Insert or replace data in kline_day table
                with sqlite3.connect(db.db_path) as conn:
                    # 先删除该股票的旧数据
                    conn.execute("DELETE FROM kline_day WHERE code = ?", (code,))
                    df.to_sql('kline_day', conn, if_exists='append', index=False)
                if log_callback:
                    log_callback(f"✅ 成功下载 {code} ({len(kl_data)} 条数据) - 数据源: {source_used}")
                else:
                    print(f"✅ 成功下载 {code} ({len(kl_data)} 条数据) - 数据源: {source_used}")
            else:
                if log_callback:
                    log_callback(f"⚠️  {code} 无有效数据")
                else:
                    print(f"⚠️  {code} 无有效数据")
                
        except Exception as e:
            if log_callback:
                log_callback(f"❌ 下载 {code} 失败: {e}")
            else:
                print(f"❌ 下载 {code} 失败: {e}")
            continue

def download_and_save_all_stocks_multi_timeframe(stock_codes, days=365, timeframes=['day', '30m', '5m', '1m'], log_callback=None, start_date=None, end_date=None, stop_check=None):
    """
    Download and save all stock data to SQLite database for multiple timeframes
    
    Args:
        stock_codes: list of stock codes to download
        days: number of days to download for day timeframe, default 365
        timeframes: list of timeframes to download ['day', '30m', '5m', '1m']
        log_callback: optional callback function for logging messages
        start_date: optional start date in 'YYYY-MM-DD' format, overrides 'days' parameter
        end_date: optional end date in 'YYYY-MM-DD' format, defaults to today if not specified
        stop_check: optional callback function that returns True if operation should be stopped
    """
    from datetime import datetime, timedelta
    from Trade.db_util import CChanDB
    from Common.CEnum import AUTYPE, KL_TYPE
    import sqlite3
    import pandas as pd
    
    db = CChanDB()
    
    # Timeframe mapping - use reasonable default days for different timeframes
    # Note: For minute-level data, the actual data availability depends on the data source
    # We use the user-specified 'days' for day data, but cap minute data to reasonable limits
    # Increased limits for 30m data to get more historical data
    # For缠论 analysis, we need sufficient historical data, so increased the limits
    tf_map = {
        'day': (KL_TYPE.K_DAY, days),
        '30m': (KL_TYPE.K_30M, min(days, 730)),  # Cap 30m to 730 days max (2 years) for better analysis
        '5m': (KL_TYPE.K_5M, min(days, 180)),    # Cap 5m to 180 days max (6 months) for better analysis
        '1m': (KL_TYPE.K_1M, min(days, 90)),     # Cap 1m to 90 days max (3 months) for better analysis
    }
    
    # Filter valid timeframes
    valid_timeframes = [tf for tf in timeframes if tf in tf_map]
    
    import time
    api_request_count = 0
    start_time = time.time()
    
    for code in stock_codes:
        # Check if we should stop before processing each stock
        if stop_check and stop_check():
            print("⚠️  数据下载被用户取消")
            if log_callback:
                log_callback("⚠️  数据下载被用户取消")
            return
            
        for tf_name in valid_timeframes:
            # ---> 限制请求频率: 每30秒最多60次，我们保守设置为50次 <---
            api_request_count += 1
            if api_request_count >= 45:
                elapsed = time.time() - start_time
                if elapsed < 31:
                    sleep_time = 31 - elapsed
                    msg = f"⏳ 为避免触发API频率限制(60次/30秒)，暂停 {sleep_time:.1f} 秒..."
                    print(msg)
                    if log_callback:
                        log_callback(msg)
                    time.sleep(sleep_time)
                # 重置计数器和计时器
                api_request_count = 0
                start_time = time.time()
            else:
                # 即使没有达到上限，也稍微间隔一点点
                time.sleep(0.1)
                
            k_type, tf_days = tf_map[tf_name]
            table_name = f"kline_{tf_name}"
            
            # Handle custom date range with time support
            if start_date and end_date:
                desired_begin_time = start_date
                desired_end_time = end_date
            elif start_date:
                desired_begin_time = start_date
                desired_end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif end_date:
                desired_end_time = end_date
                # If end_date has time, use it for subtraction
                try:
                    dt_end = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S") if ' ' in end_date else datetime.strptime(end_date, "%Y-%m-%d")
                    desired_begin_time = (dt_end - timedelta(days=tf_days)).strftime("%Y-%m-%d %H:%M:%S")
                except:
                    desired_begin_time = (datetime.now() - timedelta(days=tf_days)).strftime("%Y-%m-%d")
            else:
                desired_end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                desired_begin_time = (datetime.now() - timedelta(days=tf_days)).strftime("%Y-%m-%d %H:%M:%S")
            
            # Check existing data in database
            with sqlite3.connect(db.db_path) as conn:
                existing_df = pd.read_sql_query(f"SELECT MIN(date) as min_date, MAX(date) as max_date FROM {table_name} WHERE code = ?", conn, params=(code,))
            
            if not existing_df.empty and existing_df.iloc[0]['min_date'] is not None:
                existing_min = existing_df.iloc[0]['min_date']
                existing_max = existing_df.iloc[0]['max_date']
                print(f"ℹ️  {code} {tf_name} 已有数据范围: {existing_min} 到 {existing_max}")
                
                # 无论是默认范围还是自定义UI范围，都执行增量更新判断
                if existing_max < desired_end_time:
                    # Need to download recent data
                    if tf_name == 'day':
                        begin_time = (datetime.strptime(existing_max.split(' ')[0], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                    else:
                        # 对于分钟级别，从现有的最后一条开始下载（接口会自动排除或由于 INSERT OR REPLACE 覆盖）
                        begin_time = existing_max
                    end_time = desired_end_time
                    
                    if begin_time >= end_time and tf_name == 'day':
                        print(f"✅ {code} {tf_name} 最新数据已完整，跳过下载")
                        continue
                else:
                    # Already have recent data, check if we need historical data
                    if existing_min > desired_begin_time:
                        begin_time = desired_begin_time
                        if tf_name == 'day':
                            end_time = (datetime.strptime(existing_min.split(' ')[0], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                        else:
                            end_time = existing_min
                            
                        if begin_time >= end_time and tf_name == 'day':
                            print(f"✅ {code} {tf_name} 历史数据已完整，跳过下载")
                            continue
                        msg_hist = f"ℹ️  {code} {tf_name} 尝试补充历史数据: {begin_time} 到 {end_time}"
                        print(msg_hist)
                        if log_callback:
                            log_callback(msg_hist)
                    else:
                        print(f"✅ {code} {tf_name} 已包含请求的完整数据范围 ({desired_begin_time} 至 {desired_end_time})，跳过下载")
                        if log_callback:
                            log_callback(f"✅ {code} {tf_name} 增量数据已最新，跳过下载")
                        continue
            else:
                # No existing data, download full range
                begin_time = desired_begin_time
                end_time = desired_end_time
            
            kl_data = None
            source_used = None
            
            # DEBUG: 打印时间范围
            msg_debug = f"🔍  试图下载 {code} {tf_name}: {begin_time} 到 {end_time}"
            print(msg_debug)
            if log_callback:
                log_callback(msg_debug)
            
            try:
                # Use the same logic as day timeframe for all timeframes
                if code.startswith("US."):
                    # 美股: 优先使用AKShare（支持分钟级别）
                    kl_data, source_used = _download_us_stock_data_with_timeframe(code, begin_time, end_time, k_type)
                elif code.startswith("HK."):
                    # 港股: 优先使用Futu，失败则使用AKShare（都支持分钟级别）
                    kl_data, source_used = _download_hk_stock_data_with_timeframe(code, begin_time, end_time, k_type)
                elif code.startswith("SZ.") or code.startswith("SH."):
                    # A股: 优先使用BaoStock，失败则使用AKShare（都支持分钟级别）
                    kl_data, source_used = _download_a_stock_data_with_timeframe(code, begin_time, end_time, k_type)
                else:
                    # 默认使用AKShare
                    kl_data, source_used = _download_with_akshare_with_timeframe(code, begin_time, end_time, k_type)
                
                if kl_data:
                    # Save to database - incremental update (no deletion of existing data)
                    df = pd.DataFrame(kl_data)
                    with sqlite3.connect(db.db_path) as conn:
                        # Check existing data range
                        existing_df = pd.read_sql_query(f"SELECT MIN(date) as min_date, MAX(date) as max_date FROM {table_name} WHERE code = ?", conn, params=(code,))
                        if not existing_df.empty and existing_df.iloc[0]['min_date'] is not None:
                            existing_min = existing_df.iloc[0]['min_date']
                            existing_max = existing_df.iloc[0]['max_date']
                        
                        # Remove duplicates before inserting
                        df = df.drop_duplicates(subset=['date'], keep='last')
                        
                        # Handle unique constraint by using INSERT OR REPLACE
                        records = df.to_records(index=False)
                        columns = df.columns.tolist()
                        
                        placeholders = ', '.join(['?' for _ in columns])
                        columns_str = ', '.join(columns)
                        sql = f"INSERT OR REPLACE INTO {table_name} ({columns_str}) VALUES ({placeholders})"
                        
                        conn.executemany(sql, records)
                        conn.commit()
                    
                    msg_success = f"✅ 成功下载 {code} {tf_name} ({len(kl_data)} 条数据) - 数据源: {source_used}"
                    if log_callback:
                        log_callback(msg_success)
                    else:
                        print(msg_success)
                else:
                    msg_empty = f"⚠️  {code} {tf_name} API 返回空数据 (Futu/Akshare 均无结果)"
                    print(msg_empty)
                    if log_callback:
                        log_callback(msg_empty)
                        
            except Exception as e:
                if log_callback:
                    log_callback(f"❌ 下载 {code} {tf_name} 失败: {e}")
                else:
                    print(f"❌ 下载 {code} {tf_name} 失败: {e}")
                continue

def _download_us_stock_data(code, begin_time, end_time):
    """下载美股数据 - 优先使用AKShare"""
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE, KL_TYPE
    
    try:
        # 转换为AKShare格式
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "AKShare"
    except Exception as e:
        print(f"  ⚠️  AKShare下载美股 {code} 失败: {e}")
        return None, "None"

def _download_us_stock_data_with_timeframe(code, begin_time, end_time, k_type):
    """下载美股数据（支持多时间级别） - 优先使用Futu，失败则使用AKShare"""
    from DataAPI.FutuAPI import CFutuAPI
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE, KL_TYPE
    
    # 首先尝试Futu
    try:
        api = CFutuAPI(code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        kl_data = _extract_kl_data(api, code)
        if kl_data and len(kl_data) > 0:
            return kl_data, "Futu"
        else:
            print(f"  ℹ️  Futu下载美股 {code} {k_type} 无历史数据")
    except Exception as e:
        print(f"  ⚠️  Futu下载美股 {code} {k_type} 失败: {e}")
        
    # Futu失败或无数据，尝试AKShare
    # 注意：AKShare的美股接口 stock_us_daily 目前只支持日线级别
    if k_type != KL_TYPE.K_DAY:
        print(f"  ℹ️  AKShare的美股接口暂不支持分钟级别数据，跳过 {code} {k_type}")
        return None, "None"
        
    try:
        # 转换为AKShare格式
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        kl_data = _extract_kl_data(api, code)
        if kl_data and len(kl_data) > 0:
            return kl_data, "AKShare"
        else:
            print(f"  ℹ️  AKShare下载美股 {code} {k_type} 无历史数据")
    except Exception as e:
        print(f"  ⚠️  AKShare下载美股 {code} {k_type} 失败: {e}")
        
    return None, "None"

def _download_hk_stock_data_with_timeframe(code, begin_time, end_time, k_type):
    """下载港股数据（支持多时间级别） - 优先使用Futu，失败则使用AKShare"""
    from DataAPI.FutuAPI import CFutuAPI
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE
    
    # 首先尝试Futu
    try:
        api = CFutuAPI(code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        kl_data = _extract_kl_data(api, code)
        if kl_data and len(kl_data) > 0:
            return kl_data, "Futu"
        else:
            print(f"  ℹ️  Futu下载港股 {code} {k_type} 无历史数据")
    except Exception as e:
        print(f"  ⚠️  Futu下载港股 {code} {k_type} 失败: {e}")
    
    # Futu失败或无数据，尝试AKShare
    try:
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        kl_data = _extract_kl_data(api, code)
        if kl_data and len(kl_data) > 0:
            return kl_data, "AKShare"
        else:
            print(f"  ℹ️  AKShare下载港股 {code} {k_type} 无历史数据")
    except Exception as e:
        print(f"  ⚠️  AKShare下载港股 {code} {k_type} 失败: {e}")
    
    # 所有方法都失败
    print(f"  ℹ️  港股 {code} {k_type} 无可用历史数据")
    return None, "None"

def _download_a_stock_data_with_timeframe(code, begin_time, end_time, k_type):
    """下载A股数据（支持多时间级别） - 优先使用Futu，失败则使用BaoStock，再失败则使用AKShare"""
    from DataAPI.FutuAPI import CFutuAPI
    from DataAPI.BaoStockAPI import CBaoStock
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE
    
    # 首先尝试Futu
    try:
        # Futu API可以直接使用 SH.600000 或 SZ.000001 格式
        api = CFutuAPI(code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "Futu"
    except Exception as e:
        print(f"  ⚠️  Futu下载A股 {code} {k_type} 失败: {e}")
    
    # Futu失败，尝试BaoStock
    try:
        # BaoStock需要完整的9位代码格式 (sh.600000 或 sz.000001)
        market, stock_num = code.split(".")
        if market == "SH":
            bao_code = f"sh.{stock_num}"
        elif market == "SZ":
            bao_code = f"sz.{stock_num}"
        else:
            raise ValueError(f"不支持的A股市场: {market}")
        
        # 确保BaoStock已初始化
        CBaoStock.do_init()
        api = CBaoStock(bao_code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "BaoStock"
    except Exception as e:
        print(f"  ⚠️  BaoStock下载A股 {code} {k_type} 失败: {e}")
    
    # BaoStock失败，尝试AKShare
    try:
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "AKShare"
    except Exception as e:
        print(f"  ⚠️  AKShare下载A股 {code} {k_type} 失败: {e}")
        return None, "None"

def _download_with_akshare_with_timeframe(code, begin_time, end_time, k_type):
    """使用AKShare下载数据（支持多时间级别）（通用方法）"""
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE
    
    try:
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "AKShare"
    except Exception as e:
        print(f"  ⚠️  AKShare下载 {code} {k_type} 失败: {e}")
        return None, "None"

def _download_hk_stock_data(code, begin_time, end_time):
    """下载港股数据 - 优先使用Futu，失败则使用AKShare"""
    from DataAPI.FutuAPI import CFutuAPI
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE, KL_TYPE
    
    # 首先尝试Futu
    try:
        api = CFutuAPI(code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        kl_data = _extract_kl_data(api, code)
        if kl_data and len(kl_data) > 0:
            return kl_data, "Futu"
        else:
            print(f"  ℹ️  Futu下载港股 {code} 无历史数据（可能是新股或停牌）")
    except Exception as e:
        print(f"  ⚠️  Futu下载港股 {code} 失败: {e}")
    
    # Futu失败或无数据，尝试AKShare
    try:
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        kl_data = _extract_kl_data(api, code)
        if kl_data and len(kl_data) > 0:
            return kl_data, "AKShare"
        else:
            print(f"  ℹ️  AKShare下载港股 {code} 无历史数据")
    except Exception as e:
        print(f"  ⚠️  AKShare下载港股 {code} 失败: {e}")
    
    # 所有方法都失败
    print(f"  ℹ️  港股 {code} 无可用历史数据（不影响其他股票扫描）")
    return None, "None"

def _download_a_stock_data(code, begin_time, end_time):
    """下载A股数据 - 优先使用Futu，失败则使用BaoStock，再失败则使用AKShare"""
    from DataAPI.FutuAPI import CFutuAPI
    from DataAPI.BaoStockAPI import CBaoStock
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE, KL_TYPE
    
    # 首先尝试Futu
    try:
        # Futu API可以直接使用 SH.600000 或 SZ.000001 格式
        api = CFutuAPI(code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "Futu"
    except Exception as e:
        print(f"  ⚠️  Futu下载A股 {code} 失败: {e}")
    
    # Futu失败，尝试BaoStock
    try:
        # BaoStock需要完整的9位代码格式 (sh.600000 或 sz.000001)
        market, stock_num = code.split(".")
        if market == "SH":
            bao_code = f"sh.{stock_num}"
        elif market == "SZ":
            bao_code = f"sz.{stock_num}"
        else:
            raise ValueError(f"不支持的A股市场: {market}")
        
        # 确保BaoStock已初始化
        CBaoStock.do_init()
        api = CBaoStock(bao_code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "BaoStock"
    except Exception as e:
        print(f"  ⚠️  BaoStock下载A股 {code} 失败: {e}")
    
    # BaoStock失败，尝试AKShare
    try:
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "AKShare"
    except Exception as e:
        print(f"  ⚠️  AKShare下载A股 {code} 失败: {e}")
        return None, "None"

def _download_with_akshare(code, begin_time, end_time):
    """使用AKShare下载数据（通用方法）"""
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE, KL_TYPE
    
    try:
        akshare_code = convert_stock_code_for_akshare(code)
        api = CAkshare(akshare_code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
        return _extract_kl_data(api, code), "AKShare"
    except Exception as e:
        print(f"  ⚠️  AKShare下载 {code} 失败: {e}")
        return None, "None"

def _extract_kl_data(api, original_code):
    """从API提取K线数据"""
    kl_data = []
    for kl_unit in api.get_kl_data():
        # 根据时间级别确定日期格式
        if hasattr(api, 'k_type'):
            k_type = api.k_type
            if k_type in [KL_TYPE.K_1M, KL_TYPE.K_5M, KL_TYPE.K_15M, KL_TYPE.K_30M, KL_TYPE.K_60M]:
                # 分钟级别数据包含小时和分钟
                date_str = f"{kl_unit.time.year}-{kl_unit.time.month:02d}-{kl_unit.time.day:02d} {kl_unit.time.hour:02d}:{kl_unit.time.minute:02d}:00"
            else:
                # 日线及以上级别只包含日期
                date_str = f"{kl_unit.time.year}-{kl_unit.time.month:02d}-{kl_unit.time.day:02d}"
        else:
            # 默认只包含日期
            date_str = f"{kl_unit.time.year}-{kl_unit.time.month:02d}-{kl_unit.time.day:02d}"
            
        kl_data.append({
            'code': original_code,  # 使用原始代码存储到数据库
            'date': date_str,
            'open': kl_unit.open,
            'high': kl_unit.high,
            'low': kl_unit.low,
            'close': kl_unit.close,
            'volume': getattr(kl_unit, 'volume', 0),
            'turnover': getattr(kl_unit, 'turnover', 0),
            'turnrate': getattr(kl_unit, 'turnrate', 0.0)
        })
    return kl_data if kl_data else None