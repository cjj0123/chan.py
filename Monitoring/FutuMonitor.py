"""
Futu 实时监控模块
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futu import *
from datetime import datetime
import yaml
from DataAPI.SQLiteAPI import SQLiteAPI
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE, DATA_FIELD


class KLineHandler(StockQuoteHandlerBase):
    """自定义K线处理器"""
    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor
    
    def on_recv_rsp(self, rsp_str):
        """处理K线数据推送"""
        ret, data = super().on_recv_rsp(rsp_str)
        if ret != RET_OK:
            print(f"K线数据处理失败: {data}")
            return RET_ERROR
        
        # 处理K线数据
        for row in data.itertuples():
            code = row.code
            if code not in self.monitor.chan_objects:
                continue
            
            # 提取新的K线数据
            new_kl = {
                DATA_FIELD.FIELD_TIME: row.time_key,
                DATA_FIELD.FIELD_OPEN: row.open,
                DATA_FIELD.FIELD_HIGH: row.high,
                DATA_FIELD.FIELD_LOW: row.low,
                DATA_FIELD.FIELD_CLOSE: row.close,
                DATA_FIELD.FIELD_VOLUME: row.volume
            }
            
            # 根据k_type确定KL_TYPE
            k_type = row.k_type
            kl_type = None
            if k_type == "K_30M":
                kl_type = KL_TYPE.K_30M
            elif k_type == "K_5M":
                kl_type = KL_TYPE.K_5M
            
            if kl_type is None:
                print(f"未知的K线类型: {k_type}, 跳过处理")
                continue
            
            # 增量计算
            try:
                self.monitor.chan_objects[code].append_kl(new_kl, kl_type)
                # 检查是否有新买卖点（主要在30分钟级别检查，因为这是主要交易级别）
                if kl_type == KL_TYPE.K_30M:
                    from ModelStrategy.IntervalSuite import get_interval_suite_signal
                    interval_suite_signal = get_interval_suite_signal(self.monitor.chan_objects[code])
                    if interval_suite_signal and self.monitor.ui_callback:
                        signal_type, price, time_str = interval_suite_signal
                        self.monitor.ui_callback({
                            'code': code,
                            'signal': signal_type,
                            'price': price,
                            'time': time_str
                        })
            except Exception as e:
                print(f"处理 {code} 的新K线时出错: {e}")
        
        return RET_OK

class FutuMonitor:
    def __init__(self, config_path="Config/config.yaml"):
        # 加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        futu_config = self.config['futu']
        
        # 初始化富途 API
        self.quote_ctx = OpenQuoteContext(
            host=futu_config['host'],
            port=futu_config['port']
        )
        if futu_config.get('key'):
            self.quote_ctx.set_handler(StockQuoteHandler())
            self.quote_ctx.set_handler(OrderBookHandler())
            self.quote_ctx.set_handler(TickerHandler())
            self.quote_ctx.set_handler(RTDataHandler())
            self.quote_ctx.set_handler(BrokerHandler())
            self.quote_ctx.unlock_trade(futu_config['key'])
        
        # 设置K线处理器
        self.kline_handler = KLineHandler(self)
        self.quote_ctx.set_handler(self.kline_handler)
        
        # 不需要预先初始化 SQLiteAPI 实例
        # 用于存储每个股票的 CChan 对象
        self.chan_objects = {}
        # UI 回调函数
        self.ui_callback = None

    def set_callback(self, callback):
        """设置UI回调函数"""
        self.ui_callback = callback

    def get_watchlists(self):
        """获取用户的所有自选股分组名称"""
        ret, data = self.quote_ctx.get_user_security_group()
        if ret == RET_OK:
            # data is a pandas DataFrame
            return data['group_name'].tolist()
        else:
            print(f"获取自选股分组失败: {data}")
            return []

    def start(self, watchlist_name):
        """开始监控指定的自选股分组"""
        # 1. 获取分组内的股票代码
        ret, data = self.quote_ctx.get_user_security(group_name=watchlist_name)
        if ret != RET_OK:
            print(f"获取自选股失败: {data}")
            return
        
        # data is a pandas DataFrame, so we need to access the 'code' column directly
        codes = data['code'].tolist()
        print(f"开始监控自选股分组: {watchlist_name}, 股票列表: {codes}")

        # 2. 从本地数据库加载历史数据，初始化 CChan 对象
        for code in codes:
            try:
                # SQLiteAPI 需要实例化后才能使用
                sqlite_api = SQLiteAPI(code, k_type=KL_TYPE.K_DAY)
                kl_data = list(sqlite_api.get_kl_data())
                if not kl_data:
                    print(f"警告: 本地数据库中没有 {code} 的历史数据，跳过。")
                    continue
                # 获取时间范围
                begin_time = f"{kl_data[0].time.year}-{kl_data[0].time.month:02d}-{kl_data[0].time.day:02d}"
                end_time = f"{kl_data[-1].time.year}-{kl_data[-1].time.month:02d}-{kl_data[-1].time.day:02d}"
                # 确保配置中启用增量计算
                chan_config = CChanConfig(self.config['chan'])
                chan_config.trigger_step = True
                
                chan = CChan(
                    code=code,
                    begin_time=begin_time,
                    end_time=end_time,
                    data_src="custom:SQLiteAPI.SQLiteAPI",
                    lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M],
                    config=chan_config,
                    autype=AUTYPE.QFQ,
                )
                self.chan_objects[code] = chan
            except Exception as e:
                print(f"初始化 {code} 的 CChan 对象失败: {e}")
                continue

        # 3. 订阅实时K线 (30分钟和5分钟)
        sub_codes = list(self.chan_objects.keys())
        if not sub_codes:
            print("没有有效的股票可以订阅。")
            return
        
        ret, data = self.quote_ctx.subscribe(sub_codes, [SubType.K_30M, SubType.K_5M], is_first_push=True)
        if ret != RET_OK:
            print(f"订阅失败: {data}")
            return

        print(f"成功订阅 {len(sub_codes)} 只股票的30分钟和5分钟K线，开始监控...")


    def stop(self):
        """停止监控"""
        if self.chan_objects:
            codes = list(self.chan_objects.keys())
            self.quote_ctx.unsubscribe(codes, [SubType.K_30M, SubType.K_5M])
            self.chan_objects.clear()
        self.quote_ctx.close()
        print("监控已停止。")