import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import sqlite3

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use('QtAgg', force=True)  # Use QtAgg backend which is compatible with PyQt6

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget,
    QGroupBox, QHBoxLayout, QPushButton, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QLabel, QLineEdit,
    QSplitter, QFrame, QMessageBox, QProgressBar, QDateTimeEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.pyplot as plt


class ChanPlotCanvas(FigureCanvas):
    """
    嵌入 PyQt 的 Matplotlib 画布

    用于在 GUI 中显示缠论分析图表，包括K线、笔、线段、中枢等。

    Args:
        parent: 父控件
        width: 图表宽度（英寸）
        height: 图表高度（英寸）
    """

    def __init__(self, parent=None, width=12, height=8):
        self.fig = Figure(figsize=(width, height), dpi=100)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumHeight(400)

    def clear(self):
        """清空画布内容"""
        self.fig.clear()
        self.draw()

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.PlotDriver import CPlotDriver

# 富途API相关
try:
    from futu import RET_OK
except ImportError:
    RET_OK = 0  # 如果没有安装futu，使用默认值

# 富途实时监控相关
from Monitoring.FutuMonitor import FutuMonitor

# akshare 相关
import akshare as ak
import os
import re
import yaml

def get_futu_stock_name(code):
    """
    从富途API获取单个股票的准确名称
    
    Args:
        code: str, 股票代码 (如 SH.600000)
    
    Returns:
        str: 股票名称，获取失败时返回原代码
    """
    try:
        from futu import OpenQuoteContext, RET_OK, Market
        import os
        
        # 从环境变量或配置文件获取富途API地址
        FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
        
        # 创建富途API连接
        quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
        
        # 获取股票基本信息
        ret, data = quote_ctx.get_stock_basicinfo(Market.HK, [code])
        if ret != RET_OK:
            # 尝试获取A股信息
            market = Market.SH if code.startswith('SH.') else Market.SZ if code.startswith('SZ.') else Market.HK
            ret, data = quote_ctx.get_stock_basicinfo(market, [code])
        
        quote_ctx.close()
        
        if ret == RET_OK and not data.empty:
            return data.iloc[0]['stock_name']
        else:
            return code
    except Exception as e:
        print(f"从富途获取股票名称失败 {code}: {e}")
        return code


        return code

def get_futu_watchlist_stocks():
    """
    从富途自选股列表获取股票代码
    
    Returns:
        pd.DataFrame: 包含 ['代码', '名称', '最新价', '涨跌幅'] 列的股票列表
                      获取失败时返回空 DataFrame
    """
    try:
        from Monitoring.FutuMonitor import FutuMonitor
        monitor = FutuMonitor()
        # 获取第一个自选股分组的股票
        watchlists = monitor.get_watchlists()
        if not watchlists:
            print("没有找到富途自选股分组")
            return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])
        
        # 使用第一个分组
        ret, data = monitor.quote_ctx.get_user_security(group_name=watchlists[0])
        monitor.quote_ctx.close()
        
        if ret != RET_OK:
            print(f"获取自选股失败: {data}")
            return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])
        
        # data is a pandas DataFrame, convert to our format
        result_df = pd.DataFrame({
            '代码': data['code'],
            '名称': data['name'],
            '最新价': [0.0] * len(data),  # 富途API返回的自选股数据可能不包含最新价
            '涨跌幅': [0.0] * len(data)   # 需要额外查询
        })
        
        return result_df[['代码', '名称', '最新价', '涨跌幅']]
    except Exception as e:
        print(f"从富途获取自选股列表失败: {e}")
        return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])

def get_tradable_stocks():
    """
    获取所有可交易的A股股票列表
    
    优先尝试从富途自选股列表获取，如果失败则回退到akshare API，
    如果都失败则使用测试股票列表
    
    Returns:
        pd.DataFrame: 包含 ['代码', '名称', '最新价', '涨跌幅'] 列的股票列表
                      获取失败时返回测试股票列表
    """
    # 首先尝试从富途自选股获取
    df = get_futu_watchlist_stocks()
    if not df.empty:
        return df
    
    # 如果富途获取失败，回退到akshare
    try:
        # 获取A股实时行情
        df = ak.stock_zh_a_spot_em()

        # 过滤条件
        # 1. 剔除ST股票（名称包含ST）
        df = df[~df['名称'].str.contains('ST', case=False, na=False)]

        # 2. 剔除科创板（688开头）
        df = df[~df['代码'].str.startswith('688')]

        # 3. 剔除北交所（8开头，以43、83、87开头的也是北交所）
        df = df[~df['代码'].str.startswith('8')]
        df = df[~df['代码'].str.startswith('43')]

        # 4. 剔除B股（200开头深圳B股，900开头上海B股）
        df = df[~df['代码'].str.startswith('200')]
        df = df[~df['代码'].str.startswith('900')]

        # 5. 剔除存托凭证CDR（920开头）
        df = df[~df['代码'].str.startswith('920')]

        # 6. 剔除停牌股票（成交量为0或涨跌幅为空）
        df = df[df['成交量'] > 0]

        # 7. 剔除新股（上市不足60天的，这里简化处理，只保留有数据的）
        df = df[df['最新价'] > 0]

        if not df.empty:
            return df[['代码', '名称', '最新价', '涨跌幅']].reset_index(drop=True)
            
    except Exception as e:
        print(f"获取股票列表失败: {e}")
    
    # 如果所有方法都失败，使用测试股票列表
    try:
        import yaml
        test_config_path = "Config/test_stocks.yaml"
        if os.path.exists(test_config_path):
            with open(test_config_path, 'r', encoding='utf-8') as f:
                test_config = yaml.safe_load(f)
                if test_config and 'test_stocks' in test_config:
                    test_stocks = test_config['test_stocks']
                    codes = [stock['code'] for stock in test_stocks]
                    names = [stock['name'] for stock in test_stocks]
                    return pd.DataFrame({
                        '代码': codes,
                        '名称': names,
                        '最新价': [0.0] * len(codes),
                        '涨跌幅': [0.0] * len(codes)
                    })
    except Exception as e:
        print(f"加载测试股票列表失败: {e}")
    
    # 最后的备选方案：返回默认的5只股票
    default_stocks = ['000001', '600000', '600519', '000858', '601318']
    return pd.DataFrame({
        '代码': default_stocks,
        '名称': ['平安银行', '浦发银行', '贵州茅台', '五粮液', '中国平安'],
        '最新价': [0.0] * len(default_stocks),
        '涨跌幅': [0.0] * len(default_stocks)
    })

