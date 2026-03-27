#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Insight - NewsCollector v4
Uses AKShare for individual stock news (per-ticker).
Uses Gemini for: quality filtering, sentiment scoring, entity extraction.
Uses Futu for sector heat data.
"""

import akshare as ak
import google.generativeai as genai
from futu import OpenQuoteContext, RET_OK, Market, Plate
from datetime import datetime, timedelta
from collections import defaultdict
import json, hashlib, time

from Trade.db_util import CChanDB
from config import API_CONFIG

# Proxy tickers for news scraping
DEFAULT_NEWS_SEEDS = {
    'CN': ['600519', '000725', '600036', '300750', '601318'],
    'HK': ['00700', '09988', '01810', '03690', '02015'],
    'US': ['AAPL', 'TSLA', 'NVDA', 'MSFT', 'GOOG'],
}

SUMMARY_KEYWORDS = [
    '早报', '晚报', '盘前必读', '收盘必读', '要闻回顾',
    '一周回顾', '今日看点', '盘中速递', '会见', '考察',
    '致辞', '调研', '联播', '快评', '贺信',
]

class NewsCollector:
    def __init__(self):
        self.db = CChanDB()
        self._model = None
        self._futu_ctx = None
        api_key = API_CONFIG.get('GOOGLE_API_KEY')
        if api_key:
            genai.configure(api_key=api_key)
            try:
                # Use a stable model for linkage analysis
                self._model = genai.GenerativeModel('gemini-1.5-flash')
            except Exception as e:
                print(f"⚠️ Gemini init error: {e}")

    def _prune_old_news(self, days=3):
        """Delete news older than X days to keep DB clean."""
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
            self.db.execute_non_query("DELETE FROM market_news WHERE timestamp < ?", (cutoff,))
        except Exception as e:
            print(f"⚠️ Error pruning news: {e}")

    def save_sectors(self, sectors):
        """Save collected sector data to DB."""
        for s in sectors:
            try:
                self.db.record_sector_heat(s)
            except Exception as e:
                print(f"⚠️ Error saving sector: {e}")

    def _get_futu(self):
        if self._futu_ctx is None:
            self._futu_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        return self._futu_ctx

    def _get_dynamic_news_seeds(self):
        """Fetch hot stocks from the '热点_实盘' watchlist."""
        seeds = defaultdict(list)
        try:
            ctx = self._get_futu()
            ret, data = ctx.get_user_security("热点_实盘")
            if ret == RET_OK and not data.empty:
                for _, row in data.iterrows():
                    code = row['code']
                    ticker = code.split('.')[-1]
                    if code.startswith('HK.'): seeds['HK'].append(ticker)
                    elif code.startswith('US.'): seeds['US'].append(ticker)
                    elif code.startswith('SH.') or code.startswith('SZ.'): seeds['CN'].append(ticker)
            
            for mkt in seeds:
                seeds[mkt] = list(set(seeds[mkt]))[:15]
                
            return seeds if seeds else DEFAULT_NEWS_SEEDS
        except Exception as e:
            print(f"⚠️ Error dynamic seeds: {e}")
            return DEFAULT_NEWS_SEEDS

    def _fetch_raw_news(self, seeds=None):
        if seeds is None: seeds = self._get_dynamic_news_seeds()
        raw = []
        cutoff = datetime.now() - timedelta(hours=24)
        for market, ticker_list in seeds.items():
            for ticker in ticker_list:
                try:
                    df = ak.stock_news_em(symbol=ticker)
                    if df is None or df.empty: continue
                    for _, row in df.head(5).iterrows():
                        ts_str = str(row.get('发布时间', ''))
                        try: ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                        except ValueError: ts = datetime.now()
                        if ts < cutoff: continue
                        raw.append({
                            'timestamp': ts_str,
                            'market': market,
                            'title': str(row.get('新闻标题', '')),
                            'content': str(row.get('新闻内容', ''))[:500],
                            'seed': ticker,
                            'source': 'EastMoney',
                        })
                except Exception: pass
        return raw

    def _pre_filter(self, raw_list):
        seen = set()
        result = []
        for item in raw_list:
            title = item['title']
            if len(title) < 10 or any(kw in title for kw in SUMMARY_KEYWORDS): continue
            key = title[:20]
            if key in seen: continue
            seen.add(key)
            result.append(item)
        return result

    def _batch_analyze(self, items):
        if not items: return items
        numbered = "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(items)])
        prompt = f"你是一流分析师。请分析并返回 JSON 数组 (codes, sector, sentiment, linkage, type, keep):\n{numbered}"
        
        # Robust model selection
        model_name_default = self._model.model_name if self._model else 'gemini-1.5-flash'
        for model_name in [model_name_default, 'gemini-1.5-flash', 'gemini-pro']:
            try:
                model = genai.GenerativeModel(model_name)
                resp = model.generate_content(prompt)
                text = resp.text.strip()
                if '```json' in text: text = text.split('```json')[1].split('```')[0]
                elif '```' in text: text = text.split('```')[1].split('```')[0]
                analyses = json.loads(text)
                for a in analyses:
                    idx = a.get('id', 0) - 1
                    if 0 <= idx < len(items):
                        items[idx]['_keep'] = a.get('keep', True)
                        items[idx]['sentiment_score'] = a.get('sentiment', 0.0)
                        items[idx]['symbols'] = ', '.join(a.get('codes', []))
                        items[idx]['sectors'] = a.get('sector', '')
                        items[idx]['linkage'] = a.get('linkage', '')
                        items[idx]['analysis_type'] = a.get('type', '个股异动')
                return items
            except: continue
        return items

    def _post_process(self, items):
        kept = [i for i in items if i.get('_keep', True)]
        groups = defaultdict(list)
        for i in kept: groups[i['title'][:15]].append(i)
        final = []
        for g in groups.values():
            best = max(g, key=lambda x: abs(x.get('sentiment_score', 0)))
            if len(g) > 1: best['title'] = f"[{len(g)}条共振] {best['title']}"
            final.append(best)
        return final

    def _save_news(self, items):
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            cur = conn.cursor()
            for item in items:
                h = hashlib.md5(item['title'].encode()).hexdigest()
                cur.execute("SELECT id FROM market_news WHERE news_hash = ?", (h,))
                if cur.fetchone():
                    if item.get('linkage'):
                        cur.execute("UPDATE market_news SET sectors=?, symbols=?, sentiment_score=?, linkage=?, analysis_type=?, content=? WHERE news_hash=?",
                                    (item.get('sectors'), item.get('symbols'), item.get('sentiment_score'), item.get('linkage'), item.get('analysis_type'), item.get('linkage'), h))
                    continue
                self.db.record_news(item)

    def collect_sector_heat(self, market='HK'):
        ctx = self._get_futu()
        try:
            mkt = Market.HK if market == 'HK' else Market.US
            ret, data = ctx.get_plate_list(mkt, Plate.INDUSTRY)
            if ret != RET_OK: return []
            sectors = []
            for _, row in data.head(10).iterrows():
                plate_code = row['code']
                plate_name = row['plate_name']
                ret_s, ds = ctx.get_plate_stock(plate_code)
                movers = []
                total_turnover = 0.0
                if ret_s == RET_OK and not ds.empty:
                    batch = ds['code'].head(20).tolist()
                    time.sleep(0.1)
                    r_snap, d_snap = ctx.get_market_snapshot(batch)
                    if r_snap == RET_OK and not d_snap.empty:
                        total_turnover = d_snap['turnover'].sum()
                        d_snap = d_snap.sort_values('turnover', ascending=False)
                        for _, stock in d_snap.head(3).iterrows():
                            movers.append(stock.get('stock_name', stock['code']))
                sectors.append({'date': datetime.now().strftime('%Y-%m-%d'), 'market': market, 'sector_name': plate_name, 'money_flow': total_turnover / 1_000_000.0, 'top_movers': ','.join(movers), 'news_count': 0})
            return sectors
        except Exception as e:
            print(f"❌ Sector Heat ({market}): {e}")
            return []

    def generate_global_summary(self):
        try:
            cutoff = (datetime.now() - timedelta(hours=14)).strftime('%Y-%m-%d %H:%M:%S')
            df = self.db.execute_query("SELECT title FROM market_news WHERE timestamp >= ? AND market='US' LIMIT 20", (cutoff,))
            if df.empty: return "无隔夜美股联动资讯"
            context = "\n".join(df['title'].tolist())
            prompt = f"分析以下美股热点并提供3条联动预判 (美股驱动 -> 国内板块 -> 建议):\n{context}"
            model_name_default = self._model.model_name if self._model else 'gemini-1.5-flash'
            for model_name in [model_name_default, 'gemini-1.5-flash', 'gemini-pro']:
                try:
                    model = genai.GenerativeModel(model_name)
                    resp = model.generate_content(prompt)
                    return resp.text.strip()
                except: continue
            return "AI 超时"
        except Exception as e: return f"报告生成失败: {e}"

    def run_cycle(self):
        self._prune_old_news()
        seeds = self._get_dynamic_news_seeds()
        raw = self._fetch_raw_news(seeds)
        filtered = self._pre_filter(raw)
        analyzed = []
        for i in range(0, len(filtered), 15):
            analyzed.extend(self._batch_analyze(filtered[i:i+15]))
        final = self._post_process(analyzed)
        self._save_news(final)
        for m in ['HK', 'US']: self.save_sectors(self.collect_sector_heat(m))

    def close(self):
        if self._futu_ctx: self._futu_ctx.close()

if __name__ == "__main__":
    c = NewsCollector()
    c.run_cycle()
    c.close()
