from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import VWAP
from surmount.logging import log


class TradingStrategy(Strategy):
    """
    Enhanced Meb Faber Tactical Asset Allocation

    Features:
    - 100-day VWAP trend filter
    - Separate Risk-On and Risk-Off universes
    - Relative strength ranking
    - Top 3 Risk-On assets only
    - Dynamic regime allocation

    Regimes:

    Strong Risk-On:
        >= 4 Risk-On assets bullish
        -> 100% Risk-On

    Mixed:
        1-3 Risk-On assets bullish
        -> 70% Risk-On
        -> 30% Risk-Off

    Defensive:
        0 Risk-On assets bullish
        -> 100% Risk-Off

    Crisis:
        No bullish assets anywhere
        -> 100% BIL
    """

    @property
    def assets(self):
        return [
            # Risk-On
            "SPY",
            "QQQ",
            "IJT",
            "FEZ",
            "EFA",
            "EEM",
            "VNQ",

            # Risk-Off
            "UUP",
            "TLT",
            "GLD",

            # Cash
            "BIL"
        ]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []

    def run(self, data):

        ohlcv = data["ohlcv"]

        # Need enough history for:
        # VWAP(100)
        # 6-month momentum (~126 trading days)
        if ohlcv is None or len(ohlcv) < 130:
            return TargetAllocation({"BIL": 1.0})

        risk_on = [
            "SPY",
            "QQQ",
            "IJT",
            "FEZ",
            "EFA",
            "EEM",
            "VNQ"
        ]

        risk_off = [
            "UUP",
            "TLT",
            "GLD"
        ]

        bullish_risk_on = []
        bullish_risk_off = []

        # =====================================================
        # RISK-ON SELECTION
        # =====================================================

        for ticker in risk_on:

            try:

                if ticker not in ohlcv[-1]:
                    continue

                latest_close = ohlcv[-1][ticker]["close"]

                if latest_close is None:
                    continue

                vwap = VWAP(ticker, ohlcv, length=100)

                if vwap is None or len(vwap) == 0:
                    continue

                latest_vwap = vwap[-1]

                if latest_vwap is None:
                    continue

                # Trend filter
                if latest_close > latest_vwap:

                    old_close = ohlcv[-126][ticker]["close"]

                    if old_close is None or old_close <= 0:
                        continue

                    momentum = (latest_close / old_close) - 1

                    bullish_risk_on.append(
                        (ticker, momentum)
                    )

            except Exception:
                continue

        # =====================================================
        # RISK-OFF SELECTION
        # =====================================================

        for ticker in risk_off:

            try:

                if ticker not in ohlcv[-1]:
                    continue

                latest_close = ohlcv[-1][ticker]["close"]

                if latest_close is None:
                    continue

                vwap = VWAP(ticker, ohlcv, length=100)

                if vwap is None or len(vwap) == 0:
                    continue

                latest_vwap = vwap[-1]

                if latest_vwap is None:
                    continue

                if latest_close > latest_vwap:

                    old_close = ohlcv[-126][ticker]["close"]

                    if old_close is None or old_close <= 0:
                        continue

                    momentum = (latest_close / old_close) - 1

                    bullish_risk_off.append(
                        (ticker, momentum)
                    )

            except Exception:
                continue

        # =====================================================
        # RANK BY MOMENTUM
        # =====================================================

        bullish_risk_on = sorted(
            bullish_risk_on,
            key=lambda x: x[1],
            reverse=True
        )

        bullish_risk_off = sorted(
            bullish_risk_off,
            key=lambda x: x[1],
            reverse=True
        )

        top_risk_on = bullish_risk_on[:3]

        allocations = {}

        # =====================================================
        # STRONG RISK-ON
        # =====================================================

        if len(bullish_risk_on) >= 4:

            weight = 1.0 / len(top_risk_on)

            for ticker, _ in top_risk_on:
                allocations[ticker] = weight

        # =====================================================
        # MIXED REGIME
        # =====================================================

        elif len(bullish_risk_on) > 0:

            # 70% Risk-On
            risk_on_weight = 0.70 / len(top_risk_on)

            for ticker, _ in top_risk_on:
                allocations[ticker] = risk_on_weight

            # 30% Risk-Off
            if len(bullish_risk_off) > 0:

                defensive_weight = (
                    0.30 / len(bullish_risk_off)
                )

                for ticker, _ in bullish_risk_off:
                    allocations[ticker] = defensive_weight

            else:
                allocations["BIL"] = (
                    allocations.get("BIL", 0) + 0.30
                )

        # =====================================================
        # DEFENSIVE REGIME
        # =====================================================

        else:

            if len(bullish_risk_off) > 0:

                defensive_weight = (
                    1.0 / len(bullish_risk_off)
                )

                for ticker, _ in bullish_risk_off:
                    allocations[ticker] = defensive_weight

            else:

                allocations["BIL"] = 1.0

        # =====================================================
        # FINAL SAFETY NORMALIZATION
        # =====================================================

        total = sum(allocations.values())

        if total <= 0:
            return TargetAllocation({"BIL": 1.0})

        allocations = {
            ticker: weight / total
            for ticker, weight in allocations.items()
        }

        return TargetAllocation(allocations)