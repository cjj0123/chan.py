from datetime import datetime, timedelta
import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from Chan import CChan
from ChanConfig import CChanConfig
from config import TRADING_CONFIG
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Common.StockUtils import get_futu_stock_name, get_default_data_sources
from Common.TimeUtils import get_trading_duration_hours

# 富途API相关
try:
    from futu import RET_OK
except ImportError:
    RET_OK = 0

# 各级别默认分析/扫描数据天数
# 确保在满足缠论结构分析的同时，最大限度提升响应速度
# 日线250根≈365天, 30M≈90天, 5M≈15天, 1M≈5天
LEVEL_DATA_DAYS = {
    KL_TYPE.K_DAY: 365,
    KL_TYPE.K_30M: 90,
    KL_TYPE.K_5M: 15,
    KL_TYPE.K_1M: 5,
}


class ScanThread(QThread):
    """
    批量扫描股票的后台线程

    在独立线程中遍历股票列表，对每只股票进行缠论分析，
    检测最近指定天数内是否出现买点。
    """
    progress = pyqtSignal(int, int, str)
    found_signal = pyqtSignal(dict)
    finished = pyqtSignal(int, int)
    log_signal = pyqtSignal(str)

    def __init__(self, stock_list, config, days=365, kl_type=KL_TYPE.K_DAY, data_src=DATA_SRC.FUTU):
        super().__init__()
        self.stock_list = stock_list
        self.config = config
        self.days = days
        self.kl_type = kl_type
        self.data_src = data_src
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        total = len(self.stock_list)
        success_count = 0
        fail_count = 0

        # 根据级别决定数据天数
        scan_days = self.days
        if self.kl_type != KL_TYPE.K_DAY:
            scan_days = LEVEL_DATA_DAYS.get(self.kl_type, self.days)
            self.log_signal.emit(f"⚙️ {self.kl_type.name} 扫描优化：使用最近 {scan_days} 天数据提升速度")
        
        begin_time = (datetime.now() - timedelta(days=scan_days)).strftime("%Y-%m-%d")
        end_time = datetime.now().strftime("%Y-%m-%d")

        # 尝试创建一个临时的 Futu 连接以复用，加速名称获取
        temp_quote_ctx = None
        try:
            from futu import OpenQuoteContext
            import os
            FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
            temp_quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
        except:
            pass

        try:
            for idx, row in self.stock_list.iterrows():
                if not self.is_running:
                    break
                
                code = row['代码']
                name = row['名称']
                
                # 从Futu获取准确的股票名称 (传入 temp_quote_ctx 以复用连接)
                accurate_name = get_futu_stock_name(code, quote_ctx=temp_quote_ctx)
                if accurate_name != code:
                    name = accurate_name
                
                self.progress.emit(idx + 1, total, f"{code} {name}")
                self.log_signal.emit(f"🔍 扫描 {code} {name}...")

                # 数据源选择逻辑：统一使用 Common.StockUtils 中的优先级
                from Common.StockUtils import get_default_data_sources
                data_sources = get_default_data_sources(code) if self.data_src == DATA_SRC.FUTU else [self.data_src]
                
                chan = None
                for src in data_sources:
                    try:
                        chan = CChan(
                            code=code,
                            begin_time=begin_time,
                            end_time=end_time,
                            data_src=src,
                            lv_list=[self.kl_type],
                            config=self.config,
                            autype=AUTYPE.QFQ,
                        )
                        if len(chan.lv_list) > 0 and len(chan[chan.lv_list[0]]) > 0:
                            break # 成功获取数据
                    except Exception as e:
                        continue
                
                try:
                    if chan is None or len(chan.lv_list) == 0:
                        fail_count += 1
                        self.log_signal.emit(f"⏭️ {code} {name}: 无K线数据")
                        continue
                    
                    last_klu = chan[chan.lv_list[0]][-1][-1]
                    last_time = last_klu.time
                    last_date = datetime(last_time.year, last_time.month, last_time.day)
                    if (datetime.now() - last_date).days > 15:
                        fail_count += 1
                        self.log_signal.emit(f"⏸️ {code} {name}: 停牌超过15天")
                        continue

                    success_count += 1

                    # 检查是否有买卖点
                    bsp_list = chan.get_latest_bsp(number=0)
                    
                    # 与自动交易保持一致：只显示最近 max_signal_age_hours 小时内的信号
                    max_age_hours = TRADING_CONFIG.get('max_signal_age_hours', 1)
                    now = datetime.now()
                    
                    buy_points = []
                    sell_points = []
                    for bsp in bsp_list:
                        # 转换 Bsp 的 CTime 为 datetime
                        b_time = bsp.klu.time
                        bsp_dt = datetime(b_time.year, b_time.month, b_time.day, b_time.hour, b_time.minute, b_time.second)
                        
                        # 计算交易小时数
                        trading_hours = get_trading_duration_hours(bsp_dt, now)
                        
                        # 过滤条件
                        if trading_hours <= max_age_hours:
                            if bsp.is_buy:
                                buy_points.append(bsp)
                            else:
                                sell_points.append(bsp)
                    

                    if buy_points:
                        latest_buy = buy_points[0]
                        self.log_signal.emit(f"✅ {code} {name}: 发现买点 {latest_buy.type2str()}")
                        self.found_signal.emit({
                            'code': code,
                            'name': name,
                            'price': row.get('最新价', 0.0),
                            'change': row.get('涨跌幅', 0.0),
                            'bsp_type': f"买点{latest_buy.type2str()}",
                            'bsp_time': str(latest_buy.klu.time),
                            'bsp_direction': 'buy',
                            'chan': chan,
                        })
                    elif sell_points:
                        latest_sell = sell_points[0]
                        self.log_signal.emit(f"🔴 {code} {name}: 发现卖点 {latest_sell.type2str()}")
                        self.found_signal.emit({
                            'code': code,
                            'name': name,
                            'price': row.get('最新价', 0.0),
                            'change': row.get('涨跌幅', 0.0),
                            'bsp_type': f"卖点{latest_sell.type2str()}",
                            'bsp_time': str(latest_sell.klu.time),
                            'bsp_direction': 'sell',
                            'chan': chan,
                        })
                    else:
                        self.log_signal.emit(f"➖ {code} {name}: 无近期买卖点")
                except Exception as e:
                    fail_count += 1
                    error_msg = str(e)
                    if "list index out of range" in error_msg:
                        self.log_signal.emit(f"❌ {code} {name}: 数据不足，无法分析")
                    elif "Broken pipe" in error_msg or "Errno 32" in error_msg:
                        self.log_signal.emit(f"❌ {code} {name}: 数据处理中断，可能是分钟级别数据格式问题")
                    elif "custom" in error_msg.lower():
                        self.log_signal.emit(f"❌ {code} {name}: 数据源错误，请检查数据库")
                    else:
                        self.log_signal.emit(f"❌ {code} {name}: {error_msg[:50]}")
                    continue

        except Exception as e:
            self.log_signal.emit(f"❌ 扫描过程出错: {str(e)}")
        finally:
            if temp_quote_ctx:
                temp_quote_ctx.close()
            # 确保美股连接被释放
            try:
                from DataAPI.InteractiveBrokersAPI import CInteractiveBrokersAPI
                CInteractiveBrokersAPI.do_close()
            except:
                pass

        self.finished.emit(success_count, fail_count)


class SingleAnalysisThread(QThread):
    """
    单只股票分析的后台线程
    支持按级别设置不同的数据天数范围
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, code, config, kl_types=None, days=365, data_sources=None):
        super().__init__()
        self.code = code
        self.config = config
        self.kl_types = kl_types or [KL_TYPE.K_DAY, KL_TYPE.K_30M, KL_TYPE.K_5M, KL_TYPE.K_1M]
        self.base_days = days  # 用户输入的天数，仅用于日线
        self.data_sources = data_sources or get_default_data_sources(code)

    def _get_days_for_level(self, kl_type):
        """根据级别返回合适的数据天数"""
        if kl_type == KL_TYPE.K_DAY:
            return self.base_days  # 日线使用用户输入值
        return LEVEL_DATA_DAYS.get(kl_type, self.base_days)

    def run(self):
        try:
            end_time = datetime.now().strftime("%Y-%m-%d")
            
            self.log_signal.emit(f"🔍 开始分析 {self.code}...")
            
            results = {}
            for kl_type in self.kl_types:
                # 每个级别使用不同的数据天数
                level_days = self._get_days_for_level(kl_type)
                begin_time = (datetime.now() - timedelta(days=level_days)).strftime("%Y-%m-%d")
                self.log_signal.emit(f"📊 级别 {kl_type.name}: 加载最近 {level_days} 天数据")
                
                chan = None
                for data_src in self.data_sources:
                    try:
                        self.log_signal.emit(f"尝试使用数据源: {data_src}")
                        chan = CChan(
                            code=self.code,
                            begin_time=begin_time,
                            end_time=end_time,
                            data_src=data_src,
                            lv_list=[kl_type],
                            config=self.config,
                            autype=AUTYPE.QFQ,
                        )
                        if len(chan.lv_list) > 0:
                            first_kl_data = chan[chan.lv_list[0]]
                            if len(first_kl_data) > 0:
                                break
                    except Exception as e:
                        self.log_signal.emit(f"级别 {kl_type.name} 数据源 {data_src} 失败: {str(e)}")
                        continue
                
                if chan is None or len(chan.lv_list) == 0:
                    self.log_signal.emit(f"⚠️ {self.code} 缺失级别: {kl_type.name} 数据")
                    continue
                
                try:
                    first_kl_type = chan.lv_list[0]
                    first_kl_data = chan[first_kl_type]
                    if hasattr(first_kl_data, 'bi_list'): _ = list(first_kl_data.bi_list)
                    if hasattr(first_kl_data, 'seg_list'): _ = list(first_kl_data.seg_list)
                    if hasattr(first_kl_data, 'zs_list'): _ = list(first_kl_data.zs_list)
                    results[kl_type.name] = chan
                except Exception as calc_error:
                    self.log_signal.emit(f"⚠️ 计算级别 {kl_type.name} 时出现: {str(calc_error)}")
            
            if not results:
                raise Exception(f"股票 {self.code} 没有任何可用级别的K线数据进行分析")
                
            self.log_signal.emit(f"✅ {self.code} 分析完成，获取到 {len(results)} 个级别数据")
            self.finished.emit(results)
        except Exception as e:
            error_msg = str(e)
            if "list index out of range" in error_msg:
                self.error.emit("数据不足，无法分析。请确保数据库中有足够的历史K线数据（至少30天以上）。")
            elif "custom" in error_msg.lower():
                self.error.emit("数据源错误，请检查数据库连接和表结构。")
            else:
                self.error.emit(str(e))
        finally:
            # 确保美股连接被释放
            try:
                from DataAPI.InteractiveBrokersAPI import CInteractiveBrokersAPI
                CInteractiveBrokersAPI.do_close()
            except:
                pass


class UpdateDatabaseThread(QThread):
    """
    更新本地数据库的后台线程
    """
    progress = pyqtSignal(int, int, str)
    log_signal = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, stock_codes, days, timeframes, start_date=None, end_date=None):
        super().__init__()
        self.stock_codes = stock_codes
        self.days = days
        self.timeframes = timeframes
        self.start_date = start_date
        self.end_date = end_date
        self.is_running = True
        
    def stop(self):
        self.is_running = False
        self.log_signal.emit("正在停止数据库更新...")
        
    def run(self):
        try:
            if not self.stock_codes:
                self.finished.emit(False, "股票列表为空")
                return
                
            total = len(self.stock_codes)
            
            from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
            from Trade.db_util import CChanDB
            
            def log_callback(msg):
                if self.is_running:
                    self.log_signal.emit(msg)
                    
            if self.is_running:
                def stop_check():
                    return not self.is_running
                
                import asyncio
                # Use the new async version which is optimized for IB
                from DataAPI.SQLiteAPI import download_and_save_all_stocks_async
                
                # Use a specific event loop for this thread to avoid asyncio.run issues
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(download_and_save_all_stocks_async(
                        self.stock_codes,
                        days=self.days,
                        timeframes=self.timeframes,
                        log_callback=log_callback,
                        start_date=self.start_date,
                        end_date=self.end_date,
                        stop_check=stop_check
                    ))
                except Exception as e:
                    self.log_signal.emit(f"❌ 异步下载出错: {e}")
                finally:
                    loop.close()
                
                if self.is_running:
                    db = CChanDB()
                    downloaded_codes = db.execute_query("SELECT DISTINCT code FROM kline_day")['code'].tolist()
                    success_count = len(downloaded_codes)
                    
                    market_stats = {}
                    total_klines = 0
                    for code in downloaded_codes:
                        count = db.execute_query(f"SELECT COUNT(*) as cnt FROM kline_day WHERE code = '{code}'")['cnt'].iloc[0]
                        total_klines += count
                        market = code.split('.')[0]
                        market_stats[market] = market_stats.get(market, 0) + 1
                    
                    result_msg = f"本地数据库更新完成！成功下载 {success_count}/{total} 只股票。"
                    self.log_signal.emit(f"✅ 本地数据库更新完成！")
                    self.log_signal.emit(f"   • 成功下载: {success_count} 只股票")
                    self.log_signal.emit(f"   • 总K线数: {total_klines} 条")
                    self.log_signal.emit(f"   • 市场分布: {', '.join([f'{k}:{v}' for k, v in market_stats.items()])}")
                    
                    failed_codes = [code for code in self.stock_codes if code not in downloaded_codes]
                    if failed_codes:
                        self.log_signal.emit(f"⚠️ 下载失败的股票 ({len(failed_codes)} 只):")
                        for i, code in enumerate(failed_codes[:10]):
                            self.log_signal.emit(f"   • {code}")
                        if len(failed_codes) > 10:
                            self.log_signal.emit(f"   ... 还有 {len(failed_codes) - 10} 只股票下载失败")
                    
                    self.finished.emit(True, result_msg)
                else:
                    self.finished.emit(False, "数据库更新被用户取消")
            else:
                self.finished.emit(False, "数据库更新被用户取消")
                
        except Exception as e:
            import traceback
            self.log_signal.emit(f"❌ 更新失败: {str(e)}")
            self.log_signal.emit(f"   错误详情: {traceback.format_exc()}")
            self.finished.emit(False, f"更新失败: {str(e)}")
        finally:
            # 确保多级别更新任务结束后关闭 IB 连接
            try:
                from DataAPI.InteractiveBrokersAPI import CInteractiveBrokersAPI
                CInteractiveBrokersAPI.do_close()
            except:
                pass


class RepairSingleStockThread(QThread):
    """
    单只股票数据修复的后台线程
    """
    log_signal = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, stock_code, start_date="2024-01-01"):
        super().__init__()
        self.stock_code = stock_code
        self.start_date = start_date
        self.is_running = True
        
    def stop(self):
        self.is_running = False
        self.log_signal.emit("正在停止数据修复...")
        
    def run(self):
        try:
            if not self.stock_code:
                self.finished.emit(False, "股票代码为空")
                return
                
            from datetime import datetime
            from repair_data import diagnose_and_repair_stock
            
            timeframes = ['day', '30m', '5m', '1m']
            end_date = datetime.now().strftime("%Y-%m-%d")
            
            repaired_count = 0
            
            def log_callback(msg):
                if self.is_running:
                    self.log_signal.emit(msg)
                    
            for timeframe in timeframes:
                if not self.is_running:
                    break
                
                try:
                    if diagnose_and_repair_stock(self.stock_code, timeframe, self.start_date, end_date, log_callback):
                        repaired_count += 1
                except Exception as e:
                    error_msg = f"修复 {self.stock_code} {timeframe} 数据时出错: {str(e)}"
                    self.log_signal.emit(f"❌ {error_msg}")
                    continue
            
            if self.is_running:
                if repaired_count > 0:
                    result_msg = f"股票 {self.stock_code} 的数据补全完成！成功修复了 {repaired_count} 个时间级别的数据。"
                    self.log_signal.emit(f"✅ {result_msg}")
                    self.finished.emit(True, result_msg)
                else:
                    result_msg = f"股票 {self.stock_code} 的数据已是完整的，无需修复。"
                    self.log_signal.emit(f"ℹ️ {result_msg}")
                    self.finished.emit(True, result_msg)
            else:
                self.finished.emit(False, "数据修复被用户取消")
                
        except Exception as e:
            import traceback
            self.log_signal.emit(f"❌ 数据修复失败: {str(e)}")
            self.log_signal.emit(f"   错误详情: {traceback.format_exc()}")
            self.finished.emit(False, f"数据修复失败: {str(e)}")
            try:
                from DataAPI.InteractiveBrokersAPI import CInteractiveBrokersAPI
                CInteractiveBrokersAPI.do_close()
            except:
                pass

class NewsCollectorThread(QThread):
    """
    后台抓取新闻和板块数据的线程
    """
    finished = pyqtSignal()
    log_signal = pyqtSignal(str)

    def run(self):
        try:
            from DataAPI.NewsCollector import NewsCollector
            self.log_signal.emit("🚀 启动市场感知引擎 (动态监测三地热点股票)...")
            c = NewsCollector()
            
            # Using the new automated cycle which handles dynamic seeds and analysis
            c.run_cycle()
            
            # Also capture sector heat with calculation updates
            self.log_signal.emit("🔥 正在抓取港股及美股板块资金联动...")
            c.save_sectors(c.collect_sector_heat('HK'))
            c.save_sectors(c.collect_sector_heat('US'))
            
            # Check for morning summary opportunity (e.g. 08:00 - 09:30)
            from datetime import datetime
            now = datetime.now()
            if now.hour == 8 or (now.hour == 9 and now.minute < 30):
                self.log_signal.emit("🌍 正在生成跨市场隔夜联动分析简报...")
                summary = c.generate_global_summary()
                self.log_signal.emit(f"AI 简报: {summary[:100]}...")

            c.close()
            self.log_signal.emit("✅ 市场感知更新完成！")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.log_signal.emit(f"❌ 抓取失败: {e}")
        finally:
            self.finished.emit()
