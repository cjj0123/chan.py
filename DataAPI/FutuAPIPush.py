import pandas as pd
from futu import *
import logging

logger = logging.getLogger(__name__)

class FutuCurKlineHandler(CurKlineHandlerBase):
    """
    Handler for Futu real-time K-line push.
    Dispatches received K-line data to registered callbacks.
    """
    def __init__(self, callback_func):
        """
        :param callback_func: A function that accepts (stock_code, k_type, k_data_dict)
        """
        super().__init__()
        self.callback_func = callback_func

    def on_recv_rsp(self, rsp_pb):
        ret_code, content = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            logger.error(f"[FutuPush] CurKlineHandler error: {content}")
            return RET_ERROR, content
        
        if content is None or content.empty:
            return RET_OK, content

        # content is a DataFrame with K-line data
        for _, row in content.iterrows():
            stock_code = row['code']
            k_type = row.get('k_type', 'unknown') # Note: Futu might use ktype field or SubType in response
            
            # Map Futu response fields to internal DATA_FIELD used by CChan
            # Based on FutuAPI.py implementation
            from Common.CEnum import DATA_FIELD
            from Common.CTime import CTime
            from datetime import datetime
            
            time_str = row['time_key']
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                dt = datetime.strptime(time_str, "%Y-%m-%d")
            
            k_data_dict = {
                DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                DATA_FIELD.FIELD_OPEN: float(row['open']),
                DATA_FIELD.FIELD_HIGH: float(row['high']),
                DATA_FIELD.FIELD_LOW: float(row['low']),
                DATA_FIELD.FIELD_CLOSE: float(row['close']),
                DATA_FIELD.FIELD_VOLUME: float(row['volume']),
                DATA_FIELD.FIELD_TURNOVER: float(row.get('turnover', 0.0)),
                DATA_FIELD.FIELD_TURNRATE: float(row.get('turnover_rate', 0.0))
            }
            
            if self.callback_func:
                self.callback_func(stock_code, k_type, k_data_dict)
                
        return RET_OK, content

class FutuPushManager:
    """
    Manages subscriptions and handlers for Futu real-time push events.
    """
    def __init__(self, quote_ctx: OpenQuoteContext):
        self.quote_ctx = quote_ctx
        self.kline_handler = None
        self.callbacks = []

    def start_kline_push(self, callback_func):
        """
        Starts the K-line push handler with the given callback.
        """
        self.kline_handler = FutuCurKlineHandler(callback_func)
        self.quote_ctx.set_handler(self.kline_handler)
        logger.info("[FutuPush] K-line push handler registered.")

    def subscribe(self, codes: list, subtypes: list):
        """
        Subscribes to real-time push for the given codes and subtypes.
        """
        if not codes or not subtypes:
            return RET_ERROR, "Empty codes or subtypes"
            
        ret, data = self.quote_ctx.subscribe(codes, subtypes, subscribe_push=True)
        if ret == RET_OK:
            logger.info(f"[FutuPush] Subscribed to {codes} for {subtypes}")
        else:
            logger.error(f"[FutuPush] Subscription failed: {data}")
        return ret, data

    def unsubscribe(self, codes: list, subtypes: list):
        """
        Unsubscribes from real-time push.
        """
        ret, data = self.quote_ctx.unsubscribe(codes, subtypes)
        if ret == RET_OK:
            logger.info(f"[FutuPush] Unsubscribed from {codes} for {subtypes}")
        return ret, data