def normalize_stock_code(code_input):
    """
    标准化股票代码输入
    
    支持的输入格式：
    - 完整格式: SH.600000, SZ.000001, HK.00700, US.AAPL
    - 纯数字: 600000, 000001, 00700
    - 带市场前缀的数字: 600000.SH, 000001.SZ
    
    Returns:
        str: 标准化后的股票代码 (SH.600000, SZ.000001, HK.00700, US.AAPL)
    """
    import re
    code = code_input.strip().upper()
    
    # 如果已经是完整格式，直接返回
    if re.match(r'^(SH|SZ|HK|US)\.\w+$', code):
        return code
    
    # 如果是带市场后缀的格式 (600000.SH)
    if re.match(r'^\d+\.(SH|SZ|HK|US)$', code):
        parts = code.split('.')
        return f"{parts[1]}.{parts[0]}"
    
    # 如果是纯数字，尝试推断市场
    if re.match(r'^\d+$', code):
        # 检查长度和前缀来推断市场
        if len(code) == 6:
            if code.startswith('6'):
                return f"SH.{code}"
            elif code.startswith('0') or code.startswith('3'):
                return f"SZ.{code}"
            else:
                # 可能是其他市场，先假设是SH
                return f"SH.{code}"
        elif len(code) == 5:
            # 港股通常是5位数字
            return f"HK.{code}"
        elif len(code) <= 4:
            # 美股通常是1-4个字母，但这里输入的是数字，可能是错误
            # 先假设是A股
            if code.startswith('6'):
                return f"SH.{code.zfill(6)}"
            else:
                return f"SZ.{code.zfill(6)}"
    
    # 如果是纯字母（可能是美股），添加US前缀
    if re.match(r'^[A-Z]+$', code):
        return f"US.{code}"
    
    # 如果无法识别，返回原输入（让后续处理报错）
    return code_input


class UpdateDatabaseThread(QThread):

    """
    更新本地数据库的后台线程
    
    在独立线程中下载股票数据并保存到SQLite数据库。
    
    Signals:
        progress: (int, int, str) 当前进度、总数、当前股票信息
        log_signal: (str) 日志消息
        finished: (bool, str) 完成信号，包含成功状态和消息
    """
    progress = pyqtSignal(int, int, str)
    log_signal = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, stock_codes, days, timeframes, start_date=None, end_date=None):
        """
        初始化数据库更新线程
        
        Args:
            stock_codes: list, 股票代码列表
            days: int, 获取多少天的历史数据
            timeframes: list, 时间级别列表
            start_date: str, 开始日期 (可选)
            end_date: str, 结束日期 (可选)
        """
        super().__init__()
        self.stock_codes = stock_codes
        self.days = days
        self.timeframes = timeframes
        self.start_date = start_date
        self.end_date = end_date
        self.is_running = True
        
    def stop(self):
        """停止数据库更新"""
        self.is_running = False
        self.log_signal.emit("正在停止数据库更新...")
        
    def run(self):
        """执行数据库更新任务"""
        try:
            if not self.stock_codes:
                self.finished.emit(False, "股票列表为空")
                return
                
            total = len(self.stock_codes)
            
            # 导入必要的模块
            from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
            from Trade.db_util import CChanDB
            
            def log_callback(msg):
                if self.is_running:
                    self.log_signal.emit(msg)
                    
            # 执行下载任务
            if self.is_running:
                def stop_check():
                    return not self.is_running
                
                download_and_save_all_stocks_multi_timeframe(
                    self.stock_codes,
                    days=self.days,
                    timeframes=self.timeframes,
                    log_callback=log_callback,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    stop_check=stop_check
                )
                
                # 统计结果
                if self.is_running:
                    db = CChanDB()
                    downloaded_codes = db.execute_query("SELECT DISTINCT code FROM kline_day")['code'].tolist()
                    success_count = len(downloaded_codes)
                    
                    # 统计各市场数据量
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
                    
                    # 显示失败的股票（如果有的话）
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


