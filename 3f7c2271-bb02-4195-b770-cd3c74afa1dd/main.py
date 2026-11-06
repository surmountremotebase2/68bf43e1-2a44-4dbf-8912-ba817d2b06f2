import math
import pandas as pd
import pandas_ta as ta

from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log


class TradingStrategy(Strategy):
    """
    Daily ADX Directional Movement ETF Rotation.

    Rules:
      1. +DI > -DI: ETF is in a bullish directional regime.
      2. +DI < -DI: ETF is excluded.
      3. Rank eligible ETFs by highest +DI.
      4. Allocate equally to the top 5 ETFs.

    Optional:
      MIN_ADX = None: Pure DI crossover strategy.
      MIN_ADX = 20: Require minimum ADX trend strength.
    """

    ADX_LENGTH = 14
    TOP_N = 5
    MIN_ADX = None

    def __init__(self):
        self.tickers = [
            # US broad / size / style
            "SPY", "QQQ", "DIA", "IWM", "MDY", "IJR",
            "IJH", "VTI", "RSP", "IWD", "IWF", "VTV",

            # SPDR sectors
            "XLB", "XLE", "XLF", "XLI", "XLK", "XLP",
            "XLU", "XLV", "XLY", "XLC", "XLRE",

            # Industries
            "SMH", "XBI", "IBB", "KRE", "XRT", "XHB",
            "OIH", "XOP", "ITA", "IGV", "XME", "IYR",

            # International developed
            "EFA", "EWJ", "EWG", "EWU", "EWQ",
            "EWA", "EWC", "EWL", "VGK",

            # Emerging markets
            "EEM", "EWZ", "FXI", "EWY", "EWT",
            "INDA", "EWW", "EZA",

            # Bonds
            "TLT", "IEF", "SHY", "AGG", "LQD", "HYG",
            "TIP", "MUB", "EMB", "IEI", "MBB",

            # Commodities, FX and other
            "GLD", "SLV", "USO", "UNG", "DBC", "DBA",
            "UUP", "GDX", "FXE", "FXY", "GDXJ", "VNQ",
            "DBB", "SCHD",
        ]

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []

    def calculate_directional_indicators(self, ticker, ohlcv):
        """
        Calculate +DI, -DI and ADX using Wilder's smoothing
        through pandas_ta.

        Returns the latest indicator values or None.
        """

        high = []
        low = []
        close = []

        for bar in ohlcv:
            if ticker not in bar:
                continue

            candle = bar[ticker]

            try:
                h = float(candle["high"])
                l = float(candle["low"])
                c = float(candle["close"])

                if not all(math.isfinite(v) for v in (h, l, c)):
                    continue

                high.append(h)
                low.append(l)
                close.append(c)

            except (KeyError, TypeError, ValueError):
                continue

        length = self.ADX_LENGTH

        # ADX requires additional observations for initialization.
        if len(close) < 2 * length:
            return None

        high_series = pd.Series(high, dtype=float)
        low_series = pd.Series(low, dtype=float)
        close_series = pd.Series(close, dtype=float)

        try:
            indicators = ta.adx(
                high=high_series,
                low=low_series,
                close=close_series,
                length=length
            )

            if indicators is None or indicators.empty:
                return None

            plus_di = indicators["DMP_" + str(length)].iloc[-1]
            minus_di = indicators["DMN_" + str(length)].iloc[-1]
            adx = indicators["ADX_" + str(length)].iloc[-1]

            if pd.isna(plus_di) or pd.isna(minus_di) or pd.isna(adx):
                return None

            return {
                "plus_di": float(plus_di),
                "minus_di": float(minus_di),
                "adx": float(adx)
            }

        except (KeyError, ValueError, TypeError, IndexError) as e:
            log("Indicator calculation failed for {}: {}".format(
                ticker, str(e)
            ))
            return None

    def run(self, data):

        ohlcv = data.get("ohlcv", [])

        if not ohlcv:
            return TargetAllocation({})

        eligible = []

        # Evaluate all ETFs independently.
        for ticker in self.tickers:

            indicators = self.calculate_directional_indicators(
                ticker, ohlcv
            )

            if indicators is None:
                continue

            plus_di = indicators["plus_di"]
            minus_di = indicators["minus_di"]
            adx = indicators["adx"]

            # Entry / exit regime:
            # +DI above -DI means the latest directional crossover
            # regime is bullish. Below means exit.
            if plus_di <= minus_di:
                continue

            # Optional ADX trend-strength filter.
            if self.MIN_ADX is not None and adx < self.MIN_ADX:
                continue

            eligible.append({
                "ticker": ticker,
                "plus_di": plus_di,
                "minus_di": minus_di,
                "adx": adx
            })

        # No bullish ETFs: remain fully in cash.
        if not eligible:
            log("ADX strategy: No eligible ETFs.")
            return TargetAllocation({})

        # Rank by strongest positive directional movement.
        eligible.sort(
            key=lambda x: x["plus_di"],
            reverse=True
        )

        # Select the strongest five.
        selected = eligible[:self.TOP_N]

        # Equal-weight allocation.
        weight = 1.0 / len(selected)

        allocation = {
            item["ticker"]: weight
            for item in selected
        }

        log(
            "ADX selected ETFs: {}".format(
                [
                    (
                        x["ticker"],
                        round(x["plus_di"], 2),
                        round(x["adx"], 2)
                    )
                    for x in selected
                ]
            )
        )

        return TargetAllocation(allocation)