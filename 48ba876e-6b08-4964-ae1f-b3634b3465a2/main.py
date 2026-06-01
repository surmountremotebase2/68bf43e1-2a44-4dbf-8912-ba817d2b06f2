from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from surmount.technical_indicators import Momentum
import math


class TradingStrategy(Strategy):

    @property
    def assets(self):
        return [
            # Risk Assets
            "SPY",
            "RSP",
            "QQQ",
            "EEM",
            "VEA",
            "IWM",

            # Defensive Assets
            "TLT",
            "IEF",
            "AGG",
            "GLD",
            "UUP",
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

        allocations = {asset: 0.0 for asset in self.assets}

        risk_assets = [
            "SPY",
            "RSP",
            "QQQ",
            "EEM",
            "VEA",
            "IWM"
        ]

        defensive_assets = [
            "TLT",
            "IEF",
            "AGG",
            "GLD",
            "UUP",
            "BIL"
        ]

        # Need enough history for 6 month momentum
        if len(ohlcv) < 1:
            allocations["BIL"] = 1.0
            return TargetAllocation(allocations)

        composite_scores = {}
        absolute_scores = {}

        for ticker in self.assets:

            try:

                mom_126 = Momentum(ticker, ohlcv, length=126)
                mom_63 = Momentum(ticker, ohlcv, length=63)
                mom_21 = Momentum(ticker, ohlcv, length=21)

                if mom_126 is None or mom_63 is None or mom_21 is None:
                    continue

                m6 = mom_126[-1]
                m3 = mom_63[-1]
                m1 = mom_21[-1]

                if (
                    m6 is None or
                    m3 is None or
                    m1 is None
                ):
                    continue

                if (
                    math.isnan(m6) or
                    math.isnan(m3) or
                    math.isnan(m1)
                ):
                    continue

                # Relative Momentum Ranking Score
                score = (
                    0.50 * m6 +
                    0.30 * m3 +
                    0.20 * m1
                )

                composite_scores[ticker] = score

                # Absolute Momentum Filter
                absolute_scores[ticker] = (
                    0.70 * m6 +
                    0.30 * m3
                )

            except Exception as e:
                log(f"{ticker} error: {e}")

        # Fallback
        if len(composite_scores) < 3:
            allocations["BIL"] = 1.0
            return TargetAllocation(allocations)

        # Rank Risk Assets
        ranked_risk = sorted(
            risk_assets,
            key=lambda x: composite_scores.get(x, -999999),
            reverse=True
        )

        # Rank Defensive Assets
        ranked_defensive = sorted(
            defensive_assets,
            key=lambda x: composite_scores.get(x, -999999),
            reverse=True
        )

        best_defensive = ranked_defensive[0]

        top3 = ranked_risk[:3]

        weights = [0.50, 0.30, 0.20]

        log(f"Top Risk Assets: {top3}")
        log(f"Best Defensive Asset: {best_defensive}")

        for asset, weight in zip(top3, weights):

            absolute_momentum = absolute_scores.get(asset, -999999)

            if absolute_momentum > 0:

                allocations[asset] += weight

                log(
                    f"{asset} "
                    f"ABS={round(absolute_momentum,2)} "
                    f"-> LONG"
                )

            else:

                allocations[best_defensive] += weight

                log(
                    f"{asset} "
                    f"ABS={round(absolute_momentum,2)} "
                    f"-> DEFENSIVE ({best_defensive})"
                )

        total = sum(allocations.values())

        if total <= 0:
            allocations["BIL"] = 1.0
            return TargetAllocation(allocations)

        allocations = {
            asset: weight / total
            for asset, weight in allocations.items()
        }

        return TargetAllocation(allocations)