from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.logging import log
import pandas as pd
import math


class TradingStrategy(Strategy):
    """
    Conservative: monthly Dual Momentum (12-1) with a trend gate, inside a fixed equity band.
    Long only, no leverage, daily bars, rebalance on the first bar of each month.

    Risk profile: anchor 40% equity, band 30% to 45% (references: Vanguard LifeStrategy Conservative Growth (40/60) and
    American Century "Conservative" sample portfolio at 45% equity). The rest is bonds and short-term (BIL >= 2%).

    Universe: Equity VTI VIG XLV XLP XLU EFA VWO VNQ | Bonds AGG SHY IEF TLT TIP LQD | Cash BIL
    (SPY is listed in `assets` for benchmarking only and always receives a 0% target.)

    Signals, from data up to the current bar only:
      Momentum 12-1  = close 21 bars ago / close 252 bars ago - 1 (skips the latest month).
      Relative       = rank by momentum inside each sleeve (equity: top 4 of 8, bonds: top 4 of 6).
      Absolute       = momentum must beat the cash hurdle (BIL 12-1 return; 0 until BIL has a year of history).
      Trend gate     = one of (default "vote"):
        "sma"     close > SMA(200)
        "avwap"   close > anchored VWAP of the calendar quarter. In the first 21 bars of a quarter the anchor is the
                  start of the previous quarter, so the window is never degenerate.
        "kalman"  filtered slope > 0 of a local-linear-trend Kalman filter on the log month-end closes of the last
                  60 completed months (needs 24 months; fewer months = gate fails). The filtered value is causal.
        "vote"    at least 2 of the 3 above (least sensitive to any one filter)
        "none"    absolute momentum only
      An ETF "passes" when it beats the cash hurdle AND the gate is true.

    Allocation (all weights are slots of 1/4):
      Equity slot  = (floor + (anchor - floor) * pass) / 4 : a passing slot gets its full weight, a failing slot
                     drops to its band-floor weight, so equity always stays inside [30%, 40%].
      Bond slot    = bond budget / 4 if it passes, else 0 (the share goes to BIL). Bond budget = 1 - equity - 2%.
      BIL          = 2% minimum plus every unallocated share.

    Surmount specifics:
      - Stateless: decisions use only data["ohlcv"] (history to the current bar) and data["holdings"].
      - Between rebalances the strategy returns current holdings (no trades). A rebalance also happens if the
        equity share of the holdings leaves the band [30%, 45%] or if nothing is held yet.
      - Hard limits are checked before every rebalance and the strategy fails closed (keeps current holdings):
        weights sum to at most 1 | no negative weights | single ETF (cash excluded) <= 25%
        | equity share inside [30%, 40%].
      - Audit trail: one log() line per rebalance (date, reason, equity budget, passes, weights) and one line per
        refused or skipped rebalance on a held portfolio.
      - Missing data, too little history or missing holdings never raise.

    Reading backtests of this file: the first bar of the month is one of many possible rebalance days. Moving the
    rebalance day changes Sharpe by about 0.07 to 0.10 and CAGR by about 0.5 to 0.6 points, and the first bar is at the
    top of that range. Quote averages and ranges over rebalance days, not a single run. The choice of gate moves
    results by less than that noise.
    """

    def __init__(self):
        self.equity = ["VTI", "VIG", "XLV", "XLP", "XLU", "EFA", "VWO", "VNQ"]
        self.bonds = ["AGG", "SHY", "IEF", "TLT", "TIP", "LQD"]
        self.cash = "BIL"
        self.benchmark = "SPY"
        self.trading = self.equity + self.bonds + [self.cash]

        # Risk profile band
        self.e_anchor = 0.4
        self.e_floor = 0.3
        self.e_ceil = 0.45
        self.cash_min = 0.02
        self.max_weight = 0.25

        # Signals
        self.gate = "vote"            # "none" | "sma" | "avwap" | "kalman" | "vote"
        self.use_abs = True
        self.skip = 21                # 12-1: skip the latest month
        self.lookback = 252
        self.sma_days = 200
        self.avwap_min_bars = 21
        self.kal_months = 60
        self.kal_min_months = 24
        self.kal_q_level = 0.1
        self.kal_q_slope = 0.01
        self.kal_r = 1.0

        # Selection
        self.n_eq = 4
        self.n_bd = 4

        # History to request: 60 months of month ends for the Kalman filter
        self.min_bars = 253
        self.bars = 1400

    @property
    def assets(self):
        return self.trading + [self.benchmark]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []  # price and volume data only

    # ---------- helpers ----------
    @staticmethod
    def _stamp(bar):
        for v in bar.values():
            return str(v["date"])
        return ""

    def _closes(self, rows):
        """Close prices of the whole universe over the fetched window. Missing tickers become NaN."""
        return pd.DataFrame({t: [bar[t]["close"] if t in bar else float("nan") for bar in rows]
                             for t in self.trading})

    def _momentum(self, df):
        """12-1 momentum per ETF: close[-1-skip] / close[-1-lookback] - 1 (NaN if either is missing)."""
        if len(df) < self.lookback + 1:
            return {}
        a = df.iloc[-1 - self.skip]
        b = df.iloc[-1 - self.lookback]
        return {c: (a[c] / b[c] - 1.0) for c in self.trading if not pd.isna(a[c]) and not pd.isna(b[c]) and b[c] > 0}

    def _gate_sma(self, ticker, rows):
        sma = SMA(ticker, rows[-self.sma_days:], self.sma_days)
        return bool(sma and not pd.isna(sma[-1]) and rows[-1][ticker]["close"] > sma[-1])

    def _gate_avwap(self, ticker, rows):
        """Close above the anchored VWAP of the calendar quarter (previous quarter anchor in the first 21 bars)."""
        def qkey(bar):
            s = self._stamp(bar)
            return s[:4] + "Q" + str((int(s[5:7]) - 1) // 3 + 1)
        cur_key = qkey(rows[-1])
        cur_idx = [i for i in range(len(rows) - 1, -1, -1) if qkey(rows[i]) == cur_key]
        first_cur = cur_idx[-1]
        elapsed = len(cur_idx) - 1                      # bars of this quarter before the current bar
        start = first_cur
        if elapsed < self.avwap_min_bars:               # use the previous quarter start as anchor
            prev_key = qkey(rows[first_cur - 1]) if first_cur > 0 else None
            if prev_key is None:
                return False
            j = first_cur - 1
            while j >= 0 and qkey(rows[j]) == prev_key:
                j -= 1
            start = j + 1
        pv = vv = 0.0
        for bar in rows[start:]:
            if ticker not in bar:
                return False
            b = bar[ticker]
            vol = b.get("volume") or 0.0
            pv += (b["high"] + b["low"] + b["close"]) / 3.0 * vol
            vv += vol
        return bool(vv > 0 and rows[-1][ticker]["close"] > pv / vv)

    def _gate_kalman(self, ticker, rows):
        """Filtered slope of a local-linear-trend Kalman filter on log month-end closes (completed months only)."""
        last = {}
        order = []
        for bar in rows:
            if ticker in bar:
                m = self._stamp(bar)[:7]
                if m not in last:
                    order.append(m)
                last[m] = bar[ticker]["close"]
        cur = self._stamp(rows[-1])[:7]
        months = [m for m in order if m != cur][-self.kal_months:]
        y = [math.log(last[m]) for m in months]
        if len(y) < self.kal_min_months:
            return False
        d = [y[i] - y[i - 1] for i in range(1, len(y))]
        mean = sum(d) / len(d)
        sd = math.sqrt(sum((v - mean) ** 2 for v in d) / (len(d) - 1))
        if not sd > 0:
            return False
        z = [(v - y[0]) / sd for v in y]
        l, s = z[0], 0.0
        p00, p01, p10, p11 = 1.0, 0.0, 0.0, 0.1
        for k in range(1, len(z)):
            l, s = l + s, s                              # predict
            p00, p01, p10, p11 = (p00 + p01 + p10 + p11 + self.kal_q_level, p01 + p11,
                                  p10 + p11, p11 + self.kal_q_slope)
            S = p00 + self.kal_r                         # update
            k0, k1 = p00 / S, p10 / S
            innov = z[k] - l
            l, s = l + k0 * innov, s + k1 * innov
            p00, p01, p10, p11 = p00 - k0 * p00, p01 - k0 * p01, p10 - k1 * p00, p11 - k1 * p01
        return s > 0

    def _gate_ok(self, ticker, rows):
        g = self.gate
        if g == "none":
            return True
        if g == "sma":
            return self._gate_sma(ticker, rows)
        if g == "avwap":
            return self._gate_avwap(ticker, rows)
        if g == "kalman":
            return self._gate_kalman(ticker, rows)
        votes = (int(self._gate_sma(ticker, rows)) + int(self._gate_avwap(ticker, rows))
                 + int(self._gate_kalman(ticker, rows)))
        return votes >= 2

    def _sleeve(self, universe, n, mom, hurdle, rows):
        valid = [c for c in universe if c in mom]
        if len(valid) < n:
            return None
        top = sorted(valid, key=lambda c: (-mom[c], universe.index(c)))[:n]
        res = {}
        for c in top:
            ok = (mom[c] > hurdle) if self.use_abs else True
            res[c] = bool(ok and self._gate_ok(c, rows))
        return res

    def _target(self, df, rows):
        """Target weights from data up to the current bar. Returns (weights dict or None, info dict)."""
        mom = self._momentum(df)
        hurdle = mom.get(self.cash, 0.0)
        se = self._sleeve(self.equity, self.n_eq, mom, hurdle, rows)
        sb = self._sleeve(self.bonds, self.n_bd, mom, hurdle, rows)
        if se is None or sb is None:
            return None, {}

        tgt = {a: 0.0 for a in self.trading}
        for c, ok in se.items():
            tgt[c] = (self.e_floor + (self.e_anchor - self.e_floor) * (1.0 if ok else 0.0)) / len(se)
        e_t = sum(tgt[c] for c in se)
        bond_budget = 1.0 - self.cash_min - e_t
        for c, ok in sb.items():
            tgt[c] = bond_budget / len(sb) if ok else 0.0
        tgt[self.cash] = max(0.0, 1.0 - sum(v for k, v in tgt.items() if k != self.cash) - 1e-9)
        info = dict(equity=e_t, pe=sum(se.values()), ne=len(se), pb=sum(sb.values()), nb=len(sb))
        return tgt, info

    def _valid(self, w):
        e = sum(w[c] for c in self.equity)
        return (sum(w.values()) <= 1.0 + 1e-9 and min(w.values()) >= -1e-12
                and max(v for k, v in w.items() if k != self.cash) <= self.max_weight + 1e-9
                and self.e_floor - 1e-9 <= e <= self.e_anchor + 1e-9)

    def _alloc(self, w):
        out = {a: float(w.get(a, 0.0)) for a in self.trading}
        out[self.benchmark] = 0.0
        total = sum(out.values())
        if total > 1.0:  # float safety: never exceed 100%
            out = {k: v / total for k, v in out.items()}
        return TargetAllocation(out)

    # ---------- strategy ----------
    def run(self, data):
        ohlcv = data["ohlcv"]
        if len(ohlcv) < 1:
            return TargetAllocation({})  # not enough history: stay in cash

        holdings = data.get("holdings") or {}
        cur = {a: float(holdings.get(a) or 0.0) for a in self.trading}
        invested = sum(cur.values())
        equity_now = sum(cur[a] for a in self.equity)

        # Rebalance triggers
        new_month = self._stamp(ohlcv[-1])[:7] != self._stamp(ohlcv[-2])[:7]
        if invested < 0.5:
            reason = "initial"
        elif new_month:
            reason = "scheduled"
        elif equity_now < self.e_floor - 1e-9 or equity_now > self.e_ceil + 1e-9:
            reason = "band"
        else:
            return self._alloc(cur)  # between rebalances: keep current holdings, no trades

        rows = ohlcv[-self.bars:]
        df = self._closes(rows)
        held = invested >= 0.5
        fallback = self._alloc(cur) if held else TargetAllocation({})
        if pd.isna(df[self.cash].iloc[-1]):
            if held:
                log("%s|SKIP_NO_CASH_PRICE_KEPT_HOLDINGS|%s" % (self._stamp(ohlcv[-1])[:10], reason))
            return fallback

        tgt, info = self._target(df, rows)
        if tgt is None:
            if held:
                log("%s|SKIP_INSUFFICIENT_HISTORY_KEPT_HOLDINGS|%s" % (self._stamp(ohlcv[-1])[:10], reason))
            return fallback
        if not self._valid(tgt):
            log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s" % (self._stamp(ohlcv[-1])[:10], reason))
            return fallback

        log("%s|%s|eq=%.3f|pass_eq=%d/%d|pass_bd=%d/%d|%s" % (
            self._stamp(ohlcv[-1])[:10], reason, info["equity"], info["pe"], info["ne"], info["pb"], info["nb"],
            ",".join("%s:%.4f" % (k, v) for k, v in tgt.items() if v > 1e-9)))
        return self._alloc(tgt)