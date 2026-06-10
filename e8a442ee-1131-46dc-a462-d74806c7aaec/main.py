from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import VWAP
from surmount.logging import log


class TradingStrategy(Strategy):

    def __init__(self):

        self.signal_ticker = "SPY"
        self.trade_ticker = "QQQ"

        # ATR settings
        self.atr_period = 14

        # Target volatility risk budget
        self.target_risk = 0.01

        # Minimum ATR% required to trade
        self.min_atr_pct = 0.005

    @property
    def assets(self):
        return [self.signal_ticker, self.trade_ticker]

    @property
    def interval(self):
        return "1hour"

    def calculate_atr(self, bars, ticker, period=14):
        """
        Simple ATR calculation using hourly bars.
        """

        if len(bars) < period + 1:
            return None

        trs = []

        try:

            for i in range(-period, 0):

                current = bars[i][ticker]
                previous = bars[i - 1][ticker]

                high = current["high"]
                low = current["low"]
                prev_close = previous["close"]

                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )

                trs.append(tr)

            return sum(trs) / len(trs)

        except Exception:
            return None

    def run(self, data):

        signal = self.signal_ticker
        trade = self.trade_ticker

        ohlcv_list = data["ohlcv"]

        if ohlcv_list is None or len(ohlcv_list) < 1:
            return TargetAllocation({trade: 0})

        if signal not in ohlcv_list[-1]:
            return TargetAllocation({trade: 0})

        current_bar = ohlcv_list[-1][signal]

        current_close = current_bar["close"]
        current_date_str = current_bar["date"].split(" ")[0]

        # =====================================================
        # VWAP FILTER
        # =====================================================

        try:

            vwap_series = VWAP(
                signal,
                ohlcv_list,
                length=250
            )

            if (
                vwap_series is None
                or len(vwap_series) == 0
                or vwap_series[-1] is None
            ):
                return TargetAllocation({trade: 0})

            latest_vwap = vwap_series[-1]

        except Exception as e:

            log(f"VWAP error: {str(e)}")
            return TargetAllocation({trade: 0})

        # =====================================================
        # ATR CALCULATION
        # =====================================================

        atr = self.calculate_atr(
            ohlcv_list,
            signal,
            self.atr_period
        )

        if atr is None or current_close <= 0:
            return TargetAllocation({trade: 0})

        atr_pct = atr / current_close

        # Avoid dead / low-volatility sessions
        if atr_pct < self.min_atr_pct:
            return TargetAllocation({trade: 0})

        # =====================================================
        # CURRENT DAY BARS
        # =====================================================

        current_day_bars = []

        for bar in ohlcv_list:

            if (
                signal in bar
                and bar[signal]["date"].startswith(current_date_str)
            ):
                current_day_bars.append(bar[signal])

        if len(current_day_bars) <= 1:
            return TargetAllocation({trade: 0})

        opening_bar = current_day_bars[0]

        opening_high = opening_bar["high"]
        opening_low = opening_bar["low"]

        # =====================================================
        # ATR OPENING RANGE FILTER
        # =====================================================

        opening_range_pct = (
            opening_high - opening_low
        ) / current_close

        # Avoid chasing already-expanded sessions
        if opening_range_pct > (1 * atr_pct):
            return TargetAllocation({trade: 0})

        # =====================================================
        # ORB ENTRY LOGIC
        # =====================================================

        breakout = False

        if (
            current_close > opening_high
            and current_close > latest_vwap
        ):
            breakout = True

        else:

            prev_bar = current_day_bars[-2]

            if (
                prev_bar["close"] > opening_high
                and current_close > latest_vwap
            ):
                breakout = True

        if not breakout:
            return TargetAllocation({trade: 0})

        # =====================================================
        # ATR POSITION SIZING
        # =====================================================

        allocation = self.target_risk / atr_pct

        allocation = max(0.0, allocation)

        allocation = min(allocation, 1.0)

        log(
            f"ORB Long | "
            f"ATR={atr:.2f} | "
            f"ATR%={atr_pct:.4f} | "
            f"VWAP={latest_vwap:.2f} | "
            f"Allocation={allocation:.2f}"
        )

        return TargetAllocation({
            trade: allocation
        })