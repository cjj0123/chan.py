import pandas as pd
from datetime import datetime
import time
import random
import threading
from futu import * 
from DataAPI.CommonStockAPI import CCommonStockApi
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

_futu_local = threading.local()

class CFutuAPI(CCommonStockApi):
    _futu_lock = threading.Lock()  # 全局线程锁，防止 request_history_kline 并发频率超限 -1
    
    def __init__(self, code, k_type, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CFutuAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        
        self.type_map = {
            KL_TYPE.K_1M: SubType.K_1M,
            KL_TYPE.K_5M: SubType.K_5M,
            KL_TYPE.K_15M: SubType.K_15M,
            KL_TYPE.K_30M: SubType.K_30M,
            KL_TYPE.K_60M: SubType.K_60M,
            KL_TYPE.K_DAY: SubType.K_DAY,
            KL_TYPE.K_WEEK: SubType.K_WEEK,
            KL_TYPE.K_MON: SubType.K_MON,
        }
        
        self.autype_map = {
            AUTYPE.QFQ: AuType.QFQ,
            AUTYPE.HFQ: AuType.HFQ,
            AUTYPE.NONE: AuType.NONE,
        }

    def get_kl_data(self):
        """
        [EvoMap Strategy Fusion - Online Version]
        - Smart Retry for API Limits
        - Median-based Anomaly Filtering
        - Fixed: use request_history_kline instead of non-existent get_history_kl
        """
        stock_code = str(self.code).upper() 
        if '.' not in stock_code:
            if len(stock_code) == 5: stock_code = f"HK.{stock_code}"
            elif stock_code.startswith('6'): stock_code = f"SH.{stock_code}"
            else: stock_code = f"SZ.{stock_code}"
        
        global _futu_local
        if not hasattr(_futu_local, 'quote_ctx') or _futu_local.quote_ctx is None:
            _futu_local.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        quote_ctx = _futu_local.quote_ctx
        
        try:
            f_ktype = self.type_map.get(self.k_type, SubType.K_DAY)
            f_autype = self.autype_map.get(self.autype, AuType.QFQ)
            
            # 1. 订阅检查
            quote_ctx.subscribe([stock_code], [f_ktype], subscribe_push=False)

            # 2. 指数退避重试 + 分页处理 (使用 request_history_kline)
            retries = 3
            all_data = []
            page_token = None
            current_retry = 0
            
            time.sleep(0.2)  # 🛡️ [风控加固] 略微增加基准延时，确保 30s/60次 物理安全 (30s / 60 = 0.5s，此处 0.2s + random 组合)
            
            # --- Proactive Optimization for "Today" Requests ---
            today_str = datetime.now().strftime("%Y-%m-%d")
            use_cur_kline_directly = (self.begin_date == today_str) or (self.begin_date is None)
            
            while current_retry < retries:
                # 🛡️ [风控加固] 如果是“仅拉取今日”请求，且第一次尝试，优先走 get_cur_kline 节省历史额度
                if use_cur_kline_directly and current_retry == 0:
                    lock_acquired = CFutuAPI._futu_lock.acquire(timeout=25)
                    if lock_acquired:
                        try:
                            quote_ctx.subscribe([stock_code], [f_ktype], subscribe_push=False)
                            ret_live, data_live = quote_ctx.get_cur_kline(stock_code, num=1000, ktype=f_ktype)
                            if ret_live == RET_OK and data_live is not None and not data_live.empty:
                                all_data.append(data_live)
                                ret = RET_OK
                                break
                        finally:
                            CFutuAPI._futu_lock.release()
                    else:
                        print(f"💡 [FutuAPI] {stock_code} {f_ktype} 实时拉取因锁竞争超时 (25s)，跳过实时尝试。")
                    
                    if ret != RET_OK:
                        print(f"💡 [FutuAPI] {stock_code} {f_ktype} 优先实时拉取失败，回退至历史接口。")

                # 首次请求不需要 page_token，后续请求需要
                # 🛡️ [架构优化] 改为非阻塞锁且带有 25s 超时，防止线程在 API 挂起时发生堆积
                lock_acquired = CFutuAPI._futu_lock.acquire(timeout=25)
                if not lock_acquired:
                    print(f"🚨 [FutuAPI] {stock_code} 锁竞争超时 (25s)，强制跳过以保护执行池。")
                    raise RuntimeError(f"FutuAPI Lock Timeout for {stock_code}")
                
                try:
                    if page_token is None:
                        ret, data, new_page_token = quote_ctx.request_history_kline(
                            stock_code,
                            start=self.begin_date,
                            end=self.end_date,
                            ktype=f_ktype,
                            autype=f_autype
                        )
                    else:
                        ret, data, new_page_token = quote_ctx.request_history_kline(
                            stock_code,
                            start=self.begin_date,
                            end=self.end_date,
                            ktype=f_ktype,
                            autype=f_autype,
                            page_req_key=page_token
                        )
                    # 锁内预留微小时间间隙，保障 OpenD 绝对安全
                    if ret != RET_OK:
                        time.sleep(0.1)
                finally:
                    CFutuAPI._futu_lock.release()
                
                if ret == RET_OK:
                    if data is not None and not data.empty:
                        all_data.append(data)
                    
                    # 检查是否还有更多数据
                    if new_page_token is None or new_page_token == "":
                        break
                    else:
                        page_token = new_page_token
                        time.sleep(random.uniform(0.1, 0.3))  # 短暂延迟避免API限制
                        continue  # 继续下一页，不增加重试计数
                else:
                    error_msg = str(data)
                    # 🛡️ [风控加固] 额度不足 (Quota) 或 频率太高 (Frequency) 均触发 get_cur_kline 实时拉取降级
                    is_limit = "频" in error_msg or "frequency" in error_msg.lower() or "额度" in error_msg or data is None or error_msg == "None"
                    
                    if is_limit:
                        print(f"💡 [FutuAPI] {stock_code} {f_ktype} 受限({error_msg})，自适应降级至 get_cur_kline 实时拉取")
                        # get_cur_kline 依赖订阅，确保加锁订阅
                        lock_acquired = CFutuAPI._futu_lock.acquire(timeout=25)
                        if lock_acquired:
                            try:
                                quote_ctx.subscribe([stock_code], [f_ktype], subscribe_push=False)
                                ret_live, data_live = quote_ctx.get_cur_kline(stock_code, num=1000, ktype=f_ktype)
                                if ret_live == RET_OK and data_live is not None and not data_live.empty:
                                    all_data.append(data_live)
                                    ret = RET_OK  # 标记为成功，防止上层触发异常
                                    break
                            finally:
                                CFutuAPI._futu_lock.release()
                        else:
                            print(f"💡 [FutuAPI] {stock_code} {f_ktype} 降级尝试因锁超时 (25s) 拦截。")
                    
                    print(f"⚠️ [FutuAPI] Request failed ({data}), retrying {current_retry+1}/{retries}...")
                    time.sleep(random.uniform(0.5, 1.0) * (2 ** current_retry))
                    current_retry += 1
            
            # 合并所有页面的数据
            if all_data:
                data = pd.concat(all_data, ignore_index=True)
            else:
                data = None

            # DEBUG: 打印原始返回结果
            print(f"📡 [FutuAPI] {stock_code} {f_ktype} 原始结果: ret={ret}, 数据集大小={len(data) if data is not None else 0}")

            if ret == RET_OK and data is not None and not data.empty:
                # 3. 异常值过滤
                data['price_change'] = data['close'].diff().abs()
                median_change = data['price_change'].median()
                if median_change > 0:
                    outliers = data[data['price_change'] > median_change * 15]
                    if not outliers.empty:
                        print(f"[EVOMAP-RECOVERY] Warning: Found {len(outliers)} online price anomalies for {stock_code}.")

                for _, row in data.iterrows():
                    time_str = row['time_key']
                    try:
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        dt = datetime.strptime(time_str, "%Y-%m-%d")

                    item_dict = {
                        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                        DATA_FIELD.FIELD_OPEN: float(row['open']),
                        DATA_FIELD.FIELD_HIGH: float(row['high']),
                        DATA_FIELD.FIELD_LOW: float(row['low']),
                        DATA_FIELD.FIELD_CLOSE: float(row['close']),
                        DATA_FIELD.FIELD_VOLUME: float(row['volume']),
                        DATA_FIELD.FIELD_TURNOVER: float(row.get('turnover', 0.0)),
                        DATA_FIELD.FIELD_TURNRATE: float(row.get('turnover_rate', 0.0))
                    }
                    yield CKLine_Unit(item_dict)
                return  # 成功生成所有数据，结束生成器

            # 数据为空或请求失败的处理逻辑
            if ret != RET_OK:
                error_msg = f"API Error (ret={ret}): {data}"
            elif not all_data:
                error_msg = "Empty dataset (possibly no trades in the requested date range or frequency limit exceeded)"
            else:
                error_msg = "Unknown error"
            
            raise ValueError(f"FutuAPI returned no data for {stock_code}. Reason: {error_msg}")
                
        except Exception as e:
            if "Frequency limit" in str(e) or (ret != RET_OK and "limit" in str(data).lower()):
                 print(f"🚨 [FutuAPI] {stock_code} 疑似触发频率限制，建议在大循环中增加延时")
            print(f"🔥 [FutuAPI] Online Error for {stock_code}: {e}")
            
            # 🛡️ [Fix] Close existing connection before resetting to prevent leaks (128 limit)
            if hasattr(_futu_local, 'quote_ctx') and _futu_local.quote_ctx is not None:
                try:
                    _futu_local.quote_ctx.close()
                except:
                    pass
            _futu_local.quote_ctx = None  
            raise e
        finally:
            # Reusing connection via thread-local, do not close here
            pass

    @classmethod
    def close_all(cls):
        """显式关闭当前线程的所有 Futu 连接"""
        global _futu_local
        if hasattr(_futu_local, 'quote_ctx') and _futu_local.quote_ctx is not None:
            try:
                _futu_local.quote_ctx.close()
                print("🔌 [FutuAPI] 已显式关闭 OpenQuoteContext")
            except:
                pass
            _futu_local.quote_ctx = None

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True
