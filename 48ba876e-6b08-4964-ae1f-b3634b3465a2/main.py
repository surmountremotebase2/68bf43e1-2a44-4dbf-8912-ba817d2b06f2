from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from surmount.technical_indicators import Momentum


class TradingStrategy(Strategy):
    """
    Tactical Global Dual Momentum Strategy

    Enhancements:
    - Composite momentum ranking (12m + 6m + 3m + 1m)
    - Relative Momentum across risk assets
    - Absolute Momentum filter on 12m trend
    - Partial defensive replacement instead of all-or-nothing risk-off
    - Always holds the top 3 ranked opportunities
    """

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

        # --------------------------------------------------
        # Require sufficient history
        # --------------------------------------------------

        if len(ohlcv) < 1:
            allocations["BIL"] = 1.0
            return TargetAllocation(allocations)

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

        composite_scores = {}
        absolute_momentum = {}

        # --------------------------------------------------
        # Momentum Calculation
        # --------------------------------------------------
        #
        # Momentum() returns price change over N bars.
        # We build a weighted composite score:
        #
        # 40% = 12 month
        # 30% = 6 month
        # 20% = 3 month
        # 10% = 1 month
        #
        # Absolute momentum uses only 12-month momentum.
        #
        # --------------------------------------------------

        for ticker in self.assets:

            try:

                mom_252 = Momentum(ticker, ohlcv, length=252)
                mom_126 = Momentum(ticker, ohlcv, length=126)
                mom_63 = Momentum(ticker, ohlcv, length=63)
                mom_21 = Momentum(ticker, ohlcv, length=21)

                if (
                    not mom_252 or
                    not mom_126 or
                    not mom_63 or
                    not mom_21
                ):
                    continue

                m12 = mom_252[-1]
                m6 = mom_126[-1]
                m3 = mom_63[-1]
                m1 = mom_21[-1]

                score = (
                    0.40 * m12 +
                    0.30 * m6 +
                    0.20 * m3 +
                    0.10 * m1
                )

                composite_scores[ticker] = score
                absolute_momentum[ticker] = m12

            except Exception as e:
                log(f"Momentum error for {ticker}: {e}")

        # --------------------------------------------------
        # Safety fallback
        # --------------------------------------------------

        if len(composite_scores) == 0:
            allocations["BIL"] = 1.0
            return TargetAllocation(allocations)

        # --------------------------------------------------
        # Rank risk assets
        # --------------------------------------------------

        ranked_risk = sorted(
            risk_assets,
            key=lambda x: composite_scores.get(x, -999999),
            reverse=True
        )

        ranked_defensive = sorted(
            defensive_assets,
            key=lambda x: composite_scores.get(x, -999999),
            reverse=True
        )

        best_defensive = ranked_defensive[0]

        top3_risk = ranked_risk[:3]

        weights = [0.50, 0.30, 0.20]

        # --------------------------------------------------
        # Dual Momentum Allocation
        # --------------------------------------------------
        #
        # Relative Momentum:
        #   Top 3 risk assets
        #
        # Absolute Momentum:
        #   12m momentum must be positive
        #
        # Otherwise allocate that sleeve
        # to the strongest defensive asset.
        #
        # --------------------------------------------------

        for asset, weight in zip(top3_risk, weights):

            if absolute_momentum.get(asset, -999999) > 0:
                allocations[asset] += weight
            else:
                allocations[best_defensive] += weight

        # --------------------------------------------------
        # Diagnostics
        # --------------------------------------------------

        log(
            f"Top Risk Assets: "
            f"{[(a, round(composite_scores.get(a, 0), 2)) for a in top3_risk]}"
        )

        log(
            f"Best Defensive Asset: "
            f"{best_defensive} "
            f"({round(composite_scores.get(best_defensive, 0), 2)})"
        )

        # --------------------------------------------------
        # Final normalization
        # --------------------------------------------------

        total = sum(allocations.values())

        if total <= 0:
            allocations = {asset: 0.0 for asset in self.assets}
            allocations["BIL"] = 1.0
            return TargetAllocation(allocations)

        allocations = {
            asset: value / total
            for asset, value in allocations.items()
        }

        return TargetAllocation(allocations)