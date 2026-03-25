#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Insight - NewsCollector v3
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

# ── Proxy tickers for news scraping ──────────────────────────
# These are used as seeds to fetch related news from EastMoney.
# News titles are then re-analyzed by Gemini to extract ACTUAL related tickers.
NEWS_SEEDS = {
    'CN': ['600519', '000725', '600036', '300750', '601318'],
    'HK': ['00700', '09988', '01810', '03690', '02015'],
    'US': ['AAPL', 'TSLA', 'NVDA', 'MSFT', 'GOOG'],
}

# Keywords that indicate a "summary / aggregation" article (should be filtered)
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
                self._model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
            except Exception as e:
                print(f"⚠️ Gemini init error: {e}")

    # ── Futu Context ──────────────────────────────────────────
    def _get_futu(self):
        if self._futu_ctx is None:
            self._futu_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        return self._futu_ctx

    # ── 1. Fetch raw news from AKShare (per-seed ticker) ─────
    def _fetch_raw_news(self):
        raw = []
        cutoff = datetime.now() - timedelta(hours=24)
        for market, seeds in NEWS_SEEDS.items():
            for seed in seeds:
                try:
                    df = ak.stock_news_em(symbol=seed)
                    if df is None or df.empty:
                        continue
                    for _, row in df.head(8).iterrows():
                        ts_str = str(row.get('发布时间', ''))
                        # Parse timestamp and enforce 24h window
                        try:
                            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            ts = datetime.now()  # fallback
                        if ts < cutoff:
                            continue
                        raw.append({
                            'timestamp': ts_str,
                            'market': market,
                            'title': str(row.get('新闻标题', '')),
                            'content': str(row.get('新闻内容', ''))[:500],
                            'seed': seed,
                            'source': 'EastMoney',
                        })
                except Exception:
                    pass
        return raw

    # ── 2. Pre-filter: length, summary, dedup ────────────────
    def _pre_filter(self, raw_list):
        seen = set()
        result = []
        for item in raw_list:
            title = item['title']
            # Too short
            if len(title) < 12:
                continue
            # Summary / aggregation article
            if any(kw in title for kw in SUMMARY_KEYWORDS):
                continue
            # Fuzzy dedup (first 18 chars)
            key = title[:18]
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    # ── 3. Gemini: Batch analyze (quality + sentiment + codes)
    def _batch_analyze(self, items):
        """Use ONE Gemini call to analyze up to 15 news items at once."""
        if not self._model or not items:
            return items

        # Build a numbered list for the prompt
        lines = []
        for i, item in enumerate(items):
            lines.append(f"{i+1}. {item['title']}")
        numbered = "\n".join(lines)

        prompt = f"""你是一个资深金融分析师。请逐条分析以下 {len(items)} 条新闻：

{numbered}

对每一条返回 JSON 数组中的一个元素，格式如下：
[
  {{
    "id": 1,
    "keep": true,
    "codes": ["贵州茅台", "600519"],
    "sector": "白酒"
  }},
  ...
]

规则：
• keep=false 的条件：(a) 政治/领导活动 (b) 过于简短无实质 (c) 广告 (d) 汇总类/早报类
• codes: 从新闻标题中提取出的【实际相关的】股票名称或代码，没有则为空数组
• sector: 相关行业板块名，没有则为空字符串

只返回 JSON 数组，不要说明。"""

        try:
            resp = self._model.generate_content(prompt)
            text = resp.text.strip()
            # Extract JSON from possible markdown fencing
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0]
            elif '```' in text:
                text = text.split('```')[1].split('```')[0]
            analyses = json.loads(text)

            # Merge analysis back into items
            for a in analyses:
                idx = a.get('id', 0) - 1
                if 0 <= idx < len(items):
                    items[idx]['_keep'] = a.get('keep', True)
                    items[idx]['sentiment_score'] = 0.0 # Disabled as per user request
                    items[idx]['symbols'] = ', '.join(a.get('codes', []))
                    items[idx]['sectors'] = a.get('sector', '')
        except Exception as e:
            print(f"⚠️ Batch analysis error: {e}")
            # Fallback: keep all, zero score
            for item in items:
                item.setdefault('_keep', True)
                item.setdefault('sentiment_score', 0.0)
                item.setdefault('symbols', item.get('seed', ''))
                item.setdefault('sectors', '')

        return items

    # ── 4. Post-filter: drop rejected, merge per-stock ───────
    def _post_process(self, items):
        # Drop items Gemini flagged as low quality
        kept = [i for i in items if i.get('_keep', True)]

        # Group by extracted stock code (first code) for merging
        groups = defaultdict(list)
        ungrouped = []
        for item in kept:
            codes = item.get('symbols', '').strip()
            if codes:
                primary = codes.split(',')[0].strip()
                groups[primary].append(item)
            else:
                ungrouped.append(item)

        merged = []
        for code, group in groups.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                # Merge: pick the one with the highest absolute sentiment
                best = max(group, key=lambda x: abs(x.get('sentiment_score', 0)))
                # Append count hint
                best['title'] = f"[{len(group)}条] {best['title']}"
                merged.append(best)

        # Add ungrouped items
        merged.extend(ungrouped)
        return merged

    # ── 5. Save to DB ────────────────────────────────────────
    def _save_news(self, items):
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            cur = conn.cursor()
            for item in items:
                h = hashlib.md5(item['title'].encode()).hexdigest()
                cur.execute("SELECT id FROM market_news WHERE news_hash = ?", (h,))
                if cur.fetchone():
                    continue
                item['news_hash'] = h
                self.db.record_news(item)

    # ── 6. Sector heat (Futu) ────────────────────────────────
    def collect_sector_heat(self, market='HK'):
        ctx = self._get_futu()
        try:
            mkt = Market.HK if market == 'HK' else Market.US
            ret, data = ctx.get_plate_list(mkt, Plate.INDUSTRY)
            if ret != RET_OK:
                return []
            sectors = []
            for _, row in data.head(10).iterrows():
                ret_s, ds = ctx.get_plate_stock(row['code'])
                movers = ''
                if ret_s == RET_OK and not ds.empty:
                    if 'stock_name' in ds.columns:
                        movers = ','.join(ds['stock_name'].head(3).tolist())
                    elif 'code' in ds.columns:
                        movers = ','.join(ds['code'].head(3).tolist())
                sectors.append({
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'market': market,
                    'sector_name': row['plate_name'],
                    'money_flow': 0.0,
                    'top_movers': movers,
                    'news_count': 0,
                })
            return sectors
        except Exception as e:
            print(f"❌ Sector Heat ({market}): {e}")
            return []

    def save_sectors(self, sector_list):
        for item in (sector_list or []):
            self.db.record_sector_heat(item)

    # ── Main Cycle ───────────────────────────────────────────
    def _prune_old_news(self, days=3):
        import sqlite3
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("DELETE FROM market_news WHERE timestamp < ?", (cutoff,))
            conn.commit()

    def run_cycle(self):
        print(f"🚀 [NewsCollector] Cycle start: {datetime.now()}")
        # Optional: Auto-prune news older than 3 days to keep DB clean
        self._prune_old_news(days=3)
        # Step 1: Fetch
        raw = self._fetch_raw_news()
        print(f"   📥 Raw news fetched: {len(raw)}")
        # Step 2: Pre-filter
        filtered = self._pre_filter(raw)
        print(f"   🔍 After pre-filter: {len(filtered)}")
        # Step 3: Batch AI analysis (process in chunks of 15)
        analyzed = []
        for i in range(0, len(filtered), 15):
            chunk = filtered[i:i+15]
            analyzed.extend(self._batch_analyze(chunk))
        # Step 4: Post-process (merge per-stock)
        final = self._post_process(analyzed)
        print(f"   ✅ Final high-quality: {len(final)}")
        # Step 5: Save
        self._save_news(final)
        # Step 6: Sectors
        self.save_sectors(self.collect_sector_heat('HK'))
        self.save_sectors(self.collect_sector_heat('US'))
        print(f"✅ [NewsCollector] Cycle done.")

    def close(self):
        if self._futu_ctx:
            self._futu_ctx.close()


if __name__ == "__main__":
    c = NewsCollector()
    c.run_cycle()
    c.close()
