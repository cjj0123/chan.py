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
        # Using 50-450 range to avoid collisions with main trading (fixed at 10-20)
        if not hasattr(_ib_local, 'client_id'):
            # Use thread name or ID to generate a semi-stable clientId
            import threading
            import hashlib
            thread_name = threading.current_thread().name
            cid_hash = int(hashlib.md5(thread_name.encode()).hexdigest(), 16)
            _ib_local.client_id = 50 + (cid_hash % 400) # Range 50-450
        self.client_id = _ib_local.client_id

    async def _ensure_connection(self):
        """Helper to ensure IB connection in the current event loop"""
        from ib_insync import IB
        loop = asyncio.get_event_loop()
        nest_asyncio.apply(loop)
        
        if not hasattr(_ib_local, 'ib') or _ib_local.ib is None or not _ib_local.ib.isConnected():
            _ib_local.ib = IB()
            prefix = f"🔌 [IB-API-{self.client_id}]"
            print(f"{prefix} Establishing NEW shared connection to {self.host}:{self.port}...")
            await _ib_local.ib.connectAsync(self.host, self.port, clientId=self.client_id, timeout=10)
        return _ib_local.ib

    async def get_kl_data_async(self) -> List[CKLine_Unit]:
        """True async version of K-line fetching"""
        from ib_insync import Stock
        from datetime import datetime
        
        ib = await self._ensure_connection()
        stock_code = str(self.code).upper()
        symbol = stock_code.split(".")[1] if stock_code.startswith("US.") else stock_code
        
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            try:
                await asyncio.wait_for(ib.qualifyContractsAsync(contract), timeout=10)
            except asyncio.TimeoutError:
                print(f"⚠️ [IB-API] Qualification timeout for {symbol}")
            
            bar_size = self.type_map.get(self.k_type, '1 day')
            start_dt = self._parse_date(self.begin_date) if self.begin_date else datetime.now() - timedelta(days=365)
            end_dt = self._parse_date(self.end_date) if self.end_date else datetime.now()

            all_bars = await self._fetch_all_bars_async(ib, contract, start_dt, end_dt, bar_size)
            
            units = []
            for bar in all_bars:
                dt = bar.date
                if not isinstance(dt, datetime):
                    dt = datetime(dt.year, dt.month, dt.day)
                units.append(CKLine_Unit({
                    DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                    DATA_FIELD.FIELD_OPEN: float(bar.open),
                    DATA_FIELD.FIELD_HIGH: float(bar.high),
                    DATA_FIELD.FIELD_LOW: float(bar.low),
                    DATA_FIELD.FIELD_CLOSE: float(bar.close),
                    DATA_FIELD.FIELD_VOLUME: float(bar.volume),
                    DATA_FIELD.FIELD_TURNOVER: 0.0,
                    DATA_FIELD.FIELD_TURNRATE: 0.0
                }))
            return units
        except Exception as e:
            print(f"❌ [IB-API] Async error for {symbol}: {e}")
            return []

    def _parse_date(self, date_str):
        from datetime import datetime
        try:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S") if ' ' in date_str else datetime.strptime(date_str, "%Y-%m-%d")
        except:
            return datetime.now()

    def _to_naive(self, dt):
        from datetime import datetime, date
        if isinstance(dt, datetime):
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        if isinstance(dt, date):
            return datetime(dt.year, dt.month, dt.day)
        return dt

    async def _fetch_all_bars_async(self, ib, contract, start_dt, end_dt, bar_size):
        all_bars = []
        current_end = self._to_naive(end_dt)
        target_start = self._to_naive(start_dt)

        while current_end > target_start:
            end_str = current_end.strftime('%Y%m%d %H:%M:%S US/Eastern')
            remaining_seconds = int((current_end - target_start).total_seconds())
            
            if remaining_seconds <= 86400:
                duration_str = f"{remaining_seconds} S"
            else:
                days_needed = (remaining_seconds + 86399) // 86400
                if self.k_type == KL_TYPE.K_1M: duration_str = f"{min(days_needed, 30)} D"
                elif self.k_type in [KL_TYPE.K_5M, KL_TYPE.K_15M]: duration_str = f"{min(days_needed, 60)} D"
                elif self.k_type in [KL_TYPE.K_30M, KL_TYPE.K_60M]:
                    if days_needed > 365:
                        duration_str = f"{(days_needed + 364) // 365} Y"
                    else:
                        duration_str = f"{days_needed} D"
                else:
                    if days_needed > 365:
                        duration_str = f"{(days_needed + 364) // 365} Y"
                    else:
                        duration_str = f"{days_needed} D"

            try:
                bars = await asyncio.wait_for(
                    ib.reqHistoricalDataAsync(contract, end_str, duration_str, bar_size, 'TRADES', True, 1, False),
                    timeout=30
                )
            except asyncio.TimeoutError:
                break

            if not bars: break
            all_bars = list(bars) + all_bars
            earliest = self._to_naive(bars[0].date)
            if earliest >= current_end: break
            current_end = earliest
            if len(all_bars) > 10000: break

        # Deduplicate and sort
        seen_times = set()
        final_bars = []
        for b in all_bars:
            b_naive_dt = self._to_naive(b.date)
            if b_naive_dt not in seen_times:
                final_bars.append(b)
                seen_times.add(b_naive_dt)
        final_bars.sort(key=lambda x: self._to_naive(x.date))
        return [b for b in final_bars if self._to_naive(b.date) >= target_start]

    def get_kl_data(self) -> Generator[CKLine_Unit, None, None]:
        """
        Legacy generator version. Reuses loop and connection.
        """
        import sys
        
        try:
            if not hasattr(_ib_local, 'loop') or _ib_local.loop is None or _ib_local.loop.is_closed():
                _ib_local.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_ib_local.loop)
                nest_asyncio.apply(_ib_local.loop)
            
            loop = _ib_local.loop
            bars = loop.run_until_complete(self.get_kl_data_async())
            
            if bars:
                for b in bars:
                    yield b

        except Exception as e:
            print(f"🔥 [IB-API] FATAL: {e}", file=sys.stderr)

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
