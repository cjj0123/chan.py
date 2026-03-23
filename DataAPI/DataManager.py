"""
统一数据管理器 - DataManager
实现混合数据源策略：本地数据库（历史数据）+ 实时API（最新数据）
支持多级缓存和并发处理
"""
import os
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Generator
from Common.CEnum import KL_TYPE, AUTYPE
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.SQLiteAPI import SQLiteAPI
from DataAPI.FutuAPI import CFutuAPI
from Common.multi_level_cache import multi_level_cache

# Futu API imports for real-time price fetching
try:
    from futu import OpenQuoteContext, RET_OK
except ImportError:
    OpenQuoteContext = None
    RET_OK = None


class DataManager:
    """
    统一数据管理器
    
    设计原则：
    1. 混合数据源：本地SQLite数据库存储历史数据，Futu API获取实时/最新数据
    2. 多级缓存：内存缓存（@make_cache） + 磁盘缓存（SQLite）
    3. 智能回退：当实时API失败时，使用缠论分析中的价格作为备选
    4. 并发友好：支持多线程/多进程安全访问
    """
    
    def __init__(self, db_path: str = None):
        """
        初始化数据管理器
        
        Args:
            db_path: SQLite数据库路径，如果为None则使用默认路径
        """
        self.db_path = db_path
        # 缓存配置
        self.cache_enabled = True
        self.max_cache_size = 1000  # 最大缓存条目数
        
    @multi_level_cache
    def get_kline_data(self, 
                      code: str, 
                      k_type: KL_TYPE, 
                      begin_date: str = None, 
                      end_date: str = None,
                      autype: AUTYPE = AUTYPE.QFQ,
                      use_fallback: bool = True) -> List[CKLine_Unit]:
        """
        获取K线数据 - 主要入口方法
        
        数据获取策略：
        1. 首先尝试从本地SQLite数据库获取完整数据范围
        2. 如果数据库缺少最新数据（通常是最近1-2天），则从Futu API补充
        3. 如果Futu API失败且use_fallback=True，则返回数据库中可用的数据
        4. 如果完全失败，返回空列表
        
        Args:
            code: 股票代码 (e.g., "HK.00966", "SH.600000")
            k_type: K线类型
            begin_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)，默认为今天
            autype: 复权类型
            use_fallback: 是否使用备选方案（当API失败时返回部分数据）
            
        Returns:
            List[CKLine_Unit]: K线数据列表
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
            
        # 步骤1: 从本地数据库获取数据
        db_data = self._get_from_database(code, k_type, begin_date, end_date, autype)
        
        # 步骤2: 检查是否需要从API补充最新数据
        if self._needs_realtime_update(db_data, end_date, k_type):
            try:
                # 获取API数据（只获取缺失的最新部分）
                api_data = self._get_from_api(code, k_type, self._get_missing_date_range(db_data, end_date), end_date, autype)
                
                # 合并数据：数据库数据 + API最新数据
                combined_data = self._merge_kline_data(db_data, api_data)
                return combined_data
                
            except Exception as e:
                print(f"⚠️ [DataManager] API获取失败: {e}")
                if use_fallback and db_data:
                    print(f"ℹ️ [DataManager] 使用数据库数据作为备选方案")
                    return db_data
                else:
                    return []
        else:
            return db_data
    
    def _get_from_database(self, 
                          code: str, 
                          k_type: KL_TYPE, 
                          begin_date: str, 
                          end_date: str,
                          autype: AUTYPE) -> List[CKLine_Unit]:
        """从SQLite数据库获取数据"""
        try:
            sqlite_api = SQLiteAPI(code, k_type, begin_date, end_date, autype)
            return list(sqlite_api.get_kl_data())
        except Exception as e:
            print(f"⚠️ [DataManager] 数据库获取失败: {e}")
            return []
    
    def _get_from_api(self, 
                     code: str, 
                     k_type: KL_TYPE, 
                     begin_date: str, 
                     end_date: str,
                     autype: AUTYPE) -> List[CKLine_Unit]:
        """从外部 API 获取数据 (支持多市场)"""
        try:
            # 默认使用富途
            api_cls = CFutuAPI
            
            # 美股特殊处理
            if code.upper().startswith("US."):
                from config import API_CONFIG
                # 优先使用 Schwab API
                import os
                schwab_token_path = os.path.join(os.path.dirname(__file__), 'schwab_token.json')
                if os.path.exists(schwab_token_path):
                    from DataAPI.SchwabAPI import CSchwabAPI
                    api_cls = CSchwabAPI
                # 其次使用 Interactive Brokers
                elif os.getenv("IB_HOST"):
                    from DataAPI.InteractiveBrokersAPI import CInteractiveBrokersAPI
                    api_cls = CInteractiveBrokersAPI
                elif API_CONFIG.get('POLYGON_API_KEY'):
                    from DataAPI.PolygonAPI import CPolygonAPI
                    api_cls = CPolygonAPI
                elif API_CONFIG.get('FINNHUB_API_KEY'):
                    from DataAPI.FinnhubAPI import CFinnhubAPI
                    api_cls = CFinnhubAPI
                else:
                    from DataAPI.YFinanceAPI import CYFinanceAPI
                    api_cls = CYFinanceAPI
            
            api_instance = api_cls(code, k_type, begin_date, end_date, autype)
            return list(api_instance.get_kl_data())
        except Exception as e:
            raise Exception(f"API获取失败 ({code}): {e}")
    
    def _needs_realtime_update(self, db_data: List[CKLine_Unit], end_date: str, k_type: KL_TYPE) -> bool:
        """判断是否需要从实时API更新数据"""
        if not db_data:
            return True
            
        # 获取数据库中最新的日期
        latest_db_date = max(klu.time.to_str() for klu in db_data)
        target_end_date = end_date
        
        # 对于日线数据，如果数据库最新日期不是今天或昨天，需要更新
        if k_type == KL_TYPE.K_DAY:
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            return latest_db_date < yesterday
        else:
            # 对于分钟级别数据，总是需要实时数据
            return True
    
    def _get_missing_date_range(self, db_data: List[CKLine_Unit], end_date: str) -> str:
        """获取缺失数据的开始日期"""
        if not db_data:
            return end_date  # 如果没有数据库数据，从end_date开始（实际会由API处理完整范围）
            
        latest_db_date = max(klu.time.to_str() for klu in db_data)
        # 从数据库最新日期的下一天开始
        latest_dt = datetime.strptime(latest_db_date.split(' ')[0], "%Y-%m-%d")
        next_day = (latest_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        return next_day
    
    def _merge_kline_data(self, 
                         db_data: List[CKLine_Unit], 
                         api_data: List[CKLine_Unit]) -> List[CKLine_Unit]:
        """合并数据库数据和API数据，去重并按时间排序"""
        if not db_data:
            return api_data
        if not api_data:
            return db_data
            
        # 创建时间戳集合用于去重
        db_times = {klu.time.to_str() for klu in db_data}
        
        # 合并数据，优先保留API数据（更新的数据）
        merged = db_data.copy()
        for api_klu in api_data:
            api_time_str = api_klu.time.to_str()
            if api_time_str not in db_times:
                merged.append(api_klu)
            # 如果时间戳已存在，用API数据替换（因为API数据更新）
            else:
                # 找到对应的数据库K线并替换
                for i, db_klu in enumerate(merged):
                    if db_klu.time.to_str() == api_time_str:
                        merged[i] = api_klu
                        break
        
        # 按时间排序
        merged.sort(key=lambda x: x.time.to_str())
        return merged
    
    def get_current_price(self, code: str) -> Optional[float]:
        """
        获取当前价格 - 带缓存的版本
        
        价格获取策略：
        1. 首先尝试从Futu API获取实时价格
        2. 如果API失败，尝试从数据库获取最新收盘价
        3. 如果都失败，返回None
        
        Returns:
            float: 当前价格，如果无法获取则返回None
        """
        # 只有在Futu库可用时才尝试实时价格获取
        if OpenQuoteContext is not None and RET_OK is not None:
            try:
                # 尝试从Futu API获取实时价格
                quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                try:
                    ret, data = quote_ctx.get_market_snapshot([code])
                    if ret == RET_OK and not data.empty:
                        current_price = float(data.iloc[0]['last_price'])
                        if current_price > 0:
                            return current_price
                finally:
                    quote_ctx.close()
            except Exception as e:
                print(f"⚠️ [DataManager] 富途实时价格获取失败: {e}")
        
        # 美股特殊处理: Schwab API > Interactive Brokers 
        if code.upper().startswith("US."):
            import os
            schwab_token_path = os.path.join(os.path.dirname(__file__), 'schwab_token.json')
            if os.path.exists(schwab_token_path):
                try:
                    from DataAPI.SchwabAPI import CSchwabAPI
                    from Common.CEnum import KL_TYPE
                    import datetime
                    
                    # 取最近一天的1分钟线，最后一条即最新价
                    api = CSchwabAPI(code, k_type=KL_TYPE.K_1M, 
                                     begin_date=(datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d"), 
                                     end_date=datetime.datetime.now().strftime("%Y-%m-%d"))
                    kl_data = list(api.get_kl_data())
                    if kl_data and len(kl_data) > 0:
                        return kl_data[-1].close
                except Exception as e:
                    print(f"⚠️ [DataManager] Schwab实时价格获取失败: {e}")
            
            # 回退到 IB 
            elif os.getenv("IB_HOST"):
                try:
                    from ib_insync import IB, Stock
                    import asyncio
                    import random
                    import nest_asyncio
                    
                    # Use a different client ID range for real-time prices to avoid conflicts with download
                    realtime_client_id = int(os.getenv("IB_CLIENT_ID_RT", str(random.randint(2000, 2999))))
                    
                    async def fetch_ib_price():
                        ib_inner = IB()
                        try:
                            print(f"🚀 [DataManager] Connecting to IB RTP ({os.getenv('IB_HOST')}, ClientID: {realtime_client_id})...")
                            await ib_inner.connectAsync(
                                os.getenv("IB_HOST"), 
                                int(os.getenv("IB_PORT", "4002")), 
                                clientId=realtime_client_id,
                                timeout=5
                            )
                            symbol = code.split(".")[1]
                            contract = Stock(symbol, 'SMART', 'USD')
                            await ib_inner.qualifyContractsAsync(contract)
                            ib_inner.reqMarketDataType(3) # 延迟行情
                            ticker = ib_inner.reqMktData(contract, '', False, False)
                            
                            # 等待数据填充 (最多2秒)
                            for _ in range(20):
                                if ticker.last > 0 or ticker.close > 0:
                                    break
                                await asyncio.sleep(0.1)
                                
                            if ticker.last and ticker.last > 0:
                                return float(ticker.last)
                            elif ticker.close and ticker.close > 0:
                                return float(ticker.close)
                            return None
                        finally:
                            if ib_inner.isConnected():
                                ib_inner.disconnect()

                    # Robust execution in background threads
                    nest_asyncio.apply()
                    try:
                        # If there's already a loop running, use it. Otherwise use asyncio.run
                        try:
                            loop = asyncio.get_running_loop()
                            return loop.run_until_complete(fetch_ib_price())
                        except RuntimeError:
                            return asyncio.run(fetch_ib_price())
                    except Exception as loop_e:
                        print(f"⚠️ [DataManager] IB异步执行错误: {loop_e}")
                        return None
                except Exception as e:
                    print(f"⚠️ [DataManager] IB实时价格获取失败: {e}")
        
        # 回退到数据库最新收盘价
        try:
            db_data = self._get_from_database(code, KL_TYPE.K_DAY, None, None, AUTYPE.QFQ)
            if db_data:
                latest_close = db_data[-1].close
                if latest_close > 0:
                    return latest_close
        except Exception as e:
            print(f"⚠️ [DataManager] 数据库价格获取失败: {e}")
            
        return None
    
    @multi_level_cache
    def batch_get_kline_data(self, 
                           codes: List[str], 
                           k_type: KL_TYPE, 
                           begin_date: str = None, 
                           end_date: str = None,
                           autype: AUTYPE = AUTYPE.QFQ) -> Dict[str, List[CKLine_Unit]]:
        """
        批量获取K线数据 - 用于并发场景
        
        Args:
            codes: 股票代码列表
            k_type: K线类型
            begin_date: 开始日期
            end_date: 结束日期
            autype: 复权类型
            
        Returns:
            Dict[str, List[CKLine_Unit]]: 股票代码到K线数据的映射
        """
        result = {}
        for code in codes:
            try:
                result[code] = self.get_kline_data(code, k_type, begin_date, end_date, autype)
            except Exception as e:
                print(f"❌ [DataManager] 批量获取 {code} 失败: {e}")
                result[code] = []
        return result
    
    def update_local_database(self, 
                            codes: List[str], 
                            k_type: KL_TYPE, 
                            days: int = 365,
                            start_date: str = None,
                            end_date: str = None) -> Dict[str, bool]:
        """
        更新本地数据库
        
        Args:
            codes: 股票代码列表
            k_type: K线类型
            days: 下载天数（仅当日线且无自定义日期范围时使用）
            start_date: 自定义开始日期
            end_date: 自定义结束日期
            
        Returns:
            Dict[str, bool]: 更新结果，股票代码到成功/失败的映射
        """
        from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
        
        # 转换KL_TYPE到时间框架字符串
        tf_map = {
            KL_TYPE.K_DAY: 'day',
            KL_TYPE.K_30M: '30m',
            KL_TYPE.K_5M: '5m',
            KL_TYPE.K_1M: '1m'
        }
        
        timeframe = tf_map.get(k_type, 'day')
        timeframes = [timeframe]
        
        # 构建日志回调
        def log_callback(msg):
            print(msg)
            
        # 调用现有的下载函数
        try:
            download_and_save_all_stocks_multi_timeframe(
                codes, days, timeframes, log_callback, start_date, end_date
            )
            return {code: True for code in codes}
        except Exception as e:
            print(f"❌ [DataManager] 数据库更新失败: {e}")
            return {code: False for code in codes}


# 全局数据管理器实例
_data_manager_instance = None

def get_data_manager() -> DataManager:
    """获取全局数据管理器实例"""
    global _data_manager_instance
    if _data_manager_instance is None:
        _data_manager_instance = DataManager()
    return _data_manager_instance