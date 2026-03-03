#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股历史数据下载脚本
从富途 API 下载历史 K 线数据并保存为 Parquet 格式
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from futu import *
    import pandas as pd
except ImportError as e:
    print(f"❌ 导入失败：{e}")
    print("请确保已安装 futu-api 和 pandas: pip3 install futu-api pandas pyarrow")
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_download.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class HKDataDownloader:
    """港股历史数据下载器"""
    
    # KL 类型映射
    KL_TYPE_MAP = {
        '1M': KLType.K_1M,
        '5M': KLType.K_5M,
        '15M': KLType.K_15M,
        '30M': KLType.K_30M,
        '60M': KLType.K_60M,
        'DAY': KLType.K_DAY,
        'WEEK': KLType.K_WEEK,
        'MON': KLType.K_MON,
    }
    
    # 文件名后缀映射
    FREQ_SUFFIX_MAP = {
        KLType.K_1M: '1M',
        KLType.K_5M: '5M',
        KLType.K_15M: '15M',
        KLType.K_30M: '30M',
        KLType.K_60M: '60M',
        KLType.K_DAY: 'DAY',
        KLType.K_WEEK: 'WEEK',
        KLType.K_MON: 'MON',
    }
    
    def __init__(self, cache_dir: str = "stock_cache"):
        """
        初始化下载器
        
        Args:
            cache_dir: 数据缓存目录
        """
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        
        # 初始化富途报价上下文
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        logger.info("✅ 富途报价上下文初始化成功")
    
    def close(self):
        """关闭连接"""
        if hasattr(self, 'quote_ctx'):
            self.quote_ctx.close()
            logger.info("✅ 富途连接已关闭")
    
    def get_watchlist_codes(self, watchlist_name: str = "港股") -> List[str]:
        """
        获取自选股列表
        
        Args:
            watchlist_name: 自选股组名
            
        Returns:
            股票代码列表
        """
        try:
            ret, data = self.quote_ctx.get_user_security(watchlist_name)
            if ret == RET_OK and len(data) > 0:
                codes = data['code'].tolist()
                logger.info(f"✅ 获取到 {len(codes)} 只股票：{codes[:10]}...")
                return codes
            else:
                logger.warning(f"⚠️ 获取自选股失败：{data}")
                return []
        except Exception as e:
            logger.error(f"❌ 获取自选股异常：{e}")
            return []
    
    def get_lot_size_map(self, codes: List[str]) -> Dict[str, int]:
        """
        批量获取每手股数
        
        Args:
            codes: 股票代码列表
            
        Returns:
            {code: lot_size} 字典
        """
        lot_size_map = {}
        
        # 按市场分组查询
        hk_codes = [c for c in codes if c.startswith('HK.')]
        
        if hk_codes:
            # 分批查询，每批 50 只股票
            for i in range(0, len(hk_codes), 50):
                batch = hk_codes[i:i+50]
                try:
                    ret, data = self.quote_ctx.get_stock_basicinfo(Market.HK, batch)
                    if ret == RET_OK and len(data) > 0:
                        for _, row in data.iterrows():
                            code = row['code']
                            lot_size = row.get('lot_size', 100)
                            lot_size_map[code] = int(lot_size) if lot_size else 100
                    time.sleep(0.5)  # 避免请求过快
                except Exception as e:
                    logger.error(f"❌ 获取 {batch} 每手股数失败：{e}")
        
        logger.info(f"✅ 获取到 {len(lot_size_map)} 只股票的每手股数")
        return lot_size_map
    
    def download_kline(self, code: str, kl_type: KLType, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        下载单只股票的 K 线数据
        
        Args:
            code: 股票代码
            kl_type: K 线类型
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            
        Returns:
            DataFrame 或 None
        """
        try:
            ret, data = self.quote_ctx.get_history_kline(
                code,
                ktype=kl_type,
                start=start_date,
                end=end_date,
                autype=AuType.QFQ  # 前复权
            )
            
            if ret == RET_OK and len(data) > 0:
                logger.info(f"✅ {code} {self.FREQ_SUFFIX_MAP[kl_type]} 下载成功，共 {len(data)} 条记录")
                return data
            else:
                logger.warning(f"⚠️ {code} {self.FREQ_SUFFIX_MAP[kl_type]} 下载失败：{data}")
                return None
                
        except Exception as e:
            logger.error(f"❌ {code} {self.FREQ_SUFFIX_MAP[kl_type]} 下载异常：{e}")
            return None
    
    def save_to_parquet(self, df: pd.DataFrame, code: str, kl_type: KLType) -> str:
        """
        保存数据到 Parquet 文件
        
        Args:
            df: 数据 DataFrame
            code: 股票代码
            kl_type: K 线类型
            
        Returns:
            保存的文件路径
        """
        freq_suffix = self.FREQ_SUFFIX_MAP[kl_type]
        filename = f"{code}_K_{freq_suffix}.parquet"
        filepath = os.path.join(self.cache_dir, filename)
        
        # 保存为 Parquet
        df.to_parquet(filepath, index=False, engine='pyarrow')
        logger.info(f"✅ 数据已保存：{filepath}")
        
        return filepath
    
    def download_all(self, codes: List[str], freqs: List[str], 
                     start_date: str, end_date: str,
                     skip_existing: bool = True) -> Dict[str, Dict[str, str]]:
        """
        批量下载多只股票的多个频率数据
        
        Args:
            codes: 股票代码列表
            freqs: 频率列表 ['30M', '5M', 'DAY']
            start_date: 开始日期
            end_date: 结束日期
            skip_existing: 是否跳过已存在的文件
            
        Returns:
            {code: {freq: filepath}} 字典
        """
        saved_files = {}
        
        for code in codes:
            saved_files[code] = {}
            
            for freq in freqs:
                if freq not in self.KL_TYPE_MAP:
                    logger.warning(f"⚠️ 未知频率：{freq}")
                    continue
                
                kl_type = self.KL_TYPE_MAP[freq]
                freq_suffix = self.FREQ_SUFFIX_MAP[kl_type]
                filename = f"{code}_K_{freq_suffix}.parquet"
                filepath = os.path.join(self.cache_dir, filename)
                
                # 检查是否已存在
                if skip_existing and os.path.exists(filepath):
                    logger.info(f"⏭️ 跳过已存在的文件：{filepath}")
                    saved_files[code][freq] = filepath
                    continue
                
                # 下载数据
                df = self.download_kline(code, kl_type, start_date, end_date)
                
                if df is not None:
                    filepath = self.save_to_parquet(df, code, kl_type)
                    saved_files[code][freq] = filepath
                
                # 避免请求过快
                time.sleep(0.3)
        
        return saved_files


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='港股历史数据下载工具')
    parser.add_argument('--watchlist', type=str, default='港股', help='自选股组名')
    parser.add_argument('--start', type=str, required=True, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=True, help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--freqs', type=str, nargs='+', default=['30M', '5M', 'DAY'], 
                        help='频率列表')
    parser.add_argument('--cache-dir', type=str, default='stock_cache', help='缓存目录')
    parser.add_argument('--overwrite', action='store_true', help='覆盖已存在的文件')
    parser.add_argument('--limit', type=int, default=0, help='限制下载股票数量 (0=不限制)')
    
    args = parser.parse_args()
    
    # 创建下载器
    downloader = HKDataDownloader(cache_dir=args.cache_dir)
    
    try:
        # 获取自选股
        codes = downloader.get_watchlist_codes(args.watchlist)
        
        if not codes:
            logger.error("❌ 未获取到任何股票代码")
            return 1
        
        # 限制数量
        if args.limit > 0:
            codes = codes[:args.limit]
            logger.info(f"📌 限制下载前 {args.limit} 只股票")
        
        # 批量下载
        logger.info(f"🚀 开始下载 {len(codes)} 只股票的数据...")
        logger.info(f"📅 日期范围：{args.start} 至 {args.end}")
        logger.info(f"📊 频率：{args.freqs}")
        
        saved_files = downloader.download_all(
            codes=codes,
            freqs=args.freqs,
            start_date=args.start,
            end_date=args.end,
            skip_existing=not args.overwrite
        )
        
        # 统计结果
        total_files = sum(len(files) for files in saved_files.values())
        logger.info(f"✅ 下载完成！共保存 {total_files} 个文件")
        
        # 保存每手股数配置
        lot_size_map = downloader.get_lot_size_map(codes)
        import json
        lot_size_file = os.path.join(args.cache_dir, 'lot_size_config.json')
        with open(lot_size_file, 'w', encoding='utf-8') as f:
            json.dump(lot_size_map, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ 每手股数配置已保存：{lot_size_file}")
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("⚠️ 用户中断下载")
        return 1
    except Exception as e:
        logger.error(f"❌ 下载过程异常：{e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        downloader.close()


if __name__ == '__main__':
    sys.exit(main())
