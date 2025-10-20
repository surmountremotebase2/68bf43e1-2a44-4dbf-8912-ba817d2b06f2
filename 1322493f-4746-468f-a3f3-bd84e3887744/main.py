import pandas as pd
import numpy as np
from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log

class TradingStrategy(Strategy):
    """
    This strategy implements the ROARScore methodology, a comprehensive market timing model.
    It analyzes the SPY ETF to generate a score based on trend-following, momentum,
    and volatility metrics over multiple timeframes (20, 50, and 150 days).

    The final "ROAR Score" determines the allocation between SPY (risk-on) and BIL
    (risk-off). A higher score leads to a greater allocation in SPY, while a lower
    score shifts capital to the safety of BIL. Rebalancing occurs weekly.
    """
    def __init__(self):
        # Define the assets for the strategy: SPY for equity and BIL for cash management.
        self._assets = ["SPY", "BIL"]
        
        # Set rebalance day (0=Monday, 1=Tuesday, etc.)
        self.rebalance_day = 1  # Tuesday

        # State variables to hold information between runs
        self.raw_roar_scores = []
        self.last_alloc = {"SPY": 0.0, "BIL": 1.0}

    @property
    def assets(self):
        """The list of assets this strategy trades."""
        return self._assets

    @property
    def interval(self):
        """The data interval required for the strategy."""
        return "1day"

    # ----------------------
    # Helper functions for ROAR Score Calculation
    # These are adapted from the provided ROARScore script.
    # ----------------------

    def get_ma_rating_by_curvature(self, ma_series):
        """Generates a Buy/Sell/Hold rating based on the slope and curvature of a moving average."""
        if len(ma_series.dropna()) < 10:
            return "Hold"

        slope = ma_series.diff()
        accel = slope.diff()

        current_slope = slope.iloc[-1]
        current_accel = accel.iloc[-1]
        recent_accel = accel.iloc[-3:].mean()

        if pd.isna(current_slope) or pd.isna(current_accel):
            return "Hold"

        if current_slope > 0.1 and current_accel > 0.05 and recent_accel > 0:
            return "Buy"
        elif current_slope < -0.1 or (current_accel < -0.05 and recent_accel < -0.02):
            return "Sell"
        else:
            return "Hold"

    def calc_ma_score(self, rating):
        """Converts a Buy/Sell/Hold rating to a numerical score."""
        return {"Buy": 5, "Hold": 2, "Sell": 0}.get(rating, 2)

    def get_direction_category_slope(self, ma_series, period):
        """Classifies trend direction and acceleration using dynamic thresholds."""
        if len(ma_series.dropna()) < period:
            return "Average"

        slope = ma_series.diff()
        accel = slope.diff()

        current_slope = slope.iloc[-1]
        current_accel = accel.iloc[-1]

        if pd.isna(current_slope) or pd.isna(current_accel):
            return "Average"

        # Use historical slope values to set dynamic thresholds
        slope_window = slope.dropna().iloc[-512:]
        slope_threshold_strong = slope_window.quantile(0.65)
        slope_threshold_weak = slope_window.quantile(0.35)

        if current_slope > slope_threshold_strong:
            return "Strongest"
        elif current_slope < slope_threshold_weak and current_accel < -0.05:
            return "Weakest"
        elif current_slope < slope_threshold_weak and current_accel > 0.05:
            return "Strengthening"
        elif current_slope > slope_threshold_strong and current_accel < -0.05:
            return "Weakening"
        else:
            return "Average"

    def calc_dir_score(self, rating, direction):
        """Maps trend direction to a score, conditioned by the overall rating."""
        if rating == "Buy":
            return {"Strongest": 5, "Strengthening": 4, "Average": 2, "Weakening": 1, "Weakest": 0}.get(direction, 2)
        elif rating == "Hold":
            return {"Strongest": 3, "Strengthening": 2, "Average": 2, "Weakening": 1, "Weakest": 0}.get(direction, 2)
        else:  # Sell
            return {"Strongest": 0, "Strengthening": 0, "Average": 0, "Weakening": 1, "Weakest": 2}.get(direction, 0)

    def calc_str_score(self, rating, strength):
        """Maps price strength to a score, conditioned by the overall rating."""
        if rating != "Sell":
            return {"Maximum": 5, "Strong": 4, "Average": 2, "Soft": 1, "Weak": 0}.get(strength, 0)
        else:
            return {"Maximum": 0, "Strong": 0, "Average": 1, "Soft": 1, "Weak": 2}.get(strength, 0)

    def strength_by_barchart_method(self, close_series, period):
        """Determines market strength based on percentage change over a period."""
        if len(close_series) < period + 1:
            return "Average"
        
        pct = (close_series.iloc[-1] / close_series.iloc[-(period + 1)]) - 1

        if period == 20: thresholds = [-0.02, 0.03, 0.05, 0.08]
        elif period == 50: thresholds = [-0.05, 0.04, 0.08, 0.12]
        else: thresholds = [-0.05, 0.05, 0.10, 0.15] # 150D

        if pd.isna(pct) or (pct > thresholds[1] and pct <= thresholds[2]): return "Average"
        if pct <= thresholds[0]: return "Weak"
        if pct <= thresholds[1]: return "Soft"
        if pct <= thresholds[3]: return "Strong"
        return "Maximum"

    def realized_vol_score(self, close, lookback=126, window=21):
        """Computes an inverse volatility score based on historical realized volatility deciles."""
        daily_ret = close.pct_change()
        realized_vol = daily_ret.rolling(window).std() * np.sqrt(252)

        if len(realized_vol.dropna()) < lookback:
            return 0.0

        dist = realized_vol.iloc[-(lookback + 1):-1].dropna()
        val = realized_vol.iloc[-1]

        if pd.isna(val) or len(dist) < 20:
            return 0.0

        deciles = dist.quantile(np.arange(0.1, 1.0, 0.1))
        rank = sum(val > dec for dec in deciles)  # Rank 0..9
        score = 10 - (rank * (20 / 9))  # Map 0..9 -> +10..-10
        return score

    # ----------------------
    # Main Strategy Execution
    # ----------------------
    def run(self, data):
        """
        Executes the strategy logic at each time step.
        """
        ohlcv = data["ohlcv"]
        
        # Warmup period to ensure enough data for all moving averages
        warmup_period = 175
        if len(ohlcv) < warmup_period:
            return TargetAllocation(self.last_alloc)

        # Create a pandas Series of SPY close prices for easier calculations
        spy_close = pd.Series(
            [d["SPY"]["close"] for d in ohlcv],
            index=pd.to_datetime([d["SPY"]["date"] for d in ohlcv])
        )

        # Only re-calculate and rebalance on the specified day of the week
        today = spy_close.index[-1]
        if today.weekday() != self.rebalance_day:
            return TargetAllocation(self.last_alloc)
        
        # --- Start ROAR Score Calculation ---
        
        # 1. Calculate Moving Averages
        ma_20 = spy_close.rolling(20).mean()
        ma_50 = spy_close.rolling(50).mean()
        ma_150 = spy_close.rolling(150).mean()
        
        # 2. Calculate Ratings, Directions, and Strengths for each MA
        rating_20 = self.get_ma_rating_by_curvature(ma_20)
        rating_50 = self.get_ma_rating_by_curvature(ma_50)
        rating_150 = self.get_ma_rating_by_curvature(ma_150)

        dir_20 = self.get_direction_category_slope(ma_20, 20)
        dir_50 = self.get_direction_category_slope(ma_50, 50)
        dir_150 = self.get_direction_category_slope(ma_150, 150)
        
        str_20 = self.strength_by_barchart_method(spy_close, 20)
        str_50 = self.strength_by_barchart_method(spy_close, 50)
        str_150 = self.strength_by_barchart_method(spy_close, 150)
        
        # 3. Calculate Component Scores
        score_ma_20 = self.calc_ma_score(rating_20)
        score_ma_50 = self.calc_ma_score(rating_50)
        score_ma_150 = self.calc_ma_score(rating_150)
        
        score_dir_20 = self.calc_dir_score(rating_20, dir_20)
        score_dir_50 = self.calc_dir_score(rating_50, dir_50)
        score_dir_150 = self.calc_dir_score(rating_150, dir_150)
        
        score_str_20 = self.calc_str_score(rating_20, str_20)
        score_str_50 = self.calc_str_score(rating_50, str_50)
        score_str_150 = self.calc_str_score(rating_150, str_150)

        # 4. Calculate Volatility and Blended Momentum
        score_vol = self.realized_vol_score(spy_close, lookback=126, window=15)
        blend_pct_chg = (spy_close.pct_change(5).iloc[-1] + spy_close.pct_change(10).iloc[-1] + 
                         spy_close.pct_change(20).iloc[-1] + spy_close.pct_change(50).iloc[-1]) / 4

        # 5. Combine components into the Raw ROAR Score for the current day
        weighted_score = (
            score_ma_20 * 0.12 + score_dir_20 * 0.12 + score_str_20 * 0.08 +
            score_vol * 0.10 +
            score_ma_50 * 0.12 + score_dir_50 * 0.12 + score_str_50 * 0.08 +
            score_ma_150 * 0.08 + score_dir_150 * 0.05 + score_str_150 * 0.05
        )
        
        raw_score = (weighted_score * 25) - (blend_pct_chg * 100)
        
        # 6. Smooth the score using a 10-day rolling average
        self.raw_roar_scores.append(raw_score)
        if len(self.raw_roar_scores) > 10:
            self.raw_roar_scores.pop(0)
            
        final_roar_score = np.mean(self.raw_roar_scores)
        
        # 7. Calculate final allocation based on the smoothed score
        spy_weight = np.clip(final_roar_score / 100.0, 0.0, 1.0)
        bil_weight = 1.0 - spy_weight
        
        # Convert numpy floats to native Python floats to satisfy the assertion
        self.last_alloc = {"SPY": float(spy_weight), "BIL": float(bil_weight)}
        
        return TargetAllocation(self.last_alloc)