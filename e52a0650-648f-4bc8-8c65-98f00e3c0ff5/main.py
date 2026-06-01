from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.logging import log


class TradingStrategy(Strategy):
    """
    Meb Faber Tactical Asset Allocation Strategy
    --------------------------------------------

    Logic:
    - Multi-asset trend-following portfolio
    - Invest in assets trading above 200-day SMA
    - Allocate equally among qualifying assets
    - Move remaining allocation to SHY (cash proxy)

    Designed specifically to avoid Surmount input stream issues
    caused by missing ticker data inside OHLCV dictionaries.
    """

    @property
    def assets(self):
        """
        Asset universe.
        """
        return [
            "SPY",   # US equities
            "QQQ",
            "IJT",   #Small Caps
            "FEZ",   #EU Equity
            "EFA",   # International equities
            "EEM",   # Emerging markets
            "VNQ",   # Real estate
            "UUP",   # Commodities
            "TLT",   # Long-term treasuries
            "GLD",   # Gold
            "BIL"    # Cash proxy
        ]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []

    def run(self, data):
        """
        Main strategy execution.
        """

        ohlcv = data["ohlcv"]

        # ---------------------------------------------------------
        # Basic Safety Checks
        # ---------------------------------------------------------
        if ohlcv is None or len(ohlcv) < 1:
            log("Not enough historical data")
            return TargetAllocation({"SHY": 1.0})

        risk_assets = [
            "SPY",
            "QQQ",
            "IJT",
            "FEZ",
            "EFA",
            "EEM",
            "VNQ",
            #"DBC",
            "TLT",
            "GLD"
        ]

        qualified_assets = []

        # ---------------------------------------------------------
        # Trend Following Logic
        # ---------------------------------------------------------
        for ticker in risk_assets:

            try:

                # Verify ticker exists in latest OHLCV bar
                if ticker not in ohlcv[-1]:
                    log(f"{ticker} missing from latest OHLCV")
                    continue

                # Get SMA values
                sma = SMA(ticker, ohlcv, length=200)

                if sma is None:
                    log(f"SMA unavailable for {ticker}")
                    continue

                if len(sma) == 0:
                    log(f"Empty SMA series for {ticker}")
                    continue

                latest_sma = sma[-1]

                if latest_sma is None:
                    log(f"Latest SMA is None for {ticker}")
                    continue

                latest_close = ohlcv[-1][ticker]["close"]

                if latest_close is None:
                    log(f"Close price missing for {ticker}")
                    continue

                # Meb Faber Trend Filter
                if latest_close > latest_sma:
                    qualified_assets.append(ticker)

                    #log(
                    #    f"{ticker} bullish "
                    #    f"(Close={latest_close:.2f}, "
                    #    f"SMA200={latest_sma:.2f})"
                    #)

                #else:
                    #log(
                    #    f"{ticker} bearish "
                    #    f"(Close={latest_close:.2f}, "
                    #    f"SMA200={latest_sma:.2f})"
                    #)

            except Exception as e:
                log(f"Error processing {ticker}: {str(e)}")

        # ---------------------------------------------------------
        # Allocation Logic
        # ---------------------------------------------------------
        allocations = {}

        if len(qualified_assets) > 0:

            weight = 1.0 / len(qualified_assets)

            for ticker in qualified_assets:
                allocations[ticker] = weight

            #log(
            #    f"Allocated equally across "
            #    f"{len(qualified_assets)} assets"
            #)

        else:

            # Defensive allocation
            allocations["BIL"] = 1.0

            log("No bullish assets detected")

        # ---------------------------------------------------------
        # Final Weight Validation
        # ---------------------------------------------------------
        total_weight = sum(allocations.values())

        if total_weight <= 0:
            return TargetAllocation({"BIL": 1.0})

        normalized_allocations = {
            k: v / total_weight
            for k, v in allocations.items()
        }

        return TargetAllocation(normalized_allocations)