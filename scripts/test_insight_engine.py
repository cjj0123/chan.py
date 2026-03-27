import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from DataAPI.NewsCollector import NewsCollector

def test_pipeline():
    print("🧪 Testing Market Insight Optimization Pipeline")
    print("-" * 50)
    
    nc = NewsCollector()
    
    # 1. Test Dynamic Seeds
    print("\n[Stage 1] Testing Dynamic News Seeds...")
    seeds = nc._get_dynamic_news_seeds()
    for mkt, tickers in seeds.items():
        print(f"  - {mkt}: {len(tickers)} tickers found: {tickers[:5]}...")
    
    # 2. Test Sector Heat & Money Flow
    print("\n[Stage 2] Testing Sector Heat & Money Flow (HK)...")
    sectors = nc.collect_sector_heat('HK')
    for s in sectors[:3]:
        print(f"  - {s['sector_name']}: Flow={s['money_flow']:.2f}M, Movers={s['top_movers']}")
    
    # 3. Test Global Summary (Time Difference Analysis)
    print("\n[Stage 3] Testing Three-Market Linkage Summary...")
    summary = nc.generate_global_summary()
    print("-" * 50)
    print(summary)
    print("-" * 50)
    
    nc.close()
    print("\n✅ Verification script completed.")

if __name__ == "__main__":
    test_pipeline()