class ScanThread(QThread):
    """
    批量扫描股票的后台线程

    在独立线程中遍历股票列表，对每只股票进行缠论分析，
    检测最近3天内是否出现买点。

    Signals:
        progress: (int, int, str) 当前进度、总数、当前股票信息
        found_signal: (dict) 发现买点时发出，包含股票详情和 CChan 对象
        finished: (int, int) 扫描完成，返回成功数和失败数
        log_signal: (str) 日志消息
    """
    progress = pyqtSignal(int, int, str)
    found_signal = pyqtSignal(dict)
    finished = pyqtSignal(int, int)
    log_signal = pyqtSignal(str)

    def __init__(self, stock_list, config, days=365, kl_type=KL_TYPE.K_DAY):
        """
        初始化扫描线程

        Args:
            stock_list: pd.DataFrame, 待扫描的股票列表
            config: CChanConfig, 缠论配置
            days: int, 获取多少天的历史数据，默认365天
            kl_type: KL_TYPE, 时间级别，默认为日线
        """
        super().__init__()
        self.stock_list = stock_list
        self.config = config
        self.days = days
        self.kl_type = kl_type
        self.is_running = True

    def stop(self):
        """停止扫描，设置标志位让 run() 循环退出"""
        self.is_running = False

    def run(self):
        """
        线程主函数，遍历股票列表进行缠论分析

        扫描逻辑:
            1. 跳过无K线数据的股票
            2. 跳过停牌超过15天的股票
            3. 检测最近3天内是否出现买点
            4. 发现买点时通过 found_signal 发出通知
        """
        begin_time = (datetime.now() - timedelta(days=self.days)).strftime("%Y-%m-%d")
        end_time = datetime.now().strftime("%Y-%m-%d")
        total = len(self.stock_list)
        success_count = 0
        fail_count = 0

        for idx, row in self.stock_list.iterrows():
            if not self.is_running:
                break

            code = row['代码']
            name = row['名称']
            
            # 从Futu获取准确的股票名称
            accurate_name = get_futu_stock_name(code)
            if accurate_name != code:  # 如果获取到了准确名称，则使用它
                name = accurate_name
            
            self.progress.emit(idx + 1, total, f"{code} {name}")
            self.log_signal.emit(f"🔍 扫描 {code} {name}...")

            try:
                chan = CChan(
                    code=code,
                    begin_time=begin_time,
                    end_time=end_time,
                    data_src=DATA_SRC.FUTU,
                    lv_list=[self.kl_type],
                    config=self.config,
                    autype=AUTYPE.QFQ,
                )

                # 检查最近15天是否有数据
                if len(chan[0]) == 0:
                    fail_count += 1
                    self.log_signal.emit(f"⏭️ {code} {name}: 无K线数据")
                    continue
                last_klu = chan[0][-1][-1]
                last_time = last_klu.time
                last_date = datetime(last_time.year, last_time.month, last_time.day)
                if (datetime.now() - last_date).days > 15:
                    fail_count += 1
                    self.log_signal.emit(f"⏸️ {code} {name}: 停牌超过15天")
                    continue

                success_count += 1

                # 检查是否有买点或卖点（只找最近3天内出现的买卖点）
                bsp_list = chan.get_latest_bsp(number=0)
                cutoff_date = datetime.now() - timedelta(days=3)
                
                # 分别获取买点和卖点
                buy_points = [
                    bsp for bsp in bsp_list
                    if bsp.is_buy and datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day) >= cutoff_date
                ]
                sell_points = [
                    bsp for bsp in bsp_list
                    if not bsp.is_buy and datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day) >= cutoff_date
                ]

                # 优先处理买点，如果没有买点再处理卖点
                if buy_points:
                    # 获取最近的买点
                    latest_buy = buy_points[0]
                    self.log_signal.emit(f"✅ {code} {name}: 发现买点 {latest_buy.type2str()}")
                    self.found_signal.emit({
                        'code': code,
                        'name': name,
                        'price': row['最新价'],
                        'change': row['涨跌幅'],
                        'bsp_type': f"买点{latest_buy.type2str()}",
                        'bsp_time': str(latest_buy.klu.time),
                        'bsp_direction': 'buy',
                        'chan': chan,
                    })
                elif sell_points:
                    # 获取最近的卖点
                    latest_sell = sell_points[0]
                    self.log_signal.emit(f"🔴 {code} {name}: 发现卖点 {latest_sell.type2str()}")
                    self.found_signal.emit({
                        'code': code,
                        'name': name,
                        'price': row['最新价'],
                        'change': row['涨跌幅'],
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
                else:
                    self.log_signal.emit(f"❌ {code} {name}: {error_msg[:50]}")
                continue

        self.finished.emit(success_count, fail_count)


class OfflineScanThread(QThread):
    """
    离线批量扫描股票的后台线程
    
    在独立线程中遍历股票列表，从SQLite数据库读取K线数据进行缠论分析，
    检测最近3天内是否出现买点。
    
    Signals:
        progress: (int, int, str) 当前进度、总数、当前股票信息
        found_signal: (dict) 发现买点时发出，包含股票详情和 CChan 对象
        finished: (int, int) 扫描完成，返回成功数和失败数
        log_signal: (str) 日志消息
    """
    progress = pyqtSignal(int, int, str)
    found_signal = pyqtSignal(dict)
    finished = pyqtSignal(int, int)
    log_signal = pyqtSignal(str)
    
    def __init__(self, stock_list, config, days=365, kl_type=KL_TYPE.K_DAY):
        """
        初始化离线扫描线程
        
        Args:
            stock_list: pd.DataFrame, 待扫描的股票列表
            config: CChanConfig, 缠论配置
            days: int, 获取多少天的历史数据，默认365天
            kl_type: KL_TYPE, 时间级别，默认为日线
        """
        super().__init__()
        self.stock_list = stock_list
        self.config = config
        self.days = days
        self.kl_type = kl_type
        self.is_running = True
        
    def stop(self):
        """停止扫描，设置标志位让 run() 循环退出"""
        self.is_running = False
        
    def run(self):
        """
        线程主函数，遍历股票列表进行缠论分析
        
        扫描逻辑:
            1. 跳过无K线数据的股票
            2. 跳过停牌超过15天的股票
            3. 检测最近3天内是否出现买点
            4. 发现买点时通过 found_signal 发出通知
        """
        begin_time = (datetime.now() - timedelta(days=self.days)).strftime("%Y-%m-%d")
        end_time = datetime.now().strftime("%Y-%m-%d")
        total = len(self.stock_list)
        success_count = 0
        fail_count = 0
        
        for idx, row in self.stock_list.iterrows():
            if not self.is_running:
                break
                
            code = row['代码']
            name = row['名称']
            
            # 从Futu获取准确的股票名称
            accurate_name = get_futu_stock_name(code)
            if accurate_name != code:  # 如果获取到了准确名称，则使用它
                name = accurate_name
            
            self.progress.emit(idx + 1, total, f"{code} {name}")
            self.log_signal.emit(f"🔍 扫描 {code} {name}...")

            try:
                chan = CChan(
                    code=code,
                    begin_time=begin_time,
                    end_time=end_time,
                    data_src="custom:SQLiteAPI.SQLiteAPI",  # 使用自定义数据源（SQLite）
                    lv_list=[self.kl_type],
                    config=self.config,
                    autype=AUTYPE.QFQ,
                )
                
                # 检查最近15天是否有数据
                if len(chan[0]) == 0 or len(chan[0][-1]) == 0:
                    fail_count += 1
                    self.log_signal.emit(f"⏭️ {code} {name}: 无K线数据")
                    continue
                last_klu = chan[0][-1][-1]
                last_time = last_klu.time
                last_date = datetime(last_time.year, last_time.month, last_time.day)
                if (datetime.now() - last_date).days > 15:
                    fail_count += 1
                    self.log_signal.emit(f"⏸️ {code} {name}: 停牌超过15天")
                    continue
                    
                success_count += 1
                
                # 检查是否有买点或卖点（只找最近3天内出现的买卖点）
                bsp_list = chan.get_latest_bsp(number=0)
                cutoff_date = datetime.now() - timedelta(days=3)
                
                # 分别获取买点和卖点
                buy_points = [
                    bsp for bsp in bsp_list
                    if bsp.is_buy and datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day) >= cutoff_date
                ]
                sell_points = [
                    bsp for bsp in bsp_list
                    if not bsp.is_buy and datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day) >= cutoff_date
                ]

                # 优先处理买点，如果没有买点再处理卖点
                if buy_points:
                    # 获取最近的买点
                    latest_buy = buy_points[0]
                    self.log_signal.emit(f"✅ {code} {name}: 发现买点 {latest_buy.type2str()}")
                    self.found_signal.emit({
                        'code': code,
                        'name': name,
                        'price': row['最新价'],
                        'change': row['涨跌幅'],
                        'bsp_type': f"买点{latest_buy.type2str()}",
                        'bsp_time': str(latest_buy.klu.time),
                        'bsp_direction': 'buy',
                        'chan': chan,
                    })
                elif sell_points:
                    # 获取最近的卖点
                    latest_sell = sell_points[0]
                    self.log_signal.emit(f"🔴 {code} {name}: 发现卖点 {latest_sell.type2str()}")
                    self.found_signal.emit({
                        'code': code,
                        'name': name,
                        'price': row['最新价'],
                        'change': row['涨跌幅'],
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
                elif "custom" in error_msg.lower():
                    self.log_signal.emit(f"❌ {code} {name}: 数据源错误，请检查数据库")
                elif "Broken pipe" in error_msg or "Errno 32" in error_msg:
                    self.log_signal.emit(f"❌ {code} {name}: 数据处理中断，可能是分钟级别数据格式问题")
                else:
                    self.log_signal.emit(f"❌ {code} {name}: {error_msg[:50]}")
                continue
                
        self.finished.emit(success_count, fail_count)


class SingleAnalysisThread(QThread):
    """
    单只股票分析的后台线程
    
    在独立线程中对单只股票进行缠论分析并生成图表。
    
    Signals:
        finished: (CChan) 分析完成，返回CChan对象
        error: (str) 错误信息
        log_signal: (str) 日志消息
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, code, config, kl_type, days=365, data_sources=None):
        """
        初始化单只股票分析线程
        
        Args:
            code: str, 股票代码
            config: CChanConfig, 缠论配置
            kl_type: KL_TYPE, 时间级别
            days: int, 获取多少天的历史数据，默认365天
            data_sources: list, 数据源优先级列表，默认为[FUTU优先]
        """
        super().__init__()
        self.code = code
        self.config = config
        self.kl_type = kl_type
        self.days = days
        self.data_sources = data_sources or [DATA_SRC.FUTU, "custom:SQLiteAPI.SQLiteAPI"]

    def run(self):
       """执行单只股票缠论分析"""
       try:
           begin_time = (datetime.now() - timedelta(days=self.days)).strftime("%Y-%m-%d")
           end_time = datetime.now().strftime("%Y-%m-%d")
           
           self.log_signal.emit(f"🔍 开始分析 {self.code}...")
           
           # 尝试使用指定的数据源，按优先级顺序
           chan = None
           
           for data_src in self.data_sources:
               try:
                   self.log_signal.emit(f"尝试使用数据源: {data_src}")
                   chan = CChan(
                       code=self.code,
                       begin_time=begin_time,
                       end_time=end_time,
                       data_src=data_src,
                       lv_list=[self.kl_type],
                       config=self.config,
                       autype=AUTYPE.QFQ,
                   )
                   
                   # 检查是否有足够的数据进行分析
                   if len(chan.lv_list) > 0:
                       first_kl_type = chan.lv_list[0]
                       first_kl_data = chan[first_kl_type]
                       if len(first_kl_data) > 0:
                           break  # 找到有数据的数据源，跳出循环
               except Exception as e:
                   self.log_signal.emit(f"数据源 {data_src} 失败: {str(e)}")
                   continue
           
           if chan is None or len(chan.lv_list) == 0:
               raise Exception(f"股票 {self.code} 没有指定的时间级别数据")
           
           # 检查第一个时间级别的K线数据是否为空
           first_kl_type = chan.lv_list[0]
           first_kl_data = chan[first_kl_type]
           if len(first_kl_data) == 0:
               raise Exception(f"股票 {self.code} 没有足够的K线数据进行分析")
           
           # 触发缠论各层级的计算
           for lv in chan.lv_list:
               _ = list(chan[lv])  # 访问数据以确保加载
           
           # 确保笔、线段、中枢等结构被计算
           # 访问这些属性会触发内部计算
           try:
               if hasattr(chan, '__getitem__'):
                   # 访问第一个时间级别的数据以触发计算
                   if len(chan.lv_list) > 0:
                       first_lv = chan.lv_list[0]
                       _ = chan[first_lv]
               
               # 尝试访问笔、线段、中枢列表以触发计算
               if hasattr(chan, 'bi_list'):
                   _ = list(chan.bi_list)
               if hasattr(chan, 'seg_list'):
                   _ = list(chan.seg_list)
               if hasattr(chan, 'zs_list'):
                   _ = list(chan.zs_list)
           except Exception as calc_error:
               self.log_signal.emit(f"⚠️ 计算缠论结构时出现: {str(calc_error)}")
           
           self.log_signal.emit(f"✅ {self.code} 分析完成，使用数据源: {chan.data_src}")
           self.finished.emit(chan)
       except Exception as e:
           self.error.emit(str(e))


class TraderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("缠论交易助手 V2")
        self.setGeometry(100, 100, 1600, 900)

        # --- Main Layout ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # --- Tab Widget ---
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        # --- Create Tabs ---
        self.create_scanner_tab()
        self.create_analysis_tab()
        self.create_settings_tab()

        # --- Initialize threads ---
        self.update_db_thread = None
        self.scan_thread = None
        self.analysis_thread = None
        
        # 确保按钮在界面显示后是可见的
        self.ensure_buttons_visible()
        
        # 启动时不显示数据库统计信息，以提高启动速度
        # 数据库统计将在用户点击"更新本地数据库"时显示
        
    def ensure_buttons_visible(self):
        """确保关键按钮是可见的"""
        if hasattr(self, 'update_db_btn'):
            self.update_db_btn.setVisible(True)
        if hasattr(self, 'start_scan_btn'):
            self.start_scan_btn.setVisible(True)
        if hasattr(self, 'load_chart_btn'):
            self.load_chart_btn.setVisible(True)

    def create_scanner_tab(self):
        """创建扫描器选项卡"""
        self.scanner_tab = QWidget()
        self.tabs.addTab(self.scanner_tab, "📈 扫描器")
        layout = QVBoxLayout(self.scanner_tab)

        # --- 1. 数据操作区 ---
        data_group = QGroupBox("1. 数据操作")
        data_layout = QVBoxLayout()  # 改为垂直布局以确保内容正确显示
        
        # 第一行：更新数据库按钮和日期选择
        top_row_layout = QHBoxLayout()
        self.update_db_btn = QPushButton("更新本地数据库")
        self.update_db_btn.clicked.connect(self.on_update_db_clicked)
        self.update_db_btn.setVisible(True)  # 确保按钮可见
        top_row_layout.addWidget(self.update_db_btn)
        
        # 添加日期范围选择
        top_row_layout.addWidget(QLabel("开始日期:"))
        self.start_date_input = QDateTimeEdit()
        self.start_date_input.setCalendarPopup(True)
        self.start_date_input.setDate((datetime.now() - timedelta(days=30)).date())
        top_row_layout.addWidget(self.start_date_input)
        
        top_row_layout.addWidget(QLabel("结束日期:"))
        self.end_date_input = QDateTimeEdit()
        self.end_date_input.setCalendarPopup(True)
        self.end_date_input.setDate(datetime.now().date())
        top_row_layout.addWidget(self.end_date_input)
        
        self.last_update_label = QLabel("上次更新: 未知")
        top_row_layout.addWidget(self.last_update_label)
        top_row_layout.addStretch()
        
        data_layout.addLayout(top_row_layout)
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        # --- 2. 扫描配置区 ---
        scan_group = QGroupBox("2. 扫描配置")
        scan_layout = QVBoxLayout()  # 改为垂直布局以确保内容正确显示
        
        # 扫描配置行
        config_row_layout = QHBoxLayout()
        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItems(["日线", "30分钟", "5分钟", "1分钟"])
        config_row_layout.addWidget(QLabel("模式:"))
        config_row_layout.addWidget(self.scan_mode_combo)
        
        # 添加天数输入
        config_row_layout.addWidget(QLabel("天数:"))
        self.days_input = QLineEdit()
        self.days_input.setPlaceholderText("30")
        self.days_input.setText("30")  # 默认值
        self.days_input.setMaximumWidth(60)
        config_row_layout.addWidget(self.days_input)
        
        # 添加自选股分组下拉框
        config_row_layout.addWidget(QLabel("自选股分组:"))
        self.watchlist_combo = QComboBox()
        # 初始化时先添加一个加载项
        self.watchlist_combo.addItem("加载中...")
        config_row_layout.addWidget(self.watchlist_combo)
        
        # 添加刷新按钮
        self.refresh_watchlist_btn = QPushButton("刷新分组")
        self.refresh_watchlist_btn.clicked.connect(self.load_futu_watchlists)
        config_row_layout.addWidget(self.refresh_watchlist_btn)
        
        config_row_layout.addStretch()
        
        # 初始化时加载富途自选股分组
        self.load_futu_watchlists()
        
        # 开始扫描按钮行
        button_row_layout = QHBoxLayout()
        self.start_scan_btn = QPushButton("开始扫描")
        self.start_scan_btn.clicked.connect(self.on_start_scan_clicked)
        self.start_scan_btn.setVisible(True)  # 确保按钮可见
        button_row_layout.addWidget(self.start_scan_btn)
        
        # 添加进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        button_row_layout.addWidget(self.progress_bar)
        button_row_layout.addStretch()
        
        scan_layout.addLayout(config_row_layout)
        scan_layout.addLayout(button_row_layout)
        scan_group.setLayout(scan_layout)
        layout.addWidget(scan_group)

        # --- 3. 结果列表区 ---
        result_group = QGroupBox("3. 扫描结果")
        result_layout = QVBoxLayout()
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels(["代码", "名称", "信号类型", "评分", "时间", "API"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        result_layout.addWidget(self.result_table)
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)

        # --- 4. 日志输出区 ---
        log_group = QGroupBox("4. 操作日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        layout.addStretch()

    def create_analysis_tab(self):
        """创建图表分析选项卡"""
        self.analysis_tab = QWidget()
        self.tabs.addTab(self.analysis_tab, "📊 图表分析")
        layout = QVBoxLayout(self.analysis_tab)

        # --- 手动分析区 ---
        manual_group = QGroupBox("手动分析")
        manual_layout = QHBoxLayout()
        
        # 股票代码输入
        self.stock_code_input = QLineEdit()
        self.stock_code_input.setPlaceholderText("输入股票代码，例如: 600000 或 SH.600000")
        manual_layout.addWidget(self.stock_code_input)
        
        # 数据源选择下拉框
        manual_layout.addWidget(QLabel("数据源:"))
        self.data_source_combo = QComboBox()
        self.data_source_combo.addItems(["Futu优先", "SQLite数据库"])  # 添加数据源选项
        manual_layout.addWidget(self.data_source_combo)
        
        # 时间级别选择下拉框
        manual_layout.addWidget(QLabel("时间级别:"))
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(["日线", "30分钟", "5分钟", "1分钟"])
        manual_layout.addWidget(self.timeframe_combo)
        
        # 加载图表按钮
        self.load_chart_btn = QPushButton("加载图表")
        self.load_chart_btn.clicked.connect(self.on_load_chart_clicked)
        self.load_chart_btn.setVisible(True)  # 确保按钮可见
        manual_layout.addWidget(self.load_chart_btn)
        manual_layout.addStretch()
        manual_group.setLayout(manual_layout)
        layout.addWidget(manual_group)

        # --- 图表和详情区 (使用分割器) ---
        chart_detail_splitter = QSplitter(Qt.Orientation.Horizontal)

        # -- 图表展示区 --
        self.chart_frame = QFrame()
        self.chart_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        chart_layout = QVBoxLayout(self.chart_frame)
        self.canvas = ChanPlotCanvas(self.chart_frame, width=10, height=6)
        self.toolbar = NavigationToolbar(self.canvas, self.chart_frame)

        chart_layout.addWidget(self.toolbar)
        chart_layout.addWidget(self.canvas)

        # -- 分析详情区 --
        self.analysis_detail_text = QTextEdit()
        self.analysis_detail_text.setReadOnly(True)
        self.analysis_detail_text.setPlaceholderText("视觉评分的详细理由将显示在此处...")

        chart_detail_splitter.addWidget(self.chart_frame)
        chart_detail_splitter.addWidget(self.analysis_detail_text)
        chart_detail_splitter.setSizes([800, 300])

        layout.addWidget(chart_detail_splitter)

    def create_settings_tab(self):
        """创建设置与自动化选项卡"""
        self.settings_tab = QWidget()
        self.tabs.addTab(self.settings_tab, "⚙️ 设置 & 自动化")
        layout = QVBoxLayout(self.settings_tab)

        # --- 基础设置 ---
        base_settings_group = QGroupBox("基础设置")
        base_settings_layout = QVBoxLayout()
        self.bi_strict_cb = QCheckBox("笔严格模式")
        self.bi_strict_cb.setChecked(True)
        base_settings_layout.addWidget(self.bi_strict_cb)
        self.data_source_label = QLabel("数据源: SQLite (离线)")
        base_settings_layout.addWidget(self.data_source_label)
        base_settings_group.setLayout(base_settings_layout)
        layout.addWidget(base_settings_group)

        # --- 自动化模块 ---
        auto_group = QGroupBox("自动化模块")
        auto_layout = QVBoxLayout()
        self.hk_auto_trading_label = QLabel("港股自动交易: [待实现]")
        self.futu_monitor_label = QLabel("Futu 实时监控: [待实现]")
        auto_layout.addWidget(self.hk_auto_trading_label)
        auto_layout.addWidget(self.futu_monitor_label)
        auto_group.setLayout(auto_layout)
        layout.addWidget(auto_group)

        layout.addStretch()

    def get_chan_config(self):
        """获取缠论配置"""
        config = CChanConfig()
        config.bNewStyle = True  # 新笔模式
        config.bi_strict = self.bi_strict_cb.isChecked()  # 笔严格模式
        return config

    def get_timeframe_kl_type(self):
        """根据扫描配置的时间级别下拉框获取对应的KL_TYPE"""
        timeframe_map = {
            "日线": KL_TYPE.K_DAY,
            "30分钟": KL_TYPE.K_30M,
            "5分钟": KL_TYPE.K_5M,
            "1分钟": KL_TYPE.K_1M,
        }
        selected_timeframe = self.scan_mode_combo.currentText()
        return timeframe_map.get(selected_timeframe, KL_TYPE.K_DAY)

    def get_analysis_timeframe_kl_type(self):
        """根据分析标签页的时间级别下拉框获取对应的KL_TYPE"""
        timeframe_map = {
            "日线": KL_TYPE.K_DAY,
            "30分钟": KL_TYPE.K_30M,
            "5分钟": KL_TYPE.K_5M,
            "1分钟": KL_TYPE.K_1M,
        }
        selected_timeframe = self.timeframe_combo.currentText()
        return timeframe_map.get(selected_timeframe, KL_TYPE.K_DAY)

    def on_update_db_clicked(self):
        """处理更新数据库按钮点击"""
        self.log_text.append("🔄 开始更新本地数据库...")
        
        # 获取时间级别
        selected_timeframe = self.scan_mode_combo.currentText()
        # 不管选择哪个时间级别，都下载所有时间级别的数据
        timeframes_to_download = ['day', '30m', '5m', '1m']
        
        # 获取用户输入的天数
        try:
            days_text = self.days_input.text().strip()
            if days_text:
                days = int(days_text)
                if days <= 0:
                    days = 30  # 如果输入不合法，默认为30天
            else:
                days = 30  # 如果没有输入，默认为30天
        except ValueError:
            days = 30  # 如果转换失败，默认为30天
            self.log_text.append(f"⚠️ 天数输入格式不正确，使用默认值30天")
        
        # 获取日期范围
        start_date = self.start_date_input.date().toString("yyyy-MM-dd")
        end_date = self.end_date_input.date().toString("yyyy-MM-dd")
        
        # 从本地获取股票列表，根据自选股分组选择
        try:
            from DataAPI.SQLiteAPI import CChanDB
            db = CChanDB()
            
            # 显示数据库当前统计信息
            self.display_db_stats(db)
            
            # 获取自选股分组选择
            selected_watchlist = self.watchlist_combo.currentText()
            
            # 根据选择的分组构建查询条件
            if selected_watchlist not in ["沪深A股", "港股通", "全部"] and selected_watchlist != "加载中...":
                # 如果选择的是自定义分组，则尝试从富途API获取具体的自选股列表
                try:
                    from futu import OpenQuoteContext, RET_OK
                    import os
                    FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
                    
                    quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
                    ret, data = quote_ctx.get_user_security(selected_watchlist)
                    
                    if ret == RET_OK and not data.empty:
                        stock_codes = data['code'].tolist()
                        if stock_codes:
                            # 构建查询条件，只获取自选股的数据
                            code_placeholders = ','.join([f"'{code}'" for code in stock_codes])
                            stock_query = f"SELECT DISTINCT code FROM kline_day WHERE code IN ({code_placeholders})"
                        else:
                            self.log_text.append(f"⚠️ 自选股分组 '{selected_watchlist}' 中没有股票")
                            quote_ctx.close()
                            return
                    else:
                        self.log_text.append(f"⚠️ 获取自选股列表失败: {data}")
                        # 如果富途API获取失败，回退到查询所有股票
                        stock_query = "SELECT DISTINCT code FROM kline_day"
                        
                    quote_ctx.close()
                except Exception as e:
                    self.log_text.append(f"⚠️ 获取富途自选股时出错: {str(e)}")
                    # 出错时回退到查询所有股票
                    stock_query = "SELECT DISTINCT code FROM kline_day"
            else:
                # 如果选择的是预设分组，则使用相应的筛选条件
                stock_query = "SELECT DISTINCT code FROM kline_day"
                
                # 根据选择的分组应用不同的筛选条件
                if selected_watchlist == "沪深A股":
                    stock_query += " WHERE code LIKE 'SH.%' OR code LIKE 'SZ.%'"
                elif selected_watchlist == "港股通":
                    stock_query += " WHERE code LIKE 'HK.%'"
                elif selected_watchlist == "全部":
                    # 查询所有股票，不做额外筛选
                    pass
                # 对于其他情况，查询所有股票
            
            # 获取股票列表
            try:
                stock_df = db.execute_query(stock_query)
                stock_codes = stock_df['code'].tolist() if not stock_df.empty else []
            except Exception as db_error:
                self.log_text.append(f"⚠️ 读取数据库时出现问题: {str(db_error)}")
                stock_codes = []
            
            if not stock_codes:
                # 如果数据库中没有数据，尝试从其他地方获取一些示例股票
                # 从现有的股票列表文件中获取
                try:
                    import os
                    if os.path.exists("../futu_a_stocks.txt"):
                        with open("../futu_a_stocks.txt", "r", encoding="utf-8") as f:
                            stock_codes = [line.strip() for line in f.readlines() if line.strip()]
                        stock_codes = stock_codes[:50]  # 限制数量
                    else:
                        # 使用默认的示例股票
                        stock_codes = ["SH.000001", "SZ.000002", "SH.600000", "SZ.000001"]
                except:
                    stock_codes = ["SH.000001", "SZ.000002", "SH.600000", "SZ.000001"]
            
            self.log_text.append(f"📊 准备下载 {len(stock_codes)} 只股票的 {selected_timeframe} 数据...")
            self.log_text.append(f"📅 日期范围: {start_date} 到 {end_date}")
            
            # 启动QThread下载数据
            self.update_db_thread = UpdateDatabaseThread(
                stock_codes,
                days,  # 使用用户输入的天数
                timeframes_to_download,
                start_date,  # 使用用户选择的开始日期
                end_date    # 使用用户选择的结束日期
            )
            self.update_db_thread.log_signal.connect(self.on_log_message)
            self.update_db_thread.finished.connect(self.on_update_database_finished)
            self.update_db_thread.start()
            
        except Exception as e:
            self.log_text.append(f"❌ 获取股票列表失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")
    
    def display_db_stats(self, db):
        """显示数据库统计信息"""
        try:
            import os
            from datetime import datetime
            
            # 获取数据库文件大小
            db_size = 0
            if os.path.exists(db.db_path):
                db_size = os.path.getsize(db.db_path)
                # 转换为MB
                db_size_mb = round(db_size / (1024 * 1024), 2)
            
            # 使用单个连接执行所有查询以提高效率
            with sqlite3.connect(db.db_path) as conn:
                # 查询不同时间级别的统计数据
                day_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_day", conn).iloc[0]['count']
                day_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_day", conn).iloc[0]['count']
                day_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_day", conn).iloc[0]['max_date']
                
                m30_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_30m", conn).iloc[0]['count']
                m30_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_30m", conn).iloc[0]['count']
                m30_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_30m", conn).iloc[0]['max_date']
                
                m5_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_5m", conn).iloc[0]['count']
                m5_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_5m", conn).iloc[0]['count']
                m5_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_5m", conn).iloc[0]['max_date']
                
                m1_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_1m", conn).iloc[0]['count']
                m1_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_1m", conn).iloc[0]['count']
                m1_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_1m", conn).iloc[0]['max_date']
            
            # 显示统计信息
            self.log_text.append("📈 数据库当前统计:")
            self.log_text.append(f"  数据库大小: {db_size_mb} MB")
            self.log_text.append(f"  日线数据: {day_stock_count} 只股票, {day_count} 条记录, 最近更新: {day_max_date or '无数据'}")
            self.log_text.append(f"  30分钟线数据: {m30_stock_count} 只股票, {m30_count} 条记录, 最近更新: {m30_max_date or '无数据'}")
            self.log_text.append(f"  5分钟线数据: {m5_stock_count} 只股票, {m5_count} 条记录, 最近更新: {m5_max_date or '无数据'}")
            self.log_text.append(f"  1分钟线数据: {m1_stock_count} 只股票, {m1_count} 条记录, 最近更新: {m1_max_date or '无数据'}")
            
        except Exception as e:
            self.log_text.append(f"⚠️ 获取数据库统计信息失败: {str(e)}")

    def on_start_scan_clicked(self):
        """处理开始扫描按钮点击"""
        self.log_text.append("🔍 开始执行扫描...")
        
        try:
            # 获取配置
            config = self.get_chan_config()
            kl_type = self.get_timeframe_kl_type()
            
            # 从数据库获取股票列表
            from DataAPI.SQLiteAPI import CChanDB
            db = CChanDB()
            
            # 根据自选股分组选择获取股票列表
            selected_watchlist = self.watchlist_combo.currentText()
            
            # 根据选择的分组构建查询条件
            if selected_watchlist not in ["沪深A股", "港股通", "全部"] and selected_watchlist != "加载中...":
                # 如果选择的是自定义分组，则尝试从富途API获取具体的自选股列表
                try:
                    from futu import OpenQuoteContext, RET_OK
                    import os
                    FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
                    
                    quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
                    ret, data = quote_ctx.get_user_security(selected_watchlist)
                    
                    if ret == RET_OK and not data.empty:
                        codes = data['code'].tolist()
                        if codes:
                            # 构建查询条件，只获取自选股的数据
                            code_placeholders = ','.join([f"'{code}'" for code in codes])
                            stock_query = f"SELECT DISTINCT code FROM kline_day WHERE code IN ({code_placeholders})"
                        else:
                            self.log_text.append(f"⚠️ 自选股分组 '{selected_watchlist}' 中没有股票")
                            quote_ctx.close()
                            return
                    else:
                        self.log_text.append(f"⚠️ 获取自选股列表失败: {data}")
                        # 如果富途API获取失败，回退到查询所有股票
                        stock_query = "SELECT DISTINCT code FROM kline_day"
                        
                    quote_ctx.close()
                except Exception as e:
                    self.log_text.append(f"⚠️ 获取富途自选股时出错: {str(e)}")
                    # 出错时回退到查询所有股票
                    stock_query = "SELECT DISTINCT code FROM kline_day"
            else:
                # 如果选择的是预设分组，则使用相应的筛选条件
                stock_query = "SELECT DISTINCT code FROM kline_day"
                
                # 根据选择的分组应用不同的筛选条件
                if selected_watchlist == "沪深A股":
                    stock_query += " WHERE code LIKE 'SH.%' OR code LIKE 'SZ.%'"
                elif selected_watchlist == "港股通":
                    stock_query += " WHERE code LIKE 'HK.%'"
                elif selected_watchlist == "全部":
                    # 查询所有股票，不做额外筛选
                    pass
                # 对于其他情况，查询所有股票
            
            try:
                stock_df = db.execute_query(stock_query)
            except Exception as db_error:
                self.log_text.append(f"⚠️ 读取数据库时出现问题: {str(db_error)}")
                stock_df = pd.DataFrame(columns=['code'])  # 创建空的DataFrame
            
            if stock_df.empty or stock_df['code'].empty:
                self.log_text.append("⚠️ 数据库中没有股票数据，尝试从富途或akshare获取实时股票列表...")
                # 回退到在线模式，使用 get_tradable_stocks() 获取股票列表
                stock_list = get_tradable_stocks()
                if stock_list.empty:
                    self.log_text.append("❌ 无法获取股票列表，请检查网络连接或富途API配置")
                    return
                else:
                    self.log_text.append(f"✅ 成功获取 {len(stock_list)} 只可交易股票，使用在线模式进行扫描...")
                    # 使用在线扫描线程而不是离线扫描线程
                    scan_thread_class = ScanThread
            else:
                # 添加模拟的股票名称和价格信息
                stock_list = pd.DataFrame({
                    '代码': stock_df['code'].tolist(),
                    '名称': [f'股票_{code.split(".")[-1]}' for code in stock_df['code'].tolist()],
                    '最新价': [10.0] * len(stock_df),
                    '涨跌幅': [0.0] * len(stock_df)
                })
                scan_thread_class = OfflineScanThread
            
            self.log_text.append(f"📊 准备扫描 {len(stock_list)} 只股票 (来自: {selected_watchlist})...")
            
            # 获取用户输入的天数
            try:
                days_text = self.days_input.text().strip()
                if days_text:
                    days = int(days_text)
                    if days <= 0:
                        days = 30  # 如果输入不合法，默认为30天
                else:
                    days = 30  # 如果没有输入，默认为30天
            except ValueError:
                days = 30  # 如果转换失败，默认为30天
                self.log_text.append(f"⚠️ 天数输入格式不正确，使用默认值30天")
            
            # 启动扫描线程
            self.scan_thread = scan_thread_class(stock_list, config, days=days, kl_type=kl_type)
            self.scan_thread.progress.connect(self.on_scan_progress)
            self.scan_thread.found_signal.connect(self.on_buy_point_found)
            self.scan_thread.finished.connect(self.on_scan_finished)
            self.scan_thread.log_signal.connect(self.on_log_message)
            self.scan_thread.start()
            
            # 显示进度条
            self.progress_bar.setVisible(True)
            self.progress_bar.setMaximum(len(stock_list))
            
        except Exception as e:
            self.log_text.append(f"❌ 扫描启动失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")

    def on_load_chart_clicked(self):
        """处理加载图表按钮点击"""
        code = self.stock_code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "警告", "请输入股票代码！")
            return
        
        # 标准化股票代码格式
        normalized_code = normalize_stock_code(code)
        self.log_text.append(f"📈 正在加载 {normalized_code} 的图表...")
        
        try:
            # 获取配置
            config = self.get_chan_config()
            # 使用分析标签页中的时间级别选择，而不是扫描配置中的选择
            kl_type = self.get_analysis_timeframe_kl_type()
            
            # 获取用户输入的天数
            try:
                days_text = self.days_input.text().strip()
                if days_text:
                    days = int(days_text)
                    if days <= 0:
                        days = 30  # 如果输入不合法，默认为30天
                else:
                    days = 30  # 如果没有输入，默认为30天
            except ValueError:
                days = 30  # 如果转换失败，默认为30天
                self.log_text.append(f"⚠️ 天数输入格式不正确，使用默认值30天")
            
            # 根据用户选择的数据源设置数据源优先级
            selected_data_source = self.data_source_combo.currentText()
            if selected_data_source == "Futu优先":
                data_sources = [DATA_SRC.FUTU, "custom:SQLiteAPI.SQLiteAPI"]
            else:  # "SQLite数据库"
                data_sources = ["custom:SQLiteAPI.SQLiteAPI", DATA_SRC.FUTU]
            
            # 启动分析线程
            self.analysis_thread = SingleAnalysisThread(normalized_code, config, kl_type, days=days, data_sources=data_sources)
            self.analysis_thread.finished.connect(self.on_analysis_finished)
            self.analysis_thread.error.connect(self.on_analysis_error)
            self.analysis_thread.log_signal.connect(self.on_log_message)
            self.analysis_thread.start()
            
        except Exception as e:
            self.log_text.append(f"❌ 图表加载失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")

    def on_log_message(self, message):
        """处理日志消息"""
        self.log_text.append(message)

    def on_update_database_finished(self, success, message):
        """处理数据库更新完成"""
        if success:
            self.log_text.append(f"✅ {message}")
            self.last_update_label.setText(f"上次更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        else:
            self.log_text.append(f"❌ {message}")
        
        # 重新启用按钮
        self.update_db_btn.setEnabled(True)

    def on_scan_progress(self, current, total, stock_info):
        """处理扫描进度"""
        self.progress_bar.setValue(current)
        self.statusBar().showMessage(f'扫描进度: {current}/{total} - {stock_info}')

    def on_buy_point_found(self, data):
        """处理发现买点或卖点"""
        # 在结果表格中添加一行
        row_position = self.result_table.rowCount()
        self.result_table.insertRow(row_position)
        
        self.result_table.setItem(row_position, 0, QTableWidgetItem(data['code']))
        self.result_table.setItem(row_position, 1, QTableWidgetItem(data['name']))
        self.result_table.setItem(row_position, 2, QTableWidgetItem(data['bsp_type']))
        
        # 添加评分 - 根据买卖点类型和级别给出不同评分
        bsp_level = data['bsp_type'][2] if len(data['bsp_type']) > 2 else '1'  # 提取买卖点级别，如"买点1"中的"1"
        score = 10 - (ord(bsp_level) - ord('0')) * 2  # 简单评分逻辑，级别越低评分越高
        self.result_table.setItem(row_position, 3, QTableWidgetItem(f"{score}/10"))
        
        self.result_table.setItem(row_position, 4, QTableWidgetItem(data['bsp_time']))
        self.result_table.setItem(row_position, 5, QTableWidgetItem("缠论API"))  # API名称

    def on_scan_finished(self, success_count, fail_count):
        """处理扫描完成"""
        self.log_text.append(f"✅ 扫描完成！成功: {success_count}, 失败: {fail_count}")
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage('扫描完成')

    def on_analysis_finished(self, chan):
        """处理分析完成"""
        try:
            # 检查chan对象是否有效
            if chan is None:
                self.log_text.append("❌ 分析结果无效，无法绘制图表")
                return
                
            self.log_text.append(f"📊 开始绘制图表，股票: {chan.code}")
            self.log_text.append(f"📊 数据源: {chan.data_src}")
            self.log_text.append(f"📊 时间范围: {chan.begin_time} - {chan.end_time}")
            
            # 清除画布
            self.canvas.clear()
            
            # 检查是否有K线数据
            if len(chan.lv_list) > 0:
                first_lv = chan.lv_list[0]
                kl_data = list(chan[first_lv])
                self.log_text.append(f"📊 K线数据量: {len(kl_data)}")
            else:
                self.log_text.append("❌ 没有K线数据")
                return
            
            # 尝试访问缠论结构以触发计算
            try:
                if hasattr(chan, 'bi_list'):
                    bi_list = list(chan.bi_list)
                    self.log_text.append(f"📊 笔列表长度: {len(bi_list)}")
                if hasattr(chan, 'seg_list'):
                    seg_list = list(chan.seg_list)
                    self.log_text.append(f"📊 线段列表长度: {len(seg_list)}")
                if hasattr(chan, 'zs_list'):
                    zs_list = list(chan.zs_list)
                    self.log_text.append(f"📊 中枢列表长度: {len(zs_list)}")
            except Exception as e:
                self.log_text.append(f"⚠️ 访问缠论结构时出错: {str(e)}")
            
            # 关闭旧的 figure 释放内存
            import matplotlib.pyplot as plt
            plt.close('all')

            # 根据时间级别设置合适的x_range值
            current_kl_type = self.get_analysis_timeframe_kl_type()
            x_range_map = {
                KL_TYPE.K_DAY: 250,    # 日线显示250根K线
                KL_TYPE.K_30M: 150,    # 30分钟显示150根K线
                KL_TYPE.K_5M: 80,      # 5分钟显示80根K线
                KL_TYPE.K_1M: 40,      # 1分钟显示40根K线
            }
            x_range = x_range_map.get(current_kl_type, 0)
            
            # 获取控件宽度，计算合适的图表尺寸
            canvas_width = self.canvas.width()
            dpi = 100
            fig_width = canvas_width / dpi
            fig_height = fig_width * 0.6  # 宽高比约 5:3

            plot_para = {
                "figure": {
                    "x_range": x_range,
                    "w": fig_width,
                    "h": fig_height,
                }
            }

            # 获取图表配置
            plot_config = {
                "plot_kline": True,  # 显示K线
                "plot_kline_combine": True,  # 显示合并K线
                "plot_bi": True,  # 显示笔
                "plot_seg": True,  # 显示线段
                "plot_zs": True,  # 显示中枢
                "plot_macd": True,  # 显示MACD
                "plot_bsp": True,  # 显示买卖点
            }
            plot_driver = CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
            
            # 将生成的figure赋给canvas
            self.canvas.fig = plot_driver.figure
            self.canvas.figure = plot_driver.figure
            # 刷新画布
            self.canvas.draw()
            self.toolbar.update()
            # 显示分析详情
            bi_count = len(list(chan.bi_list)) if hasattr(chan, 'bi_list') and chan.bi_list is not None else 0
            seg_count = len(list(chan.seg_list)) if hasattr(chan, 'seg_list') and chan.seg_list is not None else 0
            zs_count = len(list(chan.zs_list)) if hasattr(chan, 'zs_list') and chan.zs_list is not None else 0
            
            self.analysis_detail_text.setPlainText(f"缠论分析完成！\n\n"
                                                  f"股票: {chan.code}\n"
                                                  f"时间范围: {chan.begin_time} - {chan.end_time}\n"
                                                  f"数据源: {chan.data_src}\n"
                                                  f"笔数量: {bi_count}\n"
                                                  f"线段数量: {seg_count}\n"
                                                  f"中枢数量: {zs_count}")
            
            self.log_text.append(f"✅ 图表绘制完成")

        except Exception as e:
            self.log_text.append(f"❌ 图表绘制失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")

    def on_analysis_error(self, error_msg):
        """处理分析错误"""
        self.log_text.append(f"❌ 图表分析失败: {error_msg}")

    def load_futu_watchlists(self):
        """加载富途自选股分组列表"""
        try:
            from futu import OpenQuoteContext, RET_OK
            # 从环境变量或配置文件获取富途API地址
            import os
            FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
            
            # 创建富途API连接
            quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
            
            # 获取所有自选股分组
            ret, data = quote_ctx.get_user_security_group()
            if ret == RET_OK:
                groups = data.to_dict('records')
                group_names = [group['group_name'] for group in groups if group['group_name'].strip()]
                
                # 更新下拉菜单选项
                self.watchlist_combo.clear()
                self.watchlist_combo.addItems(group_names)
                
                # 安全地写入日志
                if hasattr(self, 'log_text'):
                    self.log_text.append(f"✅ 成功加载 {len(group_names)} 个自选股分组")
                    
                # 关闭连接
                quote_ctx.close()
                return group_names
            else:
                # 安全地写入日志
                if hasattr(self, 'log_text'):
                    self.log_text.append(f"❌ 获取自选股分组失败: {data}")
                    
                # 关闭连接
                quote_ctx.close()
                return []
        except ImportError:
            # 如果没有futu模块，添加默认选项
            default_groups = ["沪深A股", "港股通", "全部", "自选股1", "自选股2"]
            self.watchlist_combo.clear()
            self.watchlist_combo.addItems(default_groups)
            
            # 安全地写入日志
            if hasattr(self, 'log_text'):
                self.log_text.append(f"⚠️ 未安装futu-api模块，使用默认分组选项。如需使用富途自选股，请安装futu-api模块。")
            return default_groups
        except Exception as e:
            # 安全地写入日志
            if hasattr(self, 'log_text'):
                self.log_text.append(f"❌ 加载自选股分组时出错: {str(e)}")
                import traceback
                self.log_text.append(f"详细错误: {traceback.format_exc()}")
            return []

def main():
    """程序入口函数"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TraderGUI()
    window.show()
    
    # 确保在窗口显示后按钮是可见的
    window.ensure_buttons_visible()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()