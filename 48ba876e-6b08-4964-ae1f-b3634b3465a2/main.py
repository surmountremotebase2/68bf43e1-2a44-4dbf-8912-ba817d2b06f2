from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log


class TradingStrategy(Strategy):
    """
    Tactical Global Dual Momentum Strategy

    Based on Gary Antonacci's Dual Momentum framework:

    1. Absolute Momentum:
       - Asset must have positive 12-month momentum.
       - Otherwise capital moves to defensive assets.

    2. Relative Momentum:
       - Rank all risk assets by 12-month total return.
       - Allocate to strongest assets.

    3. Risk-Off Regime:
       - If most risk assets have negative momentum,
         rotate into defensive assets ranked by momentum.

    Universe includes:
    - US Equities
    - International Equities
    - Bonds
    - Gold
    - Dollar

    Designed for monthly-style tactical allocation while
    running daily inside Surmount.
    """

    @property
    def assets(self):
        return [
            # Risk Assets
            "SPY",   # S&P 500
            "RSP",   # Equal Weight S&P 500
            "QQQ",   # Nasdaq 100
            "EEM",   # Emerging Markets
            "VEA",   # Developed Markets
            "IWM",   # Russell 2000

            # Defensive Assets
            "TLT",   # Long Treasury
            "IEF",   # Intermediate Treasury
            "AGG",   # Aggregate Bond
            "GLD",   # Gold
            "UUP",   # US Dollar
            "SHY"    # Short Treasury / Cash Proxy
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

        # Need roughly 12 months of trading history
        if len(ohlcv) < 1:
            allocations["SHY"] = 1.0
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
            "SHY"
        ]

        momentum = {}

        # --------------------------------------------------
        # 12-Month Momentum Calculation
        # --------------------------------------------------
        for ticker in self.assets:

            try:
                current_price = ohlcv[-1][ticker]["close"]
                price_252d = ohlcv[-252][ticker]["close"]

                if (
                    current_price is None
                    or price_252d is None
                    or price_252d <= 0
                ):
                    continue

                mom = (current_price / price_252d) - 1.0
                momentum[ticker] = mom

            except Exception:
                continue

        # Safety fallback
        if len(momentum) == 0:
            allocations["SHY"] = 1.0
            return TargetAllocation(allocations)

        # --------------------------------------------------
        # Absolute Momentum Filter
        # --------------------------------------------------
        positive_risk_assets = [
            a for a in risk_assets
            if momentum.get(a, -999) > 0
        ]

        # --------------------------------------------------
        # RISK-ON REGIME
        # --------------------------------------------------
        if len(positive_risk_assets) >= 3:

            ranked = sorted(
                positive_risk_assets,
                key=lambda x: momentum[x],
                reverse=True
            )

            top_assets = ranked[:3]

            #log(f"Risk-On regime detected")
            log(f"Top assets: {top_assets}")

            weights = [0.50, 0.30, 0.20]

            for asset, weight in zip(top_assets, weights):
                allocations[asset] = weight

        # --------------------------------------------------
        # RISK-OFF REGIME
        # --------------------------------------------------
        else:

            ranked_defensive = sorted(
                defensive_assets,
                key=lambda x: momentum.get(x, -999),
                reverse=True
            )

            top_defensive = ranked_defensive[:3]

            #log("Risk-Off regime detected")
            log(f"Top defensive assets: {top_defensive}")

            weights = [0.50, 0.30, 0.20]

            for asset, weight in zip(top_defensive, weights):
                allocations[asset] = weight

        # --------------------------------------------------
        # Final normalization
        # --------------------------------------------------
        total = sum(allocations.values())

        if total <= 0:
            allocations = {asset: 0.0 for asset in self.assets}
            allocations["SHY"] = 1.0
            return TargetAllocation(allocations)

        allocations = {
            asset: weight / total
            for asset, weight in allocations.items()
        }

        return TargetAllocation(allocations)