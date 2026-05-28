from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.logging import log


class TradingStrategy(Strategy):
    """
    Meb Faber Tactical Asset Allocation Strategy

    Core Logic:
    - Uses a diversified global multi-asset portfolio
    - Invests only in assets trading above their 200-day SMA
    - Assets below their SMA move to cash (SHY)
    - Equal-weight allocation among risk-on assets
    - Monthly-style trend following implemented on daily data

    Strategy Philosophy:
    This is inspired by Meb Faber's classic trend-following model from:
    "A Quantitative Approach to Tactical Asset Allocation"

    Objective:
    Reduce large drawdowns while maintaining exposure to long-term
    global asset trends.
    """

    @property
    def assets(self):
        """
        Tradable universe.

        SPY = US Equities
        EFA = International Developed Equities
        EEM = Emerging Markets
        VNQ = Real Estate
        DBC = Commodities
        TLT = Long-Term Treasuries
        GLD = Gold
        SHY = Short-Term Treasuries / Cash proxy
        """
        return [
            "SPY",
            "EFA",
            "EEM",
            "VNQ",
            "DBC",
            "TLT",
            "GLD",
            "SHY"
        ]

    @property
    def interval(self):
        """
        Daily interval.
        """
        return "1day"

    @property
    def data(self):
        """
        No additional alternative datasets required.
        """
        return []

    def run(self, data):
        """
        Execute strategy logic.

        Rules:
        - If asset close > 200-day SMA:
            allocate equally among qualifying assets
        - Otherwise:
            move capital to SHY (cash equivalent)

        Returns:
            TargetAllocation
        """

        ohlcv = data["ohlcv"]

        # Defensive fallback
        if not ohlcv or len(ohlcv) < 1:
            log("Insufficient historical data")

            return TargetAllocation({
                "SHY": 1.0
            })

        # Risk assets excluding cash proxy
        risk_assets = [
            "SPY",
            "EFA",
            "EEM",
            "VNQ",
            "DBC",
            "TLT",
            "GLD"
        ]

        allocations = {}

        qualified_assets = []

        # ---------------------------------------------------------
        # Trend Filter: Price vs 200-Day SMA
        # ---------------------------------------------------------
        for ticker in risk_assets:

            try:
                sma_200 = SMA(ticker, ohlcv, length=200)

                if sma_200 is None or len(sma_200) == 0:
                    log(f"Missing SMA data for {ticker}")
                    continue

                current_close = ohlcv[-1][ticker]["close"]
                current_sma = sma_200[-1]

                # Trend-following condition
                if current_close > current_sma:
                    qualified_assets.append(ticker)

                    log(
                        f"{ticker}: Bullish trend "
                        f"(Close={current_close:.2f} > SMA200={current_sma:.2f})"
                    )

                else:
                    log(
                        f"{ticker}: Defensive mode "
                        f"(Close={current_close:.2f} <= SMA200={current_sma:.2f})"
                    )

            except Exception as e:
                log(f"Error processing {ticker}: {str(e)}")

        # ---------------------------------------------------------
        # Allocation Engine
        # ---------------------------------------------------------
        if len(qualified_assets) > 0:

            weight = 1.0 / len(qualified_assets)

            for ticker in qualified_assets:
                allocations[ticker] = weight

            log(
                f"Allocating equally across "
                f"{len(qualified_assets)} trending assets"
            )

        else:
            # Full defensive allocation
            allocations["SHY"] = 1.0

            log("No assets in bullish trends - allocating 100% to SHY")

        # ---------------------------------------------------------
        # Final Normalization Safety
        # ---------------------------------------------------------
        total_weight = sum(allocations.values())

        if total_weight <= 0:
            return TargetAllocation({"SHY": 1.0})

        normalized_allocations = {
            asset: weight / total_weight
            for asset, weight in allocations.items()
        }

        return TargetAllocation(normalized_allocations)