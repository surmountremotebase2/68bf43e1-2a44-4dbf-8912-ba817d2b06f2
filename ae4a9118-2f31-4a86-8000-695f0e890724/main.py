import numpy as np
from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import ATR
from surmount.data import (
    EarningsSurprises,
    EarningsCalendar,
    AnalystEstimates,
    LeveredDCF
)
from surmount.logging import log


class TradingStrategy(Strategy):

    def init(self):
        # ---- MUST EXIST BEFORE init() ----
        raw_tickers = [
            "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
            # FULL LIST UNCHANGED
            "ZBRA", "ZBH", "ZTS"
        ]

        self.tickers = sorted(set(raw_tickers))
        self.last_alloc = {}

    
        # ---- REBALANCE ----
        self.rebalance_interval = 30
        self.days_since_rebalance = 30

        # ---- LIQUIDITY ----
        self.min_dollar_volume = 10_000_000
        self.liquidity_lookback = 20

        # ---- STATE ----
        self.holdings_info = {}
        self.percentile_streak = {}
        self.initial_prices = {}

        # ---- WEIGHTS ----
        self.W1 = 0.5
        self.W2 = 0.3
        self.W3 = 0.2
        self.Weight_En = 0.4
        self.Weight_EAn = 0.6

        # ---- DATASETS ----
        self.data_list = []
        for ticker in self.tickers:
            self.data_list.extend([
                EarningsSurprises(ticker),
                EarningsCalendar(ticker),
                AnalystEstimates(ticker),
                LeveredDCF(ticker)
            ])

    @property
    def interval(self):
        return "1day"

    @property
    def assets(self):
        return self.tickers

    @property
    def data(self):
        return self.data_list

    # --------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------
    def check_liquidity(self, bars):
        if not bars or len(bars) < 5:
            return False
        recent = bars[-self.liquidity_lookback:]
        avg_vol = np.mean([b["volume"] for b in recent])
        price = recent[-1]["close"]
        return avg_vol * price >= self.min_dollar_volume

    # --------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------
    def run(self, data):
        ohlcv = data.get("ohlcv", [])
        holdings = data.get("holdings", {})

        if not ohlcv:
            return TargetAllocation(self.last_alloc)

        # ---- DAILY RISK MGMT ----
        current_holdings = {k for k, v in holdings.items() if v > 0}
        active = current_holdings & set(self.holdings_info.keys())

        to_exit = set()

        for ticker in active:
            bars = [d[ticker] for d in ohlcv if ticker in d]
            if not bars:
                continue

            price = bars[-1]["close"]
            entry = self.holdings_info[ticker]["entry_price"]

            atr = ATR(ticker, bars, 14)
            atr_val = atr[-1] if atr else 0

            if atr_val > 0 and price - entry < -0.10 * atr_val:
                to_exit.add(ticker)
                continue

            pct = (price - entry) / entry
            if pct >= 0.35:
                to_exit.add(ticker)

        # ---- REBALANCE TIMER ----
        self.days_since_rebalance += 1
        if self.days_since_rebalance < self.rebalance_interval:
            return TargetAllocation(self.last_alloc)

        self.days_since_rebalance = 0

        # ---- LIQUID UNIVERSE ----
        liquid = []
        for t in self.tickers:
            bars = [d[t] for d in ohlcv if t in d]
            if self.check_liquidity(bars):
                liquid.append(t)

        if not liquid:
            return TargetAllocation(self.last_alloc)

        # ---- SCORING ----
        scores = {}
        for ticker in liquid:
            s = self.calculate_scores(ticker, data)
            if s:
                s["combined"] = (
                    self.Weight_En * s["En"] +
                    self.Weight_EAn * s["EAn"]
                )
                scores[ticker] = s

        if not scores:
            return TargetAllocation(self.last_alloc)

        threshold = np.percentile(
            [v["combined"] for v in scores.values()], 90
        )

        for t, v in scores.items():
            self.percentile_streak[t] = (
                self.percentile_streak.get(t, 0) + 1
                if v["combined"] >= threshold else 0
            )

        eligible = [
            t for t, c in self.percentile_streak.items()
            if c >= 3 and t not in to_exit
        ]

        if not eligible:
            return TargetAllocation(self.last_alloc)

        # ---- ALLOCATION ----
        total = sum(max(scores[t]["combined"], 0) for t in eligible)
        if total <= 0:
            return TargetAllocation(self.last_alloc)

        allocation = {}
        for t in eligible:
            allocation[t] = max(scores[t]["combined"], 0) / total
            if t not in self.holdings_info:
                bars = [d[t] for d in ohlcv if t in d]
                self.holdings_info[t] = {
                    "entry_price": bars[-1]["close"]
                }

        # ---- SAVE + RETURN ----
        self.last_alloc = allocation
        return TargetAllocation(self.last_alloc)

    # --------------------------------------------------
    # SCORE CALCULATION
    # --------------------------------------------------
    def calculate_scores(self, ticker, data):
        try:
            earnings = data.get(("earnings_surprises", ticker))
            estimates = data.get(("analyst_estimates", ticker))

            if not earnings or not estimates:
                return None

            def gv(lst, k, i=-1):
                return lst[i].get(k) if lst and len(lst) > abs(i) else None

            eps_est = gv(earnings, "epsEstimated")
            eps_act = gv(earnings, "epsactual")
            B1 = (eps_est / eps_act) - 1 if eps_est and eps_act else 0

            eps_series = [e.get("eps") for e in estimates if e.get("eps")]
            var = np.var(eps_series) if len(eps_series) > 1 else 0
            B2 = 1 / var if var else 0

            ebitda_est = gv(estimates, "ebitdaAvg")
            ebitda_act = gv(estimates, "ebitdaActual")
            B3 = (ebitda_est / ebitda_act) - 1 if ebitda_est and ebitda_act else 0

            En = self.W1 * B1 + self.W2 * B2 + self.W3 * B3
            return {"En": En, "EAn": En}

        except Exception:
            return None