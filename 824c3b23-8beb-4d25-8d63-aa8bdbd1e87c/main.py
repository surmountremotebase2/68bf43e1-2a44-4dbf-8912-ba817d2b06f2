import pandas as pd
import numpy as np
from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log


class TradingStrategy(Strategy):

    def __init__(self):
        self._assets = ["SPY", "QQQ", "TLT", "IEF", "IAU", "UUP", "BIL"]
        self.risk_assets = ["SPY", "QQQ", "TLT", "IEF", "IAU", "UUP"]
        self.safe_asset = "BIL"

        self.last_alloc = {a: 0.0 for a in self._assets}
        self.last_alloc[self.safe_asset] = 1.0

        self.prev_top_asset = None

    @property
    def assets(self):
        return self._assets

    @property
    def interval(self):
        return "1day"

    # -------------------------------------------------
    # INDICATORS
    # -------------------------------------------------

    def tsi(self, close, period=10):
        diff = close.diff()
        abs_diff = diff.abs()

        ema1 = diff.ewm(span=period).mean()
        ema2 = ema1.ewm(span=period).mean()

        abs1 = abs_diff.ewm(span=period).mean()
        abs2 = abs1.ewm(span=period).mean()

        return ema2 / abs2

    def ichimoku_base(self, high, low, period=26):
        return (high.rolling(period).max() +
                low.rolling(period).min()) / 2

    # -------------------------------------------------
    # MAIN LOGIC
    # -------------------------------------------------

    def run(self, data):

        ohlcv = data["ohlcv"]
        if len(ohlcv) < 60:
            return TargetAllocation(self.last_alloc)

        asset_data = {}

        # -----------------------------
        # STEP 1: Compute signals
        # -----------------------------
        for asset in self.risk_assets:

            df = pd.DataFrame({
                "close": [d[asset]["close"] for d in ohlcv],
                "high":  [d[asset]["high"] for d in ohlcv],
                "low":   [d[asset]["low"] for d in ohlcv],
            }, index=pd.to_datetime([d[asset]["date"] for d in ohlcv]))

            # Weekly & Monthly resampling
            weekly = df.resample("W-FRI").last()
            monthly = df.resample("M").last()

            weekly_tsi = self.tsi(weekly["close"], 10).dropna()
            monthly_tsi = self.tsi(monthly["close"], 10).dropna()

            if len(weekly_tsi) < 10 or len(monthly_tsi) < 4:
                continue

            # Smoothed weekly component
            weekly_smooth = weekly_tsi.rolling(5).mean().dropna()

            # Align lengths safely
            score = (
                0.75 * weekly_smooth.iloc[-1] +
                0.25 * monthly_tsi.iloc[-1]
            )

            # ROC on smoothed weekly component
            if len(weekly_smooth) < 6:
                continue

            roc = (weekly_smooth.iloc[-1] - weekly_smooth.iloc[-5])

            # Ichimoku base (daily)
            base_line = self.ichimoku_base(df["high"], df["low"])
            price = df["close"].iloc[-1]
            base = base_line.iloc[-1]

            if np.isnan(base):
                continue

            # Cloud multiplier (continuous, no filtering)
            if price > base:
                cloud_mult = 1.0
            elif price > base * 0.97:
                cloud_mult = 0.9
            else:
                cloud_mult = 0.7

            asset_data[asset] = {
                "score": score,
                "roc": roc,
                "cloud_mult": cloud_mult
            }

        if len(asset_data) < 2:
            return TargetAllocation(self.last_alloc)

        # -----------------------------
        # STEP 2: Relative normalization
        # -----------------------------
        assets = list(asset_data.keys())

        scores = np.array([asset_data[a]["score"] for a in assets])
        rocs = np.array([asset_data[a]["roc"] for a in assets])

        score_ranks = pd.Series(scores).rank(pct=True).values
        roc_ranks = pd.Series(rocs).rank(pct=True).values

        # -----------------------------
        # STEP 3: Composite strength
        # -----------------------------
        for i, asset in enumerate(assets):
            strength = 0.7 * score_ranks[i] + 0.3 * roc_ranks[i]
            asset_data[asset]["strength"] = strength

        ranked = sorted(
            asset_data.items(),
            key=lambda x: x[1]["strength"],
            reverse=True
        )

        top_asset, top_data = ranked[0]
        second_strength = ranked[1][1]["strength"]

        # -----------------------------
        # STEP 4: Conviction calculation
        # -----------------------------
        spread = top_data["strength"] - second_strength

        strengths = np.array([x[1]["strength"] for x in ranked])
        mean = np.mean(strengths)
        std = np.std(strengths) if np.std(strengths) > 0 else 1.0

        z_score = (top_data["strength"] - mean) / std

        conviction = 0.5 * spread + 0.5 * (z_score / 3.0)
        conviction = max(0.0, min(conviction, 1.0))

        # Persistence boost (reduces turnover noise)
        if self.prev_top_asset == top_asset:
            conviction *= 1.1
            conviction = min(conviction, 1.0)

        # -----------------------------
        # STEP 5: Allocation mapping
        # -----------------------------
        if conviction > 0.6:
            exposure = 1.0
        elif conviction > 0.4:
            exposure = 0.75
        elif conviction > 0.25:
            exposure = 0.5
        elif conviction > 0.1:
            exposure = 0.3
        else:
            exposure = 0.0

        # Apply Ichimoku modifier
        final_exposure = exposure * top_data["cloud_mult"]

        # -----------------------------
        # STEP 6: Allocation construction
        # -----------------------------
        alloc = {a: 0.0 for a in self._assets}
        alloc[top_asset] = float(final_exposure)
        alloc[self.safe_asset] = float(1.0 - final_exposure)

        # Optional: reduce micro-rebalancing
        prev_exposure = self.last_alloc.get(top_asset, 0.0)
        if abs(final_exposure - prev_exposure) < 0.05:
            return TargetAllocation(self.last_alloc)

        self.prev_top_asset = top_asset
        self.last_alloc = alloc

        log(f"Top: {top_asset} | Strength: {round(top_data['strength'],3)} | Conviction: {round(conviction,3)} | Exposure: {round(final_exposure,2)}")

        return TargetAllocation(self.last_alloc)