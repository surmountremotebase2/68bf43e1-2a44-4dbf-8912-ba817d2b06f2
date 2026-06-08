from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import VWAP
from surmount.logging import log


class TradingStrategy(Strategy):

    def __init__(self):
        self.signal_ticker = "QQQ"
        self.trade_ticker = "TQQQ"

    @property
    def assets(self):
        return ["QQQ", "TQQQ"]

    @property
    def interval(self):
        return "1hour"

    def run(self, data):

        ohlcv = data["ohlcv"]

        if ohlcv is None or len(ohlcv) < 60:
            return TargetAllocation({"TQQQ": 0})

        try:
            qqq_vwap = VWAP(
                self.signal_ticker,
                ohlcv,
                length=50
            )

            if (
                qqq_vwap is None
                or len(qqq_vwap) == 0
                or qqq_vwap[-1] is None
            ):
                return TargetAllocation({"TQQQ": 0})

        except Exception as e:
            log(f"VWAP error: {str(e)}")
            return TargetAllocation({"TQQQ": 0})

        current_date = (
            ohlcv[-1][self.signal_ticker]["date"]
            .split(" ")[0]
        )

        current_day_bars = []

        for bar in ohlcv:
            if (
                self.signal_ticker in bar
                and bar[self.signal_ticker]["date"].startswith(current_date)
            ):
                current_day_bars.append(bar[self.signal_ticker])

        if len(current_day_bars) < 2:
            return TargetAllocation({"TQQQ": 0})

        opening_bar = current_day_bars[0]

        opening_high = opening_bar["high"]
        opening_low = opening_bar["low"]

        latest_bar = current_day_bars[-1]

        current_close = latest_bar["close"]

        latest_vwap = qqq_vwap[-1]

        breakout_confirmed = False

        for bar in current_day_bars[1:]:

            if (
                bar["close"] > opening_high
                and bar["close"] > latest_vwap
            ):
                breakout_confirmed = True

            if breakout_confirmed and bar["close"] < opening_low:
                breakout_confirmed = False

        allocation = 0.0

        if breakout_confirmed:

            if (
                current_close > opening_low
                and current_close > latest_vwap
            ):
                allocation = 1.0

        return TargetAllocation(
            {
                self.trade_ticker: allocation
            }
        )