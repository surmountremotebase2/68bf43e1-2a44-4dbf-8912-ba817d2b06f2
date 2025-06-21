from surmount.base_class import Strategy, TargetAllocation
from surmount.data import MedianCPI
from surmount.logging import log
import pandas as pd

class TradingStrategy(Strategy):
    """
    DividendIncomeStrategy: A regime-based strategy that switches between a "risk-off"
    and "risk-on" mode.
    
    - Risk-Off Trigger: If the High-Yield Bond ETF (HYG) closes below its quarterly VWAP,
      the strategy allocates 100% to BIL (short-term treasuries) to protect capital.
    
    - Risk-On Allocation: Otherwise, it follows a dynamic allocation model:
      1.  It determines a pool of "safe" assets based on the current Median CPI reading.
      2.  It selects the single best safe asset using a long-term momentum score. This
          asset receives a fixed base allocation (30%).
      3.  It then selects the top 3 momentum-driven dividend and bond ETFs for the
          remainder of the portfolio (70%), ensuring a diversified but strong posture.
    """
    def __init__(self):
        # The universe of assets the strategy can trade.
        self.tickers = ["TLT", "EMB", "HYG", "BIL", "TIP", "BND", "AGG", "DTH", "VIG", "VYM", "PEY"]
        
        # HYG is used as a market benchmark for the risk-on/risk-off signal.
        self.market_benchmark = "HYG"
        
        # These are the assets considered for the primary momentum-based allocation.
        self.momentum_assets = ["BND", "TLT", "HYG", "DTH", "VIG", "VYM", "PEY"]
        
        # Parameters for the momentum calculation.
        self.mom_long = 125  # Long-term lookback period
        self.mom_short = 15   # Short-term lookback period
        
        # The CPI level that determines the safe asset pool.
        self.inflation_threshold = 2.1
        
        # The fixed allocation percentage for the selected safe asset.
        self.base_allocation = 0.3
        
        # A warm-up period to ensure sufficient data for calculations.
        self.warmup = self.mom_long + 5

    @property
    def interval(self):
        """
        The strategy uses daily data.
        """
        return "1day"

    @property
    def assets(self):
        """
        The list of assets this strategy trades.
        """
        return self.tickers

    @property
    def data(self):
        """
        Requires Median CPI data to assess the inflation environment.
        """
        return [MedianCPI()]

    def _calculate_momentum(self, asset, ohlcv_data):
        """
        Helper function to calculate the momentum score for a single asset.
        Momentum = Long-Term Return - (0.15 * Short-Term Return)
        This penalizes assets with strong recent pullbacks.
        """
        try:
            # Extract historical close prices for the asset.
            prices = [d[asset]['close'] for d in ohlcv_data]
            
            # Ensure there is enough data for the calculation.
            if len(prices) < self.mom_long:
                return -999 # Return a very low score if data is insufficient.
                
            # Calculate long and short term returns.
            ret_long = prices[-1] / prices[-self.mom_long] - 1
            ret_short = prices[-1] / prices[-self.mom_short] - 1
            
            # Calculate the final momentum score.
            momentum_score = ret_long - (ret_short * 0.15)
            
            return momentum_score if pd.notna(momentum_score) else -999
        except (KeyError, IndexError):
            # Handle cases where the asset data might be missing for a given day.
            return -999

    def run(self, data):
        # Ensure there's enough historical data to run the strategy.
        if len(data["ohlcv"]) < self.warmup:
            return TargetAllocation({})

        # --- Risk-Off VWAP Signal ---
        # Create a DataFrame for the market benchmark asset (HYG) for easier calculations.
        market_data = [{'date': pd.to_datetime(d['date']), **d[self.market_benchmark]} for d in data['ohlcv']]
        market_df = pd.DataFrame(market_data).set_index('date')

        # Determine the start of the current quarter for the quarterly VWAP calculation.
        last_date = market_df.index[-1]
        quarter_start_date = last_date - pd.tseries.offsets.QuarterBegin(startingMonth=1)
        quarter_df = market_df.loc[quarter_start_date:]

        # Calculate the anchored quarterly VWAP.
        quarter_df['tpv'] = ((quarter_df['high'] + quarter_df['low'] + quarter_df['close']) / 3) * quarter_df['volume']
        vwap_quarterly = quarter_df['tpv'].sum() / quarter_df['volume'].sum()
        current_close = market_df['close'].iloc[-1]
        
        # If market benchmark close is below its quarterly VWAP, move to 100% safety.
        if current_close < vwap_quarterly:
            log(f"Risk-Off Triggered: {self.market_benchmark} close ({current_close:.2f}) < Quarterly VWAP ({vwap_quarterly:.2f}). Allocating to BIL.")
            return TargetAllocation({"BIL": 1.0})

        # --- Risk-On Allocation Logic ---
        # Get the latest available Median CPI value.
        cpi_value = data[("median_cpi",)][-1]['value']

        # Determine the pool of safe-haven assets based on the inflation regime.
        if cpi_value < self.inflation_threshold:
            risk_off_assets = ["TLT", "BIL", "TIP"] # In low inflation, long-term bonds (TLT) are viable.
        else:
            risk_off_assets = ["BIL", "TIP"] # In high inflation, prefer shorter duration and inflation-protected bonds.
        
        # Select the single best safe asset based on momentum.
        safe_asset = max(risk_off_assets, key=lambda asset: self._calculate_momentum(asset, data["ohlcv"]))

        # Select the top 3 momentum assets from the broader dividend/bond universe.
        yield_assets_momentum = {asset: self._calculate_momentum(asset, data["ohlcv"]) for asset in self.momentum_assets}
        top_yield_assets = sorted(yield_assets_momentum, key=yield_assets_momentum.get, reverse=True)[:3]
        
        # If we can't identify at least two strong momentum assets, default to BIL for safety.
        if len(top_yield_assets) < 2 or yield_assets_momentum[top_yield_assets[1]] == -999:
             log("Insufficient momentum signals among yield assets. Allocating to BIL.")
             return TargetAllocation({"BIL": 1.0})

        # --- Construct Final Allocation ---
        allocation = {ticker: 0.0 for ticker in self.tickers}

        # Set the base allocation for the selected safe asset.
        allocation[safe_asset] = self.base_allocation
        
        # Distribute the remaining portfolio among the top 3 yield assets.
        risk_weight = (1 - self.base_allocation) / len(top_yield_assets)
        for asset in top_yield_assets:
            allocation[asset] += risk_weight # Use += to correctly handle if safe_asset is also a top_yield_asset
            
        # Normalize to ensure the sum is exactly 1.0, accounting for any floating point inaccuracies.
        total_allocation = sum(allocation.values())
        if total_allocation > 0:
            for key in allocation:
                allocation[key] /= total_allocation

        log(f"Risk-On Allocation: Safe Asset: {safe_asset}, Top Yield: {top_yield_assets}")
        return TargetAllocation(allocation)