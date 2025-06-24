from surmount.base_class import Strategy, TargetAllocation
from surmount.data import MedianCPI
from surmount.technical_indicators import EMA, VWAP
from surmount.logging import log
import pandas as pd

class TradingStrategy(Strategy):
    """
    DividendIncomeStrategy: A regime-based strategy that switches between a "risk-off"
    and "risk-on" mode.
    
    - Risk-Off Trigger: If the High-Yield Bond ETF (HYG) closes below its quarterly VWAP.
    - Risk-Off Action: Allocates 100% to BIL and stays in this position for a fixed
      number of days (defined by `risk_off_wait_days`) using `self.counter`.
    
    - Risk-On Allocation: When not in a risk-off state, it follows a dynamic model:
      1.  Determines a pool of "safe" assets based on the current Median CPI reading.
      2.  Selects the single best safe asset using a momentum score, which receives a
          fixed base allocation (30%).
      3.  Allocates the remainder (70%) to the top 3 momentum-driven dividend/bond ETFs.
    """
    def __init__(self):
        # The universe of assets the strategy can trade.
        self.tickers = ["TLT", "EMB", "HYG", "BIL", "TIP", "BND", "AGG", "DTH", "VIG", "VYM", "PEY", "BNDX", "VCIT", "UUP"]
        
        # HYG is used as a market benchmark for the risk-on/risk-off signal.
        self.market_benchmark = "HYG"
        
        # These are the assets considered for the primary momentum-based allocation.
        self.momentum_assets = ["BND", "AGG", "TLT", "HYG", "DTH", "VIG", "VYM", "UUP"]
        
        # Parameters for the momentum calculation.
        self.mom_long = 125
        self.mom_short = 15
        
        # The CPI level that determines the safe asset pool.
        self.inflation_threshold = 3.5
        
        # The fixed allocation percentage for the selected safe asset.
        self.base_allocation = 0.4
        
        # A warm-up period to ensure sufficient data for calculations.
        self.warmup = 1

        # Counter for the risk-off state duration.
        self.counter = 0
        self.risk_off_wait_days = 4

    @property
    def interval(self):
        return "1day"

    @property
    def assets(self):
        return self.tickers

    @property
    def data(self):
        return [MedianCPI()]

    def _vwap(self, high, low, close, volume, anchor_period='quarter'):
        """
        Calculates the anchored Volume Weighted Average Price (VWAP).
        This method is adapted to calculate VWAP resetting at the start of each period
        (e.g., quarter) based on the anchor_period.
        """
        # Create a DataFrame for grouping and calculation.
        df = pd.DataFrame({'high': high, 'low': low, 'close': close, 'volume': volume})
        df.index = pd.to_datetime(df.index)

        # Map anchor_period to pandas Grouper frequency.
        freq_map = {'month': 'MS', 'quarter': 'QS', 'year': 'AS'}
        if anchor_period not in freq_map:
            raise ValueError("anchor_period must be one of 'month', 'quarter', or 'year'")
        
        # Calculate typical price and volume-price product.
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['tpv'] = df['typical_price'] * df['volume']

        # Group by the specified anchor period and calculate cumulative values within each group.
        grouped = df.groupby(pd.Grouper(freq=freq_map[anchor_period]))
        
        cumulative_tpv = grouped['tpv'].cumsum()
        cumulative_volume = grouped['volume'].cumsum()
        
        # Calculate VWAP, handling potential division by zero.
        vwap_series = (cumulative_tpv / cumulative_volume).fillna(method='ffill')
        
        return vwap_series
        
    def _calculate_momentum(self, asset, ohlcv_data):
        """
        Helper function to calculate the momentum score for a single asset.
        Momentum = Long-Term Return - (0.15 * Short-Term Return)
        """
        try:
            prices = [d[asset]['close'] for d in ohlcv_data]
            close = prices[-1]
            current_vwap = VWAP(asset, ohlcv_data, 3)[-1]
            if len(prices) < 1:
                return -999
            ret_long = ( prices[-1] / prices[-self.mom_long] ) - 1
            ret_short = ( prices[-1] / prices[-self.mom_short] ) - 1
            momentum_score = ret_long - (ret_short * 0.15) + (current_vwap - close)
            return momentum_score if pd.notna(momentum_score) else -999
        except (KeyError, IndexError):
            return -999

    def run(self, data):
        # --- Risk-Off Counter Check ---
        # If the counter is active, stay in BIL and decrement the counter.
        if self.counter > 0:
            self.counter -= 1
            #log(f"Risk-Off period active. Days remaining: {self.counter}")
            return TargetAllocation({"BIL": 1.0})

        if len(data["ohlcv"]) < 1:
            return TargetAllocation({})

        # --- Risk-Off VWAP Signal ---
        market_data_list = [{'date': pd.to_datetime(d[self.market_benchmark]['date']), **d[self.market_benchmark]} for d in data['ohlcv']]
        market_df = pd.DataFrame(market_data_list).set_index('date')

        # Calculate quarterly VWAP using the helper method.
        #vwap_series = self._vwap(market_df['high'], market_df['low'], market_df['close'], market_df['volume'], anchor_period='quarter')
        current_vwap = VWAP(self.market_benchmark, data["ohlcv"], 50)[-1]
        
        #current_vwap = vwap_series.iloc[-1]
        current_close = market_df['close'].iloc[-1]
        current_ema = EMA(self.market_benchmark, data["ohlcv"], 50)[-1]
        cpi_value = data[("median_cpi",)][-1]['value']
        
        if cpi_value < self.inflation_threshold:
            risk_off_assets = ["TLT", "BIL", "TIP"]
        else:
            #log(f"Inflation TILT: {cpi_value}")
            risk_off_assets = ["BIL"]
        
        safe_asset = max(risk_off_assets, key=lambda asset: self._calculate_momentum(asset, data["ohlcv"]))
        
        # If market benchmark close is below its quarterly VWAP, trigger risk-off state.
        if current_close < current_ema and self.counter == 0:
            #log(f"Risk-Off Triggered: {self.market_benchmark} close ({current_close:.2f}) < Quarterly VWAP ({current_vwap:.2f}). Activating counter.")
            self.counter = self.risk_off_wait_days
            return TargetAllocation({safe_asset: 1.0})

        # --- Risk-On Allocation Logic ---
        self.counter = 0 # Explicitly reset counter when in risk-on mode.
        

        yield_assets_momentum = {asset: self._calculate_momentum(asset, data["ohlcv"]) for asset in self.momentum_assets}
        top_yield_assets = sorted(yield_assets_momentum, key=yield_assets_momentum.get, reverse=True)[:2]
        
        if len(top_yield_assets) < 1 or yield_assets_momentum[top_yield_assets[-1]] == -999:
             #log("Insufficient momentum signals among yield assets. Allocating to BIL.")
             return TargetAllocation({safe_asset: 1.0})

        # --- Construct Final Allocation ---
        allocation = {ticker: 0.0 for ticker in self.tickers}
        allocation[safe_asset] = self.base_allocation
        
        risk_weight = (1 - self.base_allocation) / len(top_yield_assets)
        for asset in top_yield_assets:
            allocation[asset] += risk_weight
            
        total_allocation = sum(allocation.values())
        if total_allocation > 0:
            for key in allocation:
                allocation[key] /= total_allocation

        #log(f"Risk-On Allocation: Safe Asset: {safe_asset}, Top Yield: {top_yield_assets}")
        return TargetAllocation(allocation)