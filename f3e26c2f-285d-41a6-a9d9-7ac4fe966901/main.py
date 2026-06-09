from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import VWAP
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the signal asset and the execution asset
        self.signal_ticker = "SPY"
        self.trade_ticker = "QQQ"

    @property
    def assets(self):
        """Returns both assets so the framework fetches OHLCV data for both."""
        return [self.signal_ticker, self.trade_ticker]

    @property
    def interval(self):
        """Using 1-hour intervals for clear intraday opening range definitions."""
        return "1hour"

    def run(self, data):
        """
        Executes the ORB strategy using SPY as the macro/intraday signal mechanism 
        and maps the target allocation execution directly to QQQ.
        """
        ohlcv_list = data["ohlcv"]
        signal = self.signal_ticker
        trade = self.trade_ticker

        # Safe check for basic data presence
        if ohlcv_list is None or len(ohlcv_list) < 1:
            return TargetAllocation({trade: 0})

        # Ensure both tickers exist in the latest data slice to prevent KeyErrors
        if signal not in ohlcv_list[-1] or trade not in ohlcv_list[-1]:
            return TargetAllocation({trade: 0})

        # Gather current candle details for the signal asset (SPY)
        current_bar = ohlcv_list[-1][signal]
        current_close = current_bar["close"]
        current_date_str = current_bar["date"].split(" ")[0]

        # =====================================================
        # 50-BAR VWAP TREND FILTER REGIME (Calculated on SPY)
        # =====================================================
        try:
            vwap_series = VWAP(signal, ohlcv_list, length=100)
            
            if vwap_series is None or len(vwap_series) == 0 or vwap_series[-1] is None:
                log(f"Insufficient or invalid VWAP data for {signal}. Remaining flat.")
                return TargetAllocation({trade: 0})
                
            latest_vwap = vwap_series[-1]
        except Exception as e:
            log(f"Error calculating VWAP indicator: {str(e)}")
            return TargetAllocation({trade: 0})

        # Filter all candles belonging strictly to the current day's session for SPY
        current_day_bars = []
        for bar in ohlcv_list:
            if signal in bar and bar[signal]["date"].startswith(current_date_str):
                current_day_bars.append(bar[signal])

        # Edge Case: If this is the first bar of the day, we are mapping the opening range.
        if len(current_day_bars) <= 1:
            return TargetAllocation({trade: 0})

        # Establish Opening Range limits using SPY's first candle of the day
        opening_bar = current_day_bars[0]
        opening_high = opening_bar["high"]
        opening_low = opening_bar["low"]

        allocation = 0.0

        # =====================================================
        # CORE EXECUTION LOGIC (Signal: SPY -> Allocation: QQQ)
        # =====================================================
        # Note: Keeps your specific '< latest_vwap' logic condition intact from your template.
        if current_close > opening_high and current_close > latest_vwap:
            allocation = 1.0
        else:
            prev_bar = current_day_bars[-2]
            if prev_bar["close"] > opening_high and current_close > latest_vwap:
                allocation = 1.0
            else:
                allocation = 0.0

        # Return target allocation designated entirely to the execution asset (QQQ)
        return TargetAllocation({trade: allocation})