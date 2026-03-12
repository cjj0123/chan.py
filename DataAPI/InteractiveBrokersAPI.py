import os
import asyncio
import nest_asyncio
import threading
from datetime import datetime, timedelta
from typing import Generator, List, Optional, Any
from DataAPI.CommonStockAPI import CCommonStockApi
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

# Thread-local storage to reuse IB connections and loops across requests in the same thread
_ib_local = threading.local()

class CInteractiveBrokersAPI(CCommonStockApi):
    def __init__(self, code, k_type, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CInteractiveBrokersAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        
        self.type_map = {
            KL_TYPE.K_1M: '1 min',
            KL_TYPE.K_5M: '5 mins',
            KL_TYPE.K_15M: '15 mins',
            KL_TYPE.K_30M: '30 mins',
            KL_TYPE.K_60M: '1 hour',
            KL_TYPE.K_DAY: '1 day',
            KL_TYPE.K_WEEK: '1 week',
            KL_TYPE.K_MON: '1 month',
        }
        
        self.host = os.getenv("IB_HOST", "127.0.0.1")
        self.port = int(os.getenv("IB_PORT", "4002"))
        
        # Determine fixed clientId for this thread to reuse
        # Using a range to avoid collisions with main trading (10)
        if not hasattr(_ib_local, 'client_id'):
            import random
            _ib_local.client_id = random.randint(50, 499)
        self.client_id = _ib_local.client_id

    def get_kl_data(self) -> Generator[CKLine_Unit, None, None]:
        """
        Connect to IB Gateway and fetch historical data.
        Reuses loop and connection if already established in this thread.
        """
        import sys
        import traceback
        from ib_insync import IB, Stock, util
        from datetime import datetime
        
        try:
            # 1. Ensure loop existence for this thread
            if not hasattr(_ib_local, 'loop') or _ib_local.loop is None or _ib_local.loop.is_closed():
                _ib_local.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_ib_local.loop)
                nest_asyncio.apply(_ib_local.loop)
            
            loop = _ib_local.loop
            
            stock_code = str(self.code).upper()
            if stock_code.startswith("US."):
                symbol = stock_code.split(".")[1]
            else:
                symbol = stock_code
                
            async def fetch_bars():
                # 2. Ensure IB connection existence for this thread
                if not hasattr(_ib_local, 'ib') or _ib_local.ib is None or not _ib_local.ib.isConnected():
                    _ib_local.ib = IB()
                    prefix = f"🔌 [IB-API-{self.client_id}]"
                    print(f"{prefix} Establishing NEW shared connection to {self.host}:{self.port}...")
                    await _ib_local.ib.connectAsync(self.host, self.port, clientId=self.client_id, timeout=10)
                
                ib = _ib_local.ib
                prefix = f"🚀 [IB-API-{self.client_id}]"
                
                try:
                    contract = Stock(symbol, 'SMART', 'USD')
                    await ib.qualifyContractsAsync(contract)
                    
                    bar_size = self.type_map.get(self.k_type, '1 day')
                    if self.begin_date:
                        try:
                            # Support both date formats
                            if ' ' in self.begin_date:
                                start_dt = datetime.strptime(self.begin_date, "%Y-%m-%d %H:%M:%S")
                            else:
                                start_dt = datetime.strptime(self.begin_date, "%Y-%m-%d")
                        except ValueError:
                            start_dt = datetime.now() - timedelta(days=365)
                            
                        try:
                            if self.end_date and ' ' in self.end_date:
                                end_dt = datetime.strptime(self.end_date, "%Y-%m-%d %H:%M:%S")
                            elif self.end_date:
                                end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
                            else:
                                end_dt = datetime.now()
                        except ValueError:
                            end_dt = datetime.now()
                    else:
                        start_dt = datetime.now().replace(year=datetime.now().year - 1)
                        end_dt = datetime.now()

                    def to_naive(dt):
                        if isinstance(dt, datetime):
                            return dt.replace(tzinfo=None) if dt.tzinfo else dt
                        from datetime import date
                        if isinstance(dt, date):
                            return datetime(dt.year, dt.month, dt.day)
                        return dt

                    all_bars = []
                    current_end = to_naive(end_dt)
                    target_start = to_naive(start_dt)

                    while current_end > target_start:
                        # Append explicit timezone to silence IB warning 2174
                        end_str = current_end.strftime('%Y%m%d %H:%M:%S US/Eastern')
                        
                        # Calculate appropriate duration to avoid over-fetching
                        remaining_delta = current_end - target_start
                        remaining_seconds = int(remaining_delta.total_seconds())
                        
                        if remaining_seconds <= 86400:
                            duration_str = f"{remaining_seconds} S"
                        else:
                            # IB rejects "S" for > 86400. Switch to "D".
                            days_needed = (remaining_seconds + 86399) // 86400
                            if self.k_type == KL_TYPE.K_1M:
                                duration_str = f"{min(days_needed, 30)} D"
                            elif self.k_type in [KL_TYPE.K_5M, KL_TYPE.K_15M]:
                                duration_str = f"{min(days_needed, 60)} D"
                            elif self.k_type in [KL_TYPE.K_30M, KL_TYPE.K_60M]:
                                duration_str = f"{min(days_needed, 365)} D"
                            else:
                                duration_str = f"{min(days_needed, 3650)} D"

                        try:
                            # print(f"{prefix} Requesting {symbol} {bar_size} for {duration_str} ending {end_str}")
                            bars = await asyncio.wait_for(
                                ib.reqHistoricalDataAsync(
                                    contract, end_str, duration_str, bar_size, 'TRADES', True, 1, False
                                ),
                                timeout=30
                            )
                        except asyncio.TimeoutError:
                            print(f"⚠️ [IB-API] Request timed out for {symbol}")
                            break

                        if not bars:
                            break
                        
                        all_bars = list(bars) + all_bars
                        earliest = to_naive(bars[0].date)
                        if earliest >= current_end:
                            break
                        current_end = earliest
                        if len(all_bars) > 10000: # Safety break
                            break

                    # Deduplicate and sort
                    seen_times = set()
                    final_bars = []
                    for b in all_bars:
                        b_naive_dt = to_naive(b.date)
                        if b_naive_dt not in seen_times:
                            final_bars.append(b)
                            seen_times.add(b_naive_dt)
                    final_bars.sort(key=lambda x: to_naive(x.date))
                    
                    return [b for b in final_bars if to_naive(b.date) >= target_start]
                except Exception as e:
                    print(f"❌ [IB-API] Error fetching {symbol}: {e}")
                    return []

            # Execute via the shared loop
            bars = None
            try:
                bars = loop.run_until_complete(fetch_bars())
            except Exception as loop_e:
                print(f"❌ [IB-API] Loop error for {stock_code}: {loop_e}", file=sys.stderr)
                # If error, clear the IB instance so it reconnects next time
                if hasattr(_ib_local, 'ib'): _ib_local.ib = None
                return

            if not bars:
                return

            print(f"✅ [IB-API] Received {len(bars)} bars for {stock_code}")
            for bar in bars:
                dt = bar.date
                if not isinstance(dt, datetime):
                    dt = datetime(dt.year, dt.month, dt.day)
                item_dict = {
                    DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                    DATA_FIELD.FIELD_OPEN: float(bar.open),
                    DATA_FIELD.FIELD_HIGH: float(bar.high),
                    DATA_FIELD.FIELD_LOW: float(bar.low),
                    DATA_FIELD.FIELD_CLOSE: float(bar.close),
                    DATA_FIELD.FIELD_VOLUME: float(bar.volume),
                    DATA_FIELD.FIELD_TURNOVER: 0.0,
                    DATA_FIELD.FIELD_TURNRATE: 0.0
                }
                yield CKLine_Unit(item_dict)

        except Exception as e:
            print(f"🔥 [IB-API] FATAL: {e}", file=sys.stderr)
            traceback.print_exc()

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        """Pre-initialize connection if needed (optional)"""
        pass

    @classmethod
    def do_close(cls):
        """Explicitly close the shared connection for this thread if it exists"""
        if hasattr(_ib_local, 'ib') and _ib_local.ib is not None:
            if _ib_local.ib.isConnected():
                print(f"🔌 [IB-API] Closing shared connection for thread {threading.get_ident()}...")
                _ib_local.ib.disconnect()
            _ib_local.ib = None
        if hasattr(_ib_local, 'loop') and _ib_local.loop is not None:
            if not _ib_local.loop.is_closed():
                _ib_local.loop.close()
            _ib_local.loop = None
