import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.UniversalBacktester import UniversalBacktester

def main():
    tester = UniversalBacktester(market='HK', watchlist=['HK.00700'], sell_freq='5M', use_ml=True, enable_quick_retreat=False, atr_stop_trail=999.0)
    
    original_get_signal = getattr(sys.modules['backtesting.backtester'].BacktestStrategyAdapter, 'get_signal')
    
    def debug_get_signal(self, code, klines_data, lot_size_map):
        res = original_get_signal(self, code, klines_data, lot_size_map)
        
        main_klines = klines_data.get(self.freq)
        if main_klines:
            chan_main = self._prepare_chan_instance(code, main_klines, self.freq)
            if chan_main:
                internal_time = chan_main[0][-1][-1].time
                print(f"[{main_klines[-1].timestamp}] {self.freq} input_time: {main_klines[-1].timestamp}, Internal Chan Time: {internal_time}")
        return res
        
    sys.modules['backtesting.backtester'].BacktestStrategyAdapter.get_signal = debug_get_signal
    
    tester.run(required_freqs=['30M', '5M', 'DAY'])

if __name__ == '__main__':
    main()
