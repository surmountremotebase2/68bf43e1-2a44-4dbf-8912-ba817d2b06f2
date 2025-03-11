from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import RSI, SMA, Momentum, STDEV
from surmount.logging import log
import pandas as pd

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the assets to trade
        self.tickers = ["NVDA", "MSFT", "GOOGL", "SNOW", "PLTR", "ASML", "TSLA"]
        self.data_list = []  # No additional data sources needed for this strategy

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"  # Daily data for monthly rebalancing

    @property
    def data(self):
        return self.data_list

    def run(self, data):
        # Access OHLCV data
        ohlcv = data["ohlcv"]
        if not ohlcv or len(ohlcv) < 200:  # Ensure sufficient data (200 days for 50/200 MA)
            log("Insufficient data for strategy execution")
            return TargetAllocation({ticker: 0 for ticker in self.tickers})

        allocation_dict = {}
        total_weight = 0

        # Calculate metrics for each ticker
        for ticker in self.tickers:
            # Extract closing prices and volatility
            closes = [day[ticker]["close"] for day in ohlcv if ticker in day]
            if len(closes) < 200:
                allocation_dict[ticker] = 0
                continue

            # Momentum Score (MS) = (3-month + 6-month return) / volatility
            three_month_return = (closes[-1] / closes[-63] - 1) if len(closes) >= 63 else 0  # ~3 months (63 trading days)
            six_month_return = (closes[-1] / closes[-126] - 1) if len(closes) >= 126 else 0  # ~6 months (126 trading days)
            volatility = STDEV(ticker, ohlcv, 20)[-1] / closes[-1] if STDEV(ticker, ohlcv, 20) else 0.01  # Avoid division by zero
            momentum_score = (three_month_return + six_month_return) / max(volatility, 0.01)

            # Initial weight based on inverse volatility (Wi = 1 / σi)
            weight = 1 / max(volatility, 0.01)

            # Adjust weight based on momentum score
            if momentum_score < 0:
                weight *= 0.5  # Reduce exposure by 50% if MS < 0

            # Profit-Taking Rule
            one_month_return = (closes[-1] / closes[-21] - 1) if len(closes) >= 21 else 0  # ~1 month (21 trading days)
            rsi = RSI(ticker, ohlcv, 14)[-1] if RSI(ticker, ohlcv, 14) else 50
            if (ticker in ["TSLA", "NVDA"] and one_month_return > 0.3) or rsi > 80:
                weight *= 0.8  # Take 20% profit by reducing weight

            # Stop-Loss Rule
            peak_price = max(closes)
            price_drop = (peak_price - closes[-1]) / peak_price
            sma_50 = SMA(ticker, ohlcv, 50)[-1] if SMA(ticker, ohlcv, 50) else closes[-1]
            sma_200 = SMA(ticker, ohlcv, 200)[-1] if SMA(ticker, ohlcv, 200) else closes[-1]
            if price_drop >= 0.12 or (sma_50 < sma_200 and sma_50 != closes[-1]):
                weight *= 0.5  # Reduce exposure by 50% or remove temporarily

            # Cap weight to avoid over-allocation
            allocation_dict[ticker] = max(0, min(weight, 1))  # Ensure weight is between 0 and 1
            total_weight += allocation_dict[ticker]

        # Normalize weights to sum between 0 and 1
        if total_weight > 0:
            for ticker in allocation_dict:
                allocation_dict[ticker] /= total_weight / 1.0  # Normalize to sum to 1
                allocation_dict[ticker] = round(allocation_dict[ticker], 4)  # Precision for clarity
        else:
            # If no valid allocations, set all to 0
            allocation_dict = {ticker: 0 for ticker in self.tickers}

        # Log the allocations for debugging
        log(f"Allocations: {allocation_dict}")
        return TargetAllocation(allocation_dict)