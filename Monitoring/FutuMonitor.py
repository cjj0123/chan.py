"""
Futu 实时监控模块
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futu import *
import yaml
from DataAPI.SQLiteAPI import SQLiteAPI
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE

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
        
        # 初始化本地数据库接口
        self.sqlite_api = SQLiteAPI()
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
        
        codes = [stock['code'] for stock in data]
        print(f"开始监控自选股分组: {watchlist_name}, 股票列表: {codes}")

        # 2. 从本地数据库加载历史数据，初始化 CChan 对象
        for code in codes:
            try:
                df = self.sqlite_api.get_kl_data(code)
                if df.empty:
                    print(f"警告: 本地数据库中没有 {code} 的历史数据，跳过。")
                    continue
                # 将 DataFrame 转换为 chan.py 所需的格式
                # 这里需要根据实际情况调整，假设 DataFrame 包含 'date', 'open', 'high', 'low', 'close', 'volume'
                begin_time = df['date'].iloc[0].strftime('%Y-%m-%d')
                end_time = df['date'].iloc[-1].strftime('%Y-%m-%d')
                chan = CChan(
                    code=code,
                    begin_time=begin_time,
                    end_time=end_time,
                    data_src=DATA_SRC.CUSTOM,
                    custom_api=self.sqlite_api,
                    lv_list=[KL_TYPE.K_DAY],
                    config=CChanConfig(self.config['chan']),
                    autype=AUTYPE.QFQ,
                )
                self.chan_objects[code] = chan
            except Exception as e:
                print(f"初始化 {code} 的 CChan 对象失败: {e}")
                continue

        # 3. 订阅实时K线 (1分钟)
        sub_codes = list(self.chan_objects.keys())
        if not sub_codes:
            print("没有有效的股票可以订阅。")
            return
        
        ret, data = self.quote_ctx.subscribe(sub_codes, [SubType.K_1M], is_first_push=True)
        if ret != RET_OK:
            print(f"订阅失败: {data}")
            return

        # 4. 设置回调处理器
        self.quote_ctx.set_on_recv_rsp(self.on_recv_rsp)
        print(f"成功订阅 {len(sub_codes)} 只股票的1分钟K线，开始监控...")

    def on_recv_rsp(self, rsp_str):
        """处理富途推送的实时数据"""
        ret, data = parse(rsp_str)
        if ret != RET_OK:
            print(f"解析数据失败: {data}")
            return

        if data['type'] == 'KLine':
            # 处理K线数据
            kline_data = data['data']
            code = kline_data['code']
            if code not in self.chan_objects:
                return
            
            # 提取新的K线数据
            new_kl = {
                'time': kline_data['time_key'],
                'open': kline_data['open'],
                'high': kline_data['high'],
                'low': kline_data['low'],
                'close': kline_data['close'],
                'volume': kline_data['volume']
            }
            
            # 增量计算
            try:
                self.chan_objects[code].append_kl(new_kl)
                # 检查是否有新买卖点
                latest_bsp = self.chan_objects[code].get_latest_bsp(number=1)
                if latest_bsp and self.ui_callback:
                    # 这里可以添加更复杂的逻辑来判断是否是真正的新信号
                    self.ui_callback({
                        'code': code,
                        'signal': latest_bsp.type2str(),
                        'price': new_kl['close'],
                        'time': new_kl['time']
                    })
            except Exception as e:
                print(f"处理 {code} 的新K线时出错: {e}")

    def stop(self):
        """停止监控"""
        if self.chan_objects:
            codes = list(self.chan_objects.keys())
            self.quote_ctx.unsubscribe(codes, [SubType.K_1M])
            self.chan_objects.clear()
        self.quote_ctx.close()
        print("监控已停止。")