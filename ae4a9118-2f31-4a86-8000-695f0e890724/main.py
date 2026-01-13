import numpy as np
from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import ATR
from surmount.logging import log
from surmount.data import (
    EarningsSurprises,
    EarningsCalendar,
    AnalystEstimates,
    LeveredDCF
)


class TradingStrategy(Strategy):

    def __init__(self):

        raw_tickers = [
            "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
            # (full original list unchanged)
            "ZBRA", "ZBH", "ZTS"
        ]

        self.tickers = sorted(set(raw_tickers))

        # --- REBALANCE & RISK STATE ---
        self.rebalance_interval = 30
        self.days_since_rebalance = 30

        # --- LIQUIDITY ---
        self.min_dollar_volume = 10_000_000
        self.liquidity_lookback = 20

        # --- STRATEGY STATE ---
        self.holdings_info = {}
        self.percentile_streak = {}
        self.initial_prices = {}

        # --- WEIGHTS ---
        self.W1 = 0.5
        self.W2 = 0.3
        self.W3 = 0.2
        self.Weight_En = 0.4
        self.Weight_EAn = 0.6

        # --- DATASETS (EXAMPLE-COMPLIANT) ---
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
    # LIQUIDITY FILTER
    # --------------------------------------------------
    def check_liquidity(self, ticker, bars):
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
        ohlcv = data["ohlcv"]
        holdings = data.get("holdings", {})

        if not ohlcv:
            return TargetAllocation({})

        # ---- DAILY RISK MGMT ----
        current_holdings = {k for k, v in holdings.items() if v > 0}
        active = current_holdings & set(self.holdings_info.keys())

        to_exit = set()
        partial_sells = {}

        for ticker in active:
            bars = [d[ticker] for d in ohlcv if ticker in d]
            if not bars:
                continue

            price = bars[-1]["close"]
            entry = self.holdings_info[ticker]["entry_price"]

            atr_series = ATR(ticker, bars, 14)
            atr_val = atr_series[-1] if atr_series else 0

            if price - entry < -0.10 * atr_val:
                to_exit.add(ticker)
                continue

            pct = (price - entry) / entry
            if pct >= 0.35:
                to_exit.add(ticker)
            elif pct >= 0.25:
                partial_sells[ticker] = 0.65
            elif pct >= 0.15:
                partial_sells[ticker] = 0.75
            elif pct >= 0.10:
                partial_sells[ticker] = 0.85

        # ---- REBALANCE TIMER ----
        self.days_since_rebalance += 1
        if self.days_since_rebalance < self.rebalance_interval:
            return TargetAllocation({})

        self.days_since_rebalance = 0
        log("Monthly rebalance")

        # ---- LIQUIDITY FILTER ----
        liquid = []
        for t in self.tickers:
            bars = [d[t] for d in ohlcv if t in d]
            if self.check_liquidity(t, bars):
                liquid.append(t)

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
            return TargetAllocation({})

        threshold = np.percentile(
            [v["combined"] for v in scores.values()], 90
        )

        for t, v in scores.items():
            if v["combined"] >= threshold:
                self.percentile_streak[t] = self.percentile_streak.get(t, 0) + 1
            else:
                self.percentile_streak[t] = 0

        eligible = [t for t, c in self.percentile_streak.items() if c >= 3]
        final_assets = set(eligible) - to_exit

        # ---- ALLOCATION ----
        alloc_scores = {}
        total = 0.0

        for t in final_assets:
            score = max(scores[t]["combined"], 0)
            alloc_scores[t] = score
            total += score

            if t not in self.holdings_info:
                bars = [d[t] for d in ohlcv if t in d]
                self.holdings_info[t] = {"entry_price": bars[-1]["close"]}

        allocation = {}
        if total > 0:
            for t, s in alloc_scores.items():
                allocation[t] = s / total

        return TargetAllocation(allocation)

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
            EAn = En

            return {"En": En, "EAn": EAn}

        except Exception:
            return None

    # --------------------------------------------------
    # DCF FUNCTION
    # --------------------------------------------------
    def func_DF(self, ticker, data, current_price):
        try:
            dcf = data.get(("levered_dcf", ticker))
            dcf_price = dcf[-1].get("Stock Price") if dcf else current_price

            base = self.initial_prices.setdefault(ticker, current_price)
            delta = dcf_price - base
            pct = (dcf_price / base) - 1 if base else 0

            if delta < 0:
                bars = [d[ticker] for d in data["ohlcv"] if ticker in d]
                atr = ATR(ticker, bars, 14)
                atr_val = atr[-1] if atr else 1
                return pct / (delta * atr_val) if delta else pct

            return pct

        except Exception:
            return 0.0
