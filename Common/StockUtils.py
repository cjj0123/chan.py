import os
import re
import pandas as pd
import akshare as ak

try:
    from futu import RET_OK
except ImportError:
    RET_OK = 0

def get_futu_stock_name(code, quote_ctx=None):
    """
    从富途API获取单个股票的准确名称
    
    Args:
        code: str, 股票代码 (如 SH.600000)
        quote_ctx: OpenQuoteContext, 可选的现有连接对象，如不提供则创建新连接
    
    Returns:
        str: 股票名称，获取失败时返回原代码
    """
    try:
        from futu import OpenQuoteContext, RET_OK, Market, SecurityType
        import os
        
        # 是否是外部传入的连接
        is_external_ctx = quote_ctx is not None
        
        if not is_external_ctx:
            # 从环境变量或配置文件获取富途API地址
            FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
            # 创建富途API连接
            quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
        
        # 获取股票基本信息 (修正参数传递：market, stock_type, code_list)
        ret, data = quote_ctx.get_stock_basicinfo(Market.HK, SecurityType.STOCK, [code])
        if ret != RET_OK or data.empty:
            # 尝试获取A股信息
            market = Market.SH if code.startswith('SH.') else Market.SZ if code.startswith('SZ.') else Market.HK
            ret, data = quote_ctx.get_stock_basicinfo(market, SecurityType.STOCK, [code])
        
        if not is_external_ctx:
            quote_ctx.close()
        
        if ret == RET_OK and not data.empty:
            return data.iloc[0]['stock_name']
        else:
            return code
    except Exception as e:
        # print(f"从富途获取股票名称失败 {code}: {e}")
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
        
        all_dfs = []
        for wl_name in watchlists:
            ret, data = monitor.quote_ctx.get_user_security(group_name=wl_name)
            if ret == RET_OK and not data.empty:
                all_dfs.append(data)
        
        monitor.quote_ctx.close()
        
        if not all_dfs:
            print("所有自选股分组获取失败或为空")
            return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])
        
        # 合并所有分组数据并去重
        data = pd.concat(all_dfs, ignore_index=True)
        data = data.drop_duplicates(subset=['code'])
        
        # data is a pandas DataFrame, convert to our format
        result_df = pd.DataFrame({
            '代码': data['code'],
            '名称': data['name'],
            '最新价': [0.0] * len(data),
            '涨跌幅': [0.0] * len(data)
        })
        
        return result_df[['代码', '名称', '最新价', '涨跌幅']]
    except Exception as e:
        print(f"从富途获取自选股列表失败: {e}")
        return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])

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

def get_tradable_stocks(fallback_stocks=None):
    """
    获取所有可交易的A股股票列表
    
    优先尝试从富途自选股列表获取，如果失败则回退到akshare API，
    如果都失败则使用测试股票列表
    
    Args:
        fallback_stocks: list, 默认回退的股票列表。如果为空则使用内置默认值。
    
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
    
    # 如果所有方法都失败，使用配置中的测试股票列表
    try:
        import yaml
        test_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Config", "test_stocks.yaml")
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
    
    # 最后的备选方案：返回默认的几只股票
    default_stocks_codes = ['000001', '600000', '600519', '000858', '601318']
    default_names = ['平安银行', '浦发银行', '贵州茅台', '五粮液', '中国平安']
    
    if fallback_stocks:
        default_stocks_codes = [s['code'] if isinstance(s, dict) else s for s in fallback_stocks]
        default_names = [s.get('name', f"Stock_{s['code']}") if isinstance(s, dict) else f"Stock_{s}" for s in fallback_stocks]

    return pd.DataFrame({
        '代码': default_stocks_codes,
        '名称': default_names,
        '最新价': [0.0] * len(default_stocks_codes),
        '涨跌幅': [0.0] * len(default_stocks_codes)
    })

def is_us_stock(code: str) -> bool:
    """判断是否为美股代码"""
    return code.upper().startswith("US.")

def get_default_data_sources(code: str) -> list:
    """
    根据股票代码获取默认的建议数据源优先级列表
    
    Args:
        code: 股票代码 (如 US.AAPL, HK.00700, SH.600000)
        
    Returns:
        list: 数据源列表 (DATA_SRC 枚举或字符串)
    """
    from Common.CEnum import DATA_SRC
    from config import API_CONFIG
    import os
    
    # 默认通用列表
    default_sources = ["custom:SQLiteAPI.SQLiteAPI"]
    
    if is_us_stock(code):
        # 美股独家数据源: Schwab
        return [DATA_SRC.SCHWAB]
    else:
        # 港股/A股优先级逻辑
        return [DATA_SRC.FUTU] + default_sources

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
