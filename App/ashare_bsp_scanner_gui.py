"""
A股缠论买点扫描器 - Powered by chan.py

功能说明:
    - 批量扫描A股市场，自动识别近期出现买点的股票
    - 支持单只股票的缠论分析和图表展示
    - 可视化显示K线、笔、线段、中枢、买卖点、MACD等

数据来源:
    - 使用 Futu 获取A股实时行情和历史K线数据（支持5分钟级别）

过滤规则:
    - 剔除ST股票、科创板(688)、北交所、B股
    - 剔除停牌股票和新股

依赖:
    - PyQt6: GUI框架
    - matplotlib: 图表绑定
    - futu: A股数据接口（支持5分钟级别）
    - chan.py: 缠论分析核心库

使用方法:
    python App/ashare_bsp_scanner_gui.py
"""
import sys
from pathlib import Path

# 将项目根目录加入路径，以便导入 chan.py 核心模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QGroupBox,
    QMessageBox, QStatusBar, QSplitter, QTableWidget, QTableWidgetItem,
    QProgressBar, QHeaderView, QTextEdit, QSpinBox, QDateTimeEdit,
    QSizePolicy
)
from PyQt6.QtCore import QDate, Qt, QThread, pyqtSignal, QDateTime

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

import akshare as ak
import pandas as pd
import os
import re
import yaml

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE

# 富途API相关
try:
    from futu import RET_OK
except ImportError:
    RET_OK = 0  # 如果没有安装futu，使用默认值

# 富途实时监控相关
from Monitoring.FutuMonitor import FutuMonitor

# 港股自动化交易控制器
from App.HKTradingController import HKTradingController

# 性能仪表盘
from App.PerformanceDashboard import PerformanceDashboard


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

def get_local_stock_list():
    """
    从本地SQLite数据库获取所有股票代码列表
    
    Returns:
        pd.DataFrame: 包含 ['代码', '名称', '最新价', '涨跌幅'] 列的股票列表
    """
    try:
        from Trade.db_util import CChanDB
        db = CChanDB()
        # 查询kline_day表中所有的唯一股票代码
        query = "SELECT DISTINCT code FROM kline_day ORDER BY code"
        df_codes = db.execute_query(query)
        
        if df_codes.empty:
            return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])
            
        # 为简化处理，这里只返回代码列，其他列设为默认值
        result_df = pd.DataFrame({
            '代码': df_codes['code'],
            '名称': [''] * len(df_codes),
            '最新价': [0.0] * len(df_codes),
            '涨跌幅': [0.0] * len(df_codes)
        })
        return result_df
    except Exception as e:
        print(f"从本地数据库获取股票列表失败: {e}")
        return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])


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
            success_count = 0
            
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


class RepairSingleStockThread(QThread):
    """
    单只股票数据修复的后台线程
    
    在独立线程中为指定的单个股票下载并补充历史数据。
    
    Signals:
        log_signal: (str) 日志消息
        finished: (bool, str) 完成信号，包含成功状态和消息
    """
    log_signal = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, stock_code):
        """
        初始化单只股票修复线程
        
        Args:
            stock_code: str, 股票代码
        """
        super().__init__()
        self.stock_code = stock_code
        self.is_running = True
        
    def stop(self):
        """停止数据修复"""
        self.is_running = False
        self.log_signal.emit("正在停止数据修复...")
        
    def run(self):
        """执行单只股票数据修复任务"""
        try:
            if not self.stock_code:
                self.finished.emit(False, "股票代码为空")
                return
                
            from datetime import datetime
            from repair_data import diagnose_and_repair_stock
            
            # 定义要修复的时间级别
            timeframes = ['day', '30m', '5m', '1m']
            start_date = "2024-01-01"
            end_date = datetime.now().strftime("%Y-%m-%d")
            
            repaired_count = 0
            
            def log_callback(msg):
                if self.is_running:
                    self.log_signal.emit(msg)
                    
            # 对每个时间级别进行诊断和修复
            for timeframe in timeframes:
                if not self.is_running:
                    break
                    
                try:
                    if diagnose_and_repair_stock(self.stock_code, timeframe, start_date, end_date, log_callback):
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


class OfflineSingleAnalysisThread(QThread):
    """
    离线单只股票分析的后台线程

    用于分析用户手动输入的股票代码，从SQLite数据库读取数据，避免阻塞 UI。

    Signals:
        finished: (CChan) 分析完成，返回 CChan 对象
        error: (str) 分析出错时返回错误信息
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, code, config, kl_type, days=365):
        """
        初始化分析线程

        Args:
            code: str, 股票代码（如 '000001'）
            config: CChanConfig, 缠论配置
            kl_type: KL_TYPE, 时间级别
            days: int, 获取多少天的历史数据
        """
        super().__init__()
        self.code = code
        self.config = config
        self.kl_type = kl_type
        self.days = days

    def run(self):
        """执行缠论分析，完成后通过信号返回结果"""
        try:
            begin_time = (datetime.now() - timedelta(days=self.days)).strftime("%Y-%m-%d")
            end_time = datetime.now().strftime("%Y-%m-%d")

            chan = CChan(
                code=self.code,
                begin_time=begin_time,
                end_time=end_time,
                data_src="custom:SQLiteAPI.SQLiteAPI",  # 使用自定义数据源（SQLite）
                lv_list=[self.kl_type],
                config=self.config,
                autype=AUTYPE.QFQ,
            )
            self.finished.emit(chan)
        except Exception as e:
            error_msg = str(e)
            if "list index out of range" in error_msg:
                self.error.emit("数据不足，无法分析。请确保数据库中有足够的历史K线数据（至少30天以上）。")
            elif "custom" in error_msg.lower():
                self.error.emit("数据源错误，请检查数据库连接和表结构。")
            else:
                self.error.emit(f"分析失败: {error_msg}")


class SingleAnalysisThread(QThread):
    """
    单只股票分析的后台线程

    用于分析用户手动输入的股票代码，避免阻塞 UI。

    Signals:
        finished: (CChan) 分析完成，返回 CChan 对象
        error: (str) 分析出错时返回错误信息
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, code, config, kl_type, days=365):
        """
        初始化分析线程

        Args:
            code: str, 股票代码（如 '000001'）
            config: CChanConfig, 缠论配置
            kl_type: KL_TYPE, 时间级别
            days: int, 获取多少天的历史数据
        """
        super().__init__()
        self.code = code
        self.config = config
        self.kl_type = kl_type
        self.days = days

    def run(self):
        """执行缠论分析，完成后通过信号返回结果"""
        try:
            begin_time = (datetime.now() - timedelta(days=self.days)).strftime("%Y-%m-%d")
            end_time = datetime.now().strftime("%Y-%m-%d")

            chan = CChan(
                code=self.code,
                begin_time=begin_time,
                end_time=end_time,
                data_src=DATA_SRC.FUTU,
                lv_list=[self.kl_type],
                config=self.config,
                autype=AUTYPE.QFQ,
            )
            self.finished.emit(chan)
        except Exception as e:
            self.error.emit(str(e))


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


class AkshareGUI(QMainWindow):
    """
    A股缠论买点扫描器主窗口

    主要功能:
        - 批量扫描: 自动获取所有可交易股票，逐一分析寻找买点
        - 单股分析: 手动输入股票代码进行缠论分析
        - 图表显示: 可视化展示K线、笔、线段、中枢、买卖点、MACD

    界面布局:
        - 左侧面板: 扫描控制、单股输入、买点列表、扫描日志
        - 右侧面板: 图表显示区域，支持缩放和导航
    """
    log_signal = pyqtSignal(str)

    def __init__(self):
        """初始化主窗口"""
        super().__init__()
        self.chan = None  # 当前分析的 CChan 对象
        self.scan_thread = None  # 批量扫描线程
        self.analysis_thread = None  # 单股分析线程
        self.update_db_thread = None  # 数据库更新线程
        self.repair_thread = None  # 单股数据修复线程
        self.stock_cache = {}  # 缓存已分析的股票 {code: CChan}
        self.futu_monitor = None  # 富途监控器
        self.hk_trading_controller = None  # 港股自动化交易控制器
        self.log_signal.connect(self.on_log_message)
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle('A股缠论买点扫描器 - Powered by chan.py')
        self.setGeometry(100, 100, 1600, 900)

        # 创建中央 widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)

        # 左侧控制面板、股票列表和性能仪表盘
        left_panel = self.create_left_panel()
        performance_dashboard = PerformanceDashboard()

        # 右侧图表区域
        right_panel = self.create_chart_panel()

        # 使用分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(performance_dashboard)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 200, 1100])

        main_layout.addWidget(splitter)

        # 状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage('就绪 - 点击"开始扫描"分析所有股票')

    def create_left_panel(self):
        """创建左侧面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # 扫描控制
        scan_group = QGroupBox("扫描设置")
        scan_layout = QVBoxLayout(scan_group)

        # 笔严格模式
        self.bi_strict_cb = QCheckBox("笔严格模式")
        self.bi_strict_cb.setChecked(True)
        scan_layout.addWidget(self.bi_strict_cb)

        # 在线/离线模式选择
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("数据源模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["在线 (AKShare)", "离线 (SQLite)"])
        mode_layout.addWidget(self.mode_combo)
        scan_layout.addLayout(mode_layout)

        # === 新增：Futu 自选股分组选择 ===
        futu_watchlist_layout = QHBoxLayout()
        futu_watchlist_layout.addWidget(QLabel("Futu 自选股分组:"))
        self.futu_watchlist_combo = QComboBox()
        futu_watchlist_layout.addWidget(self.futu_watchlist_combo)
        scan_layout.addLayout(futu_watchlist_layout)
        # === 新增结束 ===

        # 数据下载时间设置
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("数据时间范围:"))
        self.days_input = QSpinBox()
        self.days_input.setRange(30, 2190)  # 30天到6年
        self.days_input.setValue(365)  # 默认1年
        self.days_input.setSuffix(" 天")
        time_layout.addWidget(self.days_input)
        scan_layout.addLayout(time_layout)
        
        # 时间级别选择
        timeframe_layout = QHBoxLayout()
        timeframe_layout.addWidget(QLabel("时间级别:"))
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(["日线", "30分钟", "5分钟", "1分钟"])
        self.timeframe_combo.setCurrentText("日线")
        timeframe_layout.addWidget(self.timeframe_combo)
        scan_layout.addLayout(timeframe_layout)
        
        # 更新本地数据库按钮
        db_btn_layout = QHBoxLayout()
        self.update_db_btn = QPushButton("更新本地数据库")
        self.update_db_btn.clicked.connect(self.update_local_database)
        db_btn_layout.addWidget(self.update_db_btn)
        
        self.stop_update_db_btn = QPushButton("停止更新")
        self.stop_update_db_btn.clicked.connect(self.stop_update_database)
        self.stop_update_db_btn.setEnabled(False)
        self.stop_update_db_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 12px;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #da190b; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        db_btn_layout.addWidget(self.stop_update_db_btn)
        scan_layout.addLayout(db_btn_layout)

        # 扫描按钮
        btn_layout = QHBoxLayout()
        self.scan_btn = QPushButton("开始扫描")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        btn_layout.addWidget(self.scan_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #da190b; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        btn_layout.addWidget(self.stop_btn)
        scan_layout.addLayout(btn_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        scan_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        scan_layout.addWidget(self.progress_label)

        layout.addWidget(scan_group)

        # 单只股票分析
        single_group = QGroupBox("单只股票分析")
        single_layout = QVBoxLayout(single_group)

        code_row = QHBoxLayout()
        code_row.addWidget(QLabel("股票代码:"))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("如: 000001")
        code_row.addWidget(self.code_input)

        self.analyze_btn = QPushButton("分析")
        self.analyze_btn.clicked.connect(self.analyze_single)
        code_row.addWidget(self.analyze_btn)
        
        self.repair_btn = QPushButton("补全数据")
        self.repair_btn.clicked.connect(self.repair_single_stock)
        code_row.addWidget(self.repair_btn)
        single_layout.addLayout(code_row)

        layout.addWidget(single_group)

        # 买点股票列表
        list_group = QGroupBox("买点股票列表")
        list_layout = QVBoxLayout(list_group)

        self.stock_table = QTableWidget()
        self.stock_table.setColumnCount(7)
        self.stock_table.setHorizontalHeaderLabels(['代码', '名称', '现价', '涨跌%', '信号类型', '评分', 'API'])
        self.stock_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stock_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.stock_table.cellClicked.connect(self.on_stock_clicked)
        list_layout.addWidget(self.stock_table)

        # 清空按钮
        self.clear_list_btn = QPushButton("清空列表")
        self.clear_list_btn.clicked.connect(self.clear_stock_list)
        list_layout.addWidget(self.clear_list_btn)

        layout.addWidget(list_group)

        # 日志区域
        log_group = QGroupBox("扫描日志")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)

        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        log_layout.addWidget(clear_log_btn)

        layout.addWidget(log_group)

        # === 新增：Futu 实时监控面板 ===
        futu_group = QGroupBox("Futu 实时监控")
        futu_layout = QVBoxLayout(futu_group)

        # 刷新和控制按钮
        futu_btn_layout = QHBoxLayout()
        self.futu_refresh_btn = QPushButton("刷新列表")
        self.futu_refresh_btn.clicked.connect(self.refresh_futu_watchlists)
        futu_btn_layout.addWidget(self.futu_refresh_btn)

        self.futu_start_btn = QPushButton("开始监控")
        self.futu_start_btn.clicked.connect(self.start_futu_monitoring)
        futu_btn_layout.addWidget(self.futu_start_btn)

        self.futu_stop_btn = QPushButton("停止监控")
        self.futu_stop_btn.clicked.connect(self.stop_futu_monitoring)
        self.futu_stop_btn.setEnabled(False)
        futu_btn_layout.addWidget(self.futu_stop_btn)
        futu_layout.addLayout(futu_btn_layout)

        # 监控日 log
        self.futu_log_text = QTextEdit()
        self.futu_log_text.setReadOnly(True)
        self.futu_log_text.setMaximumHeight(150)
        futu_layout.addWidget(self.futu_log_text)

        layout.addWidget(futu_group)
        # === 新增结束 ===

        # === 新增：自动化交易面板 ===
        auto_trade_group = QGroupBox("自动化交易 (港股)")
        auto_trade_layout = QVBoxLayout(auto_trade_group)

        # 控制按钮
        auto_trade_btn_layout = QHBoxLayout()
        self.auto_trade_start_btn = QPushButton("启动自动交易")
        self.auto_trade_start_btn.clicked.connect(self.start_auto_trading)
        auto_trade_btn_layout.addWidget(self.auto_trade_start_btn)

        self.auto_trade_stop_btn = QPushButton("停止自动交易")
        self.auto_trade_stop_btn.clicked.connect(self.stop_auto_trading)
        self.auto_trade_stop_btn.setEnabled(False)
        auto_trade_btn_layout.addWidget(self.auto_trade_stop_btn)
        auto_trade_layout.addLayout(auto_trade_btn_layout)

        # 交易日志
        self.auto_trade_log_text = QTextEdit()
        self.auto_trade_log_text.setReadOnly(True)
        self.auto_trade_log_text.setMaximumHeight(150)
        auto_trade_layout.addWidget(self.auto_trade_log_text)

        # 实时交易监控按钮
        realtime_trade_btn_layout = QHBoxLayout()
        self.realtime_trade_start_btn = QPushButton("启动实时交易监控")
        self.realtime_trade_start_btn.clicked.connect(self.start_realtime_trading)
        realtime_trade_btn_layout.addWidget(self.realtime_trade_start_btn)
        
        self.realtime_trade_stop_btn = QPushButton("停止实时交易监控")
        self.realtime_trade_stop_btn.clicked.connect(self.stop_realtime_trading)
        self.realtime_trade_stop_btn.setEnabled(False)
        realtime_trade_btn_layout.addWidget(self.realtime_trade_stop_btn)
        auto_trade_layout.addLayout(realtime_trade_btn_layout)
        
        layout.addWidget(auto_trade_group)
        # === 新增结束 ===

        return panel

    def create_chart_panel(self):
        """创建右侧图表面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # 绘图配置
        config_layout = QHBoxLayout()

        self.plot_kline_cb = QCheckBox("K线")
        self.plot_kline_cb.setChecked(True)
        config_layout.addWidget(self.plot_kline_cb)

        self.plot_bi_cb = QCheckBox("笔")
        self.plot_bi_cb.setChecked(True)
        config_layout.addWidget(self.plot_bi_cb)

        self.plot_seg_cb = QCheckBox("线段")
        self.plot_seg_cb.setChecked(True)
        config_layout.addWidget(self.plot_seg_cb)

        self.plot_zs_cb = QCheckBox("中枢")
        self.plot_zs_cb.setChecked(True)
        config_layout.addWidget(self.plot_zs_cb)

        self.plot_bsp_cb = QCheckBox("买卖点")
        self.plot_bsp_cb.setChecked(True)
        config_layout.addWidget(self.plot_bsp_cb)

        self.plot_macd_cb = QCheckBox("MACD")
        self.plot_macd_cb.setChecked(True)
        config_layout.addWidget(self.plot_macd_cb)

        config_layout.addStretch()

        # 刷新按钮
        self.refresh_btn = QPushButton("刷新图表")
        self.refresh_btn.clicked.connect(self.refresh_chart)
        config_layout.addWidget(self.refresh_btn)

        layout.addLayout(config_layout)

        # matplotlib 画布
        self.canvas = ChanPlotCanvas(panel, width=12, height=8)
        self.toolbar = NavigationToolbar(self.canvas, panel)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        # 确保画布能随窗口大小变化
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        # 设置最小高度，确保有足够的空间
        self.canvas.setMinimumHeight(400)

        # 保存布局引用
        self.chart_layout = layout
        self.right_panel = panel

        return panel

    def get_chan_config(self):
        """
        获取缠论分析配置

        Returns:
            CChanConfig: 包含笔严格模式、买卖点类型等配置的对象
        """
        return CChanConfig({
            "bi_strict": self.bi_strict_cb.isChecked(),  # 笔严格模式
            "trigger_step": False,  # 不启用逐步触发模式
            "skip_step": 0,
            "divergence_rate": float("inf"),  # 背驰比率
            "bsp2_follow_1": False,  # 二类买卖点不跟随一类
            "bsp3_follow_1": False,  # 三类买卖点不跟随一类
            "min_zs_cnt": 0,  # 最小中枢数量
            "bs1_peak": False,
            "macd_algo": "peak",  # MACD 算法
            "bs_type": "1,1p,2,2s,3a,3b",  # 启用的买卖点类型
            "print_warning": False,
            "zs_algo": "normal",  # 中枢算法
        })

    def get_timeframe_kl_type(self):
        """
        根据GUI中选择的时间级别返回对应的KL_TYPE
        
        Returns:
            KL_TYPE: 对应的时间级别枚举
        """
        timeframe_map = {
            "日线": KL_TYPE.K_DAY,
            "30分钟": KL_TYPE.K_30M,
            "5分钟": KL_TYPE.K_5M,
            "1分钟": KL_TYPE.K_1M,
        }
        selected_text = self.timeframe_combo.currentText()
        return timeframe_map.get(selected_text, KL_TYPE.K_DAY)

    def get_plot_config(self):
        """
        获取图表绑定配置

        Returns:
            dict: 包含各图层显示开关的配置字典
        """
        return {
            "plot_kline": self.plot_kline_cb.isChecked(),  # 显示K线
            "plot_kline_combine": True,  # 显示合并K线
            "plot_bi": self.plot_bi_cb.isChecked(),  # 显示笔
            "plot_seg": self.plot_seg_cb.isChecked(),  # 显示线段
            "plot_zs": self.plot_zs_cb.isChecked(),  # 显示中枢
            "plot_macd": self.plot_macd_cb.isChecked(),  # 显示MACD
            "plot_bsp": self.plot_bsp_cb.isChecked(),  # 显示买卖点
        }

    def start_scan(self):
        """开始批量扫描所有可交易股票"""
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.stock_cache.clear()

        self.statusBar.showMessage('正在获取股票列表...')
        QApplication.processEvents()

        # 获取所选的Futu自选股分组
        selected_watchlist = self.futu_watchlist_combo.currentText()
        if selected_watchlist:
            try:
                from Monitoring.FutuMonitor import FutuMonitor
                monitor = FutuMonitor()
                ret, data = monitor.quote_ctx.get_user_security(group_name=selected_watchlist)
                monitor.quote_ctx.close()
                
                if ret == RET_OK and not data.empty:
                    stock_list = pd.DataFrame({
                        '代码': data['code'],
                        '名称': data['name'],
                        '最新价': [0.0] * len(data),
                        '涨跌幅': [0.0] * len(data)
                    })
                else:
                    QMessageBox.warning(self, "警告", f"无法从分组 '{selected_watchlist}' 获取股票，使用默认列表。")
                    if self.mode_combo.currentText() == "离线 (SQLite)":
                        stock_list = get_local_stock_list()
                    else:
                        stock_list = get_tradable_stocks()
            except Exception as e:
                QMessageBox.warning(self, "警告", f"获取自选股分组 '{selected_watchlist}' 失败: {e}，使用默认列表。")
                if self.mode_combo.currentText() == "离线 (SQLite)":
                    stock_list = get_local_stock_list()
                else:
                    stock_list = get_tradable_stocks()
        else:
            # 根据模式选择获取股票列表的方式
            if self.mode_combo.currentText() == "离线 (SQLite)":
                stock_list = get_local_stock_list()
            else:
                stock_list = get_tradable_stocks()
        if stock_list.empty:
            QMessageBox.warning(self, "警告", "获取股票列表失败")
            self.scan_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.progress_bar.setVisible(False)
            return

        self.statusBar.showMessage(f'获取到 {len(stock_list)} 只可交易股票，开始扫描...')
        self.progress_bar.setMaximum(len(stock_list))

        # 获取天数设置
        days = self.days_input.value()

        # 根据模式选择启动不同的扫描线程
        config = self.get_chan_config()
        kl_type = self.get_timeframe_kl_type()
        if self.mode_combo.currentText() == "离线 (SQLite)":
            self.scan_thread = OfflineScanThread(stock_list, config, days=days, kl_type=kl_type)
        else:
            self.scan_thread = ScanThread(stock_list, config, days=days, kl_type=kl_type)
            
        self.scan_thread.progress.connect(self.on_scan_progress)
        self.scan_thread.found_signal.connect(self.on_buy_point_found)
        self.scan_thread.finished.connect(self.on_scan_finished)
        self.scan_thread.log_signal.connect(self.on_log_message)
        self.scan_thread.start()

    def update_local_database(self):
        """更新本地数据库"""
        self.update_db_btn.setEnabled(False)
        self.stop_update_db_btn.setEnabled(True)
        days = self.days_input.value()
        self.statusBar.showMessage(f'开始下载并更新本地数据库... (数据时间范围: {days} 天)')
        self.log_text.append(f"🔄 开始更新本地数据库，下载最近 {days} 天的数据...")
        
        # 获取所选的Futu自选股分组
        selected_watchlist = self.futu_watchlist_combo.currentText()
        if selected_watchlist:
            try:
                from Monitoring.FutuMonitor import FutuMonitor
                monitor = FutuMonitor()
                ret, data = monitor.quote_ctx.get_user_security(group_name=selected_watchlist)
                monitor.quote_ctx.close()
                
                if ret == RET_OK and not data.empty:
                    stock_list = pd.DataFrame({
                        '代码': data['code'],
                        '名称': data['name'],
                        '最新价': [0.0] * len(data),
                        '涨跌幅': [0.0] * len(data)
                    })
                else:
                    self.log_text.append(f"⚠️ 无法从分组 '{selected_watchlist}' 获取股票，使用默认列表。")
                    # 根据模式选择默认列表
                    if self.mode_combo.currentText() == "离线 (SQLite)":
                        stock_list = get_local_stock_list()
                        if stock_list.empty:
                            self.log_text.append("⚠️ 本地数据库中没有股票，尝试从在线源获取股票列表...")
                            stock_list = get_tradable_stocks()
                    else:
                        stock_list = get_tradable_stocks()
            except Exception as e:
                self.log_text.append(f"⚠️ 获取自选股分组 '{selected_watchlist}' 失败: {e}，使用默认列表。")
                # 根据模式选择默认列表
                if self.mode_combo.currentText() == "离线 (SQLite)":
                    stock_list = get_local_stock_list()
                    if stock_list.empty:
                        self.log_text.append("⚠️ 本地数据库中没有股票，尝试从在线源获取股票列表...")
                        stock_list = get_tradable_stocks()
                else:
                    stock_list = get_tradable_stocks()
        else:
            # 如果没有选择分组，则根据模式选择默认逻辑
            if self.mode_combo.currentText() == "离线 (SQLite)":
                stock_list = get_local_stock_list()
                if stock_list.empty:
                    self.log_text.append("⚠️ 本地数据库中没有股票，尝试从在线源获取股票列表...")
                    stock_list = get_tradable_stocks()
            else:
                stock_list = get_futu_watchlist_stocks()
                if stock_list.empty:
                    stock_list = get_tradable_stocks()
        
        if stock_list.empty:
            self.statusBar.showMessage('股票列表为空，无法更新数据库')
            self.log_text.append("❌ 股票列表为空，无法更新数据库")
            self.update_db_btn.setEnabled(True)
            self.stop_update_db_btn.setEnabled(False)
            return
            
        # 获取选择的时间级别
        selected_timeframe = self.timeframe_combo.currentText()
        timeframe_map = {
            "日线": ['day'],
            "30分钟": ['30m'],
            "5分钟": ['5m'],
            "1分钟": ['1m'],
        }
        timeframes_to_download = timeframe_map.get(selected_timeframe, ['day'])
        
        
        stock_codes = stock_list['代码'].tolist()
        self.log_text.append(f"📊 准备下载 {len(stock_codes)} 只股票的 {selected_timeframe} 数据...")
        
        # 启动QThread下载数据
        self.update_db_thread = UpdateDatabaseThread(
            stock_codes,
            days,
            timeframes_to_download,
            None,  # start_date
            None   # end_date
        )
        self.update_db_thread.log_signal.connect(self.on_log_message)
        self.update_db_thread.finished.connect(self.on_update_database_finished)
        self.update_db_thread.start()

    def stop_scan(self):
        """停止扫描"""
        if self.scan_thread:
            self.scan_thread.stop()
        self.statusBar.showMessage('正在停止扫描...')
    
    def stop_update_database(self):
        """停止更新数据库"""
        if self.update_db_thread:
            self.update_db_thread.stop()
        self.statusBar.showMessage('正在停止数据库更新...')
    
    def on_update_database_finished(self, success, message):
        """数据库更新完成回调"""
        self.update_db_btn.setEnabled(True)
        self.stop_update_db_btn.setEnabled(False)
        self.statusBar.showMessage(message)

    def on_scan_progress(self, current, total, stock_info):
        """扫描进度更新"""
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"进度: {current}/{total} - {stock_info}")

    def on_log_message(self, msg):
        """显示日志消息"""
        self.log_text.append(msg)

    def on_buy_point_found(self, data):
        """
        发现买点或卖点的回调函数

        Args:
            data: dict, 包含股票代码、名称、价格、买卖点类型、CChan对象等信息
        """
        row = self.stock_table.rowCount()
        self.stock_table.insertRow(row)
        self.stock_table.setItem(row, 0, QTableWidgetItem(data['code']))
        self.stock_table.setItem(row, 1, QTableWidgetItem(data['name']))
        self.stock_table.setItem(row, 2, QTableWidgetItem(f"{data['price']:.2f}"))
        self.stock_table.setItem(row, 3, QTableWidgetItem(f"{data['change']:.2f}%"))
        self.stock_table.setItem(row, 4, QTableWidgetItem(f"{data['bsp_type']} ({data['bsp_time']})"))
        
        # 添加评分和API名称 - 这里可以根据实际需求调整评分逻辑
        # 模拟评分：根据买卖点类型和级别给出不同评分
        bsp_level = data['bsp_type'][2] if len(data['bsp_type']) > 2 else '1'  # 提取买卖点级别，如"买点1"中的"1"
        score = 10 - (ord(bsp_level) - ord('0')) * 2  # 简单评分逻辑，级别越低评分越高
        self.stock_table.setItem(row, 5, QTableWidgetItem(f"{score}/10"))
        self.stock_table.setItem(row, 6, QTableWidgetItem("缠论API"))  # API名称

        # 缓存 chan 对象
        self.stock_cache[data['code']] = data['chan']

    def on_scan_finished(self, success_count, fail_count):
        """扫描完成"""
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        found_count = self.stock_table.rowCount()
        self.statusBar.showMessage(f'扫描完成: 成功{success_count}只, 跳过{fail_count}只, 发现{found_count}只买点股票')
        self.progress_label.setText(f"完成: 成功{success_count}, 跳过{fail_count}, 买点{found_count}")

    def on_stock_clicked(self, row, col):
        """点击股票列表"""
        code = self.stock_table.item(row, 0).text()
        name = self.stock_table.item(row, 1).text()

        if code in self.stock_cache:
            self.chan = self.stock_cache[code]
            self.plot_chart()
            self.statusBar.showMessage(f'显示: {code} {name}')
        else:
            # 重新分析
            self.analyze_stock(code)

    def analyze_single(self):
        """分析单只股票"""
        code = self.code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "警告", "请输入股票代码")
            return
        
        # 标准化股票代码格式
        normalized_code = normalize_stock_code(code)
        self.analyze_stock(normalized_code)

    def repair_single_stock(self):
        """补全单只股票的历史数据"""
        code = self.code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "警告", "请输入股票代码")
            return
        
        # 标准化股票代码格式
        normalized_code = normalize_stock_code(code)
        
        # 禁用相关按钮，防止重复点击
        self.analyze_btn.setEnabled(False)
        self.repair_btn.setEnabled(False)
        self.statusBar.showMessage(f'正在补全 {normalized_code} 的历史数据...')
        
        # 启动后台修复线程
        self.repair_thread = RepairSingleStockThread(normalized_code)
        self.repair_thread.log_signal.connect(self.on_log_message)
        self.repair_thread.finished.connect(self.on_repair_finished)
        self.repair_thread.start()

    def on_repair_finished(self, success, message):
        """单只股票数据修复完成"""
        # 恢复按钮状态
        self.analyze_btn.setEnabled(True)
        self.repair_btn.setEnabled(True)
        
        if success:
            self.statusBar.showMessage('数据补全完成')
            QMessageBox.information(self, "完成", message)
        else:
            self.statusBar.showMessage('数据补全失败')
            QMessageBox.critical(self, "错误", message)

    def analyze_stock(self, code):
        """分析指定股票"""
        self.analyze_btn.setEnabled(False)
        self.statusBar.showMessage(f'正在分析 {code}...')

        config = self.get_chan_config()
        kl_type = self.get_timeframe_kl_type()
        if self.mode_combo.currentText() == "离线 (SQLite)":
            self.analysis_thread = OfflineSingleAnalysisThread(code, config, kl_type, days=365)
        else:
            self.analysis_thread = SingleAnalysisThread(code, config, kl_type, days=365)
        self.analysis_thread.finished.connect(self.on_analysis_finished)
        self.analysis_thread.error.connect(self.on_analysis_error)
        self.analysis_thread.start()

    def on_analysis_finished(self, chan):
        """单只股票分析完成"""
        self.chan = chan
        self.analyze_btn.setEnabled(True)
        self.plot_chart()
        self.statusBar.showMessage(f'分析完成: {chan.code}')

    def on_analysis_error(self, error_msg):
        """分析出错"""
        self.analyze_btn.setEnabled(True)
        QMessageBox.critical(self, "分析错误", error_msg)
        self.statusBar.showMessage('分析失败')

    def plot_chart(self):
        """
        绑定当前股票的缠论分析图表

        使用 CPlotDriver 生成图表，显示K线、笔、线段、中枢等元素。
        图表大小会根据画布宽度自动调整。
        """
        if not self.chan:
            return

        try:
            from Plot.PlotDriver import CPlotDriver

            plot_config = self.get_plot_config()

            # 使用合理的固定尺寸，让布局自动调整
            fig_width = 12
            fig_height = 8

            # 根据时间级别设置合适的x_range值
            current_kl_type = self.get_timeframe_kl_type()
            x_range_map = {
                KL_TYPE.K_DAY: 250,    # 日线显示250根K线
                KL_TYPE.K_30M: 150,    # 30分钟显示150根K线
                KL_TYPE.K_5M: 240,     # 5分钟显示240根K线（约1周交易日）
                KL_TYPE.K_1M: 240,     # 1分钟显示240根K线（约1个完整交易日）
            }
            x_range = x_range_map.get(current_kl_type, 0)
            
            plot_para = {
                "figure": {
                    "x_range": x_range,
                    "w": fig_width,
                    "h": fig_height,
                }
            }

            # 让CPlotDriver创建新的Figure
            plot_driver = CPlotDriver(self.chan, plot_config=plot_config, plot_para=plot_para)

            # 完全重新创建canvas和toolbar
            self.replace_chart_canvas(plot_driver.figure)
            
        except Exception as e:
            QMessageBox.critical(self, "绑定错误", str(e))

    def replace_chart_canvas(self, figure):
        """替换图表画布和工具栏"""
        # 获取图表面板的布局
        chart_layout = self.chart_layout
        
        # 移除旧的toolbar和canvas（它们在布局的位置1和2）
        if chart_layout.count() >= 3:
            # 移除toolbar（位置1）
            old_toolbar_item = chart_layout.itemAt(1)
            if old_toolbar_item:
                old_toolbar = old_toolbar_item.widget()
                if old_toolbar:
                    old_toolbar.deleteLater()
            
            # 移除canvas（位置2）
            old_canvas_item = chart_layout.itemAt(2)
            if old_canvas_item:
                old_canvas = old_canvas_item.widget()
                if old_canvas:
                    old_canvas.deleteLater()
            
            # 创建新的canvas
            new_canvas = ChanPlotCanvas(self.right_panel, width=12, height=8)
            new_canvas.fig = figure
            new_canvas.figure = figure
            
            # 创建新的toolbar
            from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
            new_toolbar = NavigationToolbar(new_canvas, self.right_panel)
            
            # 添加到布局的正确位置
            chart_layout.insertWidget(1, new_toolbar)
            chart_layout.insertWidget(2, new_canvas)
            
            # 设置canvas属性
            new_canvas.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding
            )
            new_canvas.setMinimumHeight(400)
            
            # 更新引用
            self.canvas = new_canvas
            self.toolbar = new_toolbar

    def refresh_chart(self):
        """刷新图表"""
        self.plot_chart()

    def clear_stock_list(self):
        """清空股票列表"""
        self.stock_table.setRowCount(0)
        self.stock_cache.clear()
        self.statusBar.showMessage('列表已清空')

    # === 新增：Futu 实时监控相关方法 ===
    def refresh_futu_watchlists(self):
        """刷新富途自选股分组列表"""
        try:
            if self.futu_monitor is None:
                self.futu_monitor = FutuMonitor()
            watchlists = self.futu_monitor.get_watchlists()
            self.futu_watchlist_combo.clear()
            self.futu_watchlist_combo.addItems(watchlists)
            self.futu_log_text.append(f"成功获取 {len(watchlists)} 个自选股分组。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取自选股分组失败: {str(e)}")
            self.futu_log_text.append(f"错误: {str(e)}")

    def on_futu_signal(self, signal_data):
        """处理来自 FutuMonitor 的信号"""
        msg = f"[{signal_data['time']}] {signal_data['code']}: {signal_data['signal']} @ {signal_data['price']}"
        self.futu_log_text.append(msg)
        self.statusBar.showMessage(f"新信号: {msg}")
        
        # 如果启用了自动交易，将信号传递给交易控制器
        if self.hk_trading_controller is not None and self.hk_trading_controller._is_running:
            # 在主线程中调用交易控制器的实时信号处理方法
            # 由于FutuMonitor回调可能在非主线程中执行，我们需要确保线程安全
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(
                self.hk_trading_controller,
                "process_realtime_signal",
                Qt.ConnectionType.QueuedConnection,
                Qt.ReturnArgument(bool),
                Qt.Q_ARG(dict, signal_data)
            )

    def start_futu_monitoring(self):
        """开始富途实时监控"""
        selected_group = self.futu_watchlist_combo.currentText()
        if not selected_group:
            QMessageBox.warning(self, "警告", "请先选择一个自选股分组。")
            return

        try:
            self.futu_start_btn.setEnabled(False)
            self.futu_stop_btn.setEnabled(True)
            self.futu_refresh_btn.setEnabled(False)
            if self.futu_monitor is None:
                self.futu_monitor = FutuMonitor()
            self.futu_monitor.set_callback(self.on_futu_signal)
            self.futu_monitor.start(selected_group)
            self.futu_log_text.append(f"开始监控自选股分组: {selected_group}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动监控失败: {str(e)}")
            self.futu_log_text.append(f"错误: {str(e)}")
            self.futu_start_btn.setEnabled(True)
            self.futu_stop_btn.setEnabled(False)
            self.futu_refresh_btn.setEnabled(True)

    def stop_futu_monitoring(self):
        """停止富途实时监控"""
        if self.futu_monitor:
            self.futu_monitor.stop()
        self.futu_start_btn.setEnabled(True)
        self.futu_stop_btn.setEnabled(False)
        self.futu_refresh_btn.setEnabled(True)
        self.futu_log_text.append("监控已停止。")
    # === 新增结束 ===

    # === 新增：自动化交易相关方法 ===
    def on_auto_trade_log(self, message: str):
        """处理来自交易控制器的日志消息"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.auto_trade_log_text.append(f"[{timestamp}] {message}")

    def on_auto_trade_finished(self, executed_sell: int, executed_buy: int, failed_sell: int, failed_buy: int):
        """处理交易完成信号"""
        self.auto_trade_start_btn.setEnabled(True)
        self.auto_trade_stop_btn.setEnabled(False)
        self.statusBar.showMessage(f"自动交易完成: 成功卖出 {executed_sell} 笔, 买入 {executed_buy} 笔")

    def start_auto_trading(self):
        """启动自动化交易"""
        if self.hk_trading_controller is not None and self.hk_trading_controller._is_running:
            QMessageBox.warning(self, "警告", "自动交易已在运行中！")
            return

        try:
            self.auto_trade_start_btn.setEnabled(False)
            self.auto_trade_stop_btn.setEnabled(True)
            self.auto_trade_log_text.clear()
            self.on_auto_trade_log("正在初始化港股交易控制器...")

            # 创建新的交易控制器实例（不设置父对象，以便可以移动到其他线程）
            self.hk_trading_controller = HKTradingController()
            # 连接信号
            self.hk_trading_controller.log_message.connect(self.on_auto_trade_log)
            self.hk_trading_controller.scan_finished.connect(self.on_auto_trade_finished)

            # 在新线程中启动交易流程
            from PyQt6.QtCore import QThread
            self.auto_trade_thread = QThread()
            self.hk_trading_controller.moveToThread(self.auto_trade_thread)
            self.auto_trade_thread.started.connect(self.hk_trading_controller.run_scan_and_trade)
            self.auto_trade_thread.start()

            self.on_auto_trade_log("自动化交易流程已启动。")
        except Exception as e:
            error_msg = f"启动自动交易失败: {str(e)}"
            self.on_auto_trade_log(f"❌ {error_msg}")
            QMessageBox.critical(self, "错误", error_msg)
            self.auto_trade_start_btn.setEnabled(True)
            self.auto_trade_stop_btn.setEnabled(False)

    def stop_auto_trading(self):
        """停止自动化交易"""
        if self.hk_trading_controller:
            self.hk_trading_controller.stop()
            self.on_auto_trade_log("已发送停止信号，等待当前操作完成...")
        self.auto_trade_start_btn.setEnabled(True)
        self.auto_trade_stop_btn.setEnabled(False)
    # === 新增结束 ===
    
    # === 新增：实时交易监控方法 ===
    def start_realtime_trading(self):
        """启动实时交易监控模式"""
        selected_group = self.futu_watchlist_combo.currentText()
        if not selected_group:
            QMessageBox.warning(self, "警告", "请先选择一个自选股分组。")
            return
            
        try:
            # 禁用按钮
            self.realtime_trade_start_btn.setEnabled(False)
            self.realtime_trade_stop_btn.setEnabled(True)
            
            # 初始化交易控制器（如果还没有）
            if self.hk_trading_controller is None:
                self.hk_trading_controller = HKTradingController()
                self.hk_trading_controller.log_message.connect(self.on_auto_trade_log)
                self.hk_trading_controller.scan_finished.connect(self.on_auto_trade_finished)
            
            # 启动 FutuMonitor 如果还没有启动
            if self.futu_monitor is None:
                self.futu_monitor = FutuMonitor()
                self.futu_monitor.set_callback(self.on_futu_signal)
                self.futu_monitor.start(selected_group)
                self.futu_log_text.append(f"自动启动 FutuMonitor 监控分组: {selected_group}")
            
            # 标记为正在运行
            self.hk_trading_controller._is_running = True
            self.on_auto_trade_log("✅ 实时交易监控模式已启动")
            self.statusBar.showMessage("实时交易监控模式已启动")
            
        except Exception as e:
            error_msg = f"启动实时交易监控失败: {str(e)}"
            self.on_auto_trade_log(f"❌ {error_msg}")
            self.futu_log_text.append(f"❌ 启动实时交易监控失败: {str(e)}")
            QMessageBox.critical(self, "错误", error_msg)
            # 恢复按钮状态
            self.realtime_trade_start_btn.setEnabled(True)
            self.realtime_trade_stop_btn.setEnabled(False)
    
    def stop_realtime_trading(self):
        """停止实时交易监控模式"""
        if self.hk_trading_controller:
            self.hk_trading_controller._is_running = False
            self.on_auto_trade_log("⏹️ 实时交易监控模式已停止")
            self.statusBar.showMessage("实时交易监控模式已停止")
        
        # 停止 FutuMonitor 如果正在运行
        if self.futu_monitor:
            self.futu_monitor.stop()
            self.futu_monitor = None
            self.futu_log_text.append("FutuMonitor 已停止")
        
        # 恢复按钮状态
        self.realtime_trade_start_btn.setEnabled(True)
        self.realtime_trade_stop_btn.setEnabled(False)
    # === 新增结束 ===


def main():
    """程序入口函数，创建并运行 GUI 应用"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # 使用 Fusion 风格，跨平台一致性好

    window = AkshareGUI()
    window.show()

    exit_code = app.exec()
    
    # 确保所有后台线程都已停止
    if hasattr(window, 'scan_thread') and window.scan_thread and window.scan_thread.isRunning():
        window.scan_thread.stop()
        window.scan_thread.wait(1000)  # 等待1秒
        
    if hasattr(window, 'analysis_thread') and window.analysis_thread and window.analysis_thread.isRunning():
        window.analysis_thread.quit()
        window.analysis_thread.wait(1000)
        
    if hasattr(window, 'update_db_thread') and window.update_db_thread and window.update_db_thread.isRunning():
        window.update_db_thread.stop()
        window.update_db_thread.wait(1000)
        
    if hasattr(window, 'repair_thread') and window.repair_thread and window.repair_thread.isRunning():
        window.repair_thread.stop()
        window.repair_thread.wait(1000)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
