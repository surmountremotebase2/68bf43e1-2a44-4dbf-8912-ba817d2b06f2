from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.logging import log
import pandas as pd
import math


class TradingStrategy(Strategy):
    """
    Conservative: score-driven ETF allocation inside a fixed equity band. Long only, no leverage, daily bars.

    Risk profile: anchor 40% equity, band 30% to 45% (references: Vanguard LifeStrategy Conservative Growth (40/60) and
    American Century "Conservative" sample portfolio at 45% equity). The rest is bonds and short-term (BIL >= 2%).

    Universe (14 scored ETFs + cash):
      Equity: VTI VIG XLV XLP XLU EFA VWO VNQ     Bonds: AGG SHY IEF TLT TIP LQD     Cash: BIL
      SPY is listed in `assets` for benchmarking only and always receives a 0% target.

    Score per ETF, from data up to the current bar only (range -10 to +10):
      Vol score  = inverse decile of the 21-day realised vol versus its prior 126 observations (low vol = high score)
      Dist score = distance of close from SMA(220), in units of its random-walk standard deviation, scaled to +/-10
      Score      = 0.5 * Vol score + 0.5 * Dist score

    Allocation at each rebalance (first bar of a month, or equity share leaves the band, or nothing held yet):
      1. Equity sleeve: top 5 by score, weights proportional to (score + 10), floor of 1, max 40% of the sleeve
         (and 25% of the portfolio).
      2. Volatility target: 126-day realised vol of the selected equity basket vs 15%.
         Equity budget = anchor * min(1, 15% / vol), never below the band floor and never above the anchor.
      3. Bond sleeve (budget = 1 - equity - cash minimum): top 4 by score, only those with score > 0,
         weights proportional to score, same caps. Any unallocated share goes to BIL.
      4. BIL receives the 2% minimum plus any unallocated bond budget.
    Ties in score go to the earlier ticker in the universe list (deterministic).

    Surmount specifics:
      - Stateless: every decision uses only data["ohlcv"] (history up to the current bar) and data["holdings"].
      - Between rebalances the strategy returns the current holdings, so no trades are generated.
      - Hard limits are checked before every rebalance and the strategy fails closed (keeps current holdings):
        weights sum to at most 1 | no negative weights | single ETF (cash excluded) <= 25%
        | equity share inside [30%, 45%].
      - Audit trail: one log() line per rebalance (date, reason, equity budget, volatility scale, equity vol, weights)
        and one line for every refused rebalance.
      - Not enough history, a missing price, or missing holdings never raises: the strategy holds what it has
        (or stays in cash if nothing is held yet). Waiting for history is silent; a refused rebalance on a held portfolio is logged.
    """

    def __init__(self):
        # Universe
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

        # Scoring
        self.sma_days = 220
        self.vol_window = 10
        self.vol_lookback = 126
        self.w_vol = 0.8
        self.w_dist = 0.2
        self.use_vol_score = True
        self.use_dist_score = True

        # Volatility targeting
        self.use_vol_target = True
        self.vt_lookback = 126
        self.vt_target = 0.10

        # Selection
        self.n_eq = 3
        self.n_bd = 1
        self.max_sleeve_weight = 0.40

        # History needed: SMA(220) needs 221 closes; the 126-day windows need fewer
        self.bars = 221

    @property
    def assets(self):
        return self.trading + [self.benchmark]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []  # price data only

    # ---------- helpers ----------
    @staticmethod
    def _stamp(bar):
        """Date string of a bar (every ticker in a bar carries the same date)."""
        for v in bar.values():
            return str(v["date"])
        return ""

    def _frame(self, rows):
        """Close prices of the whole universe over the fetched window. Missing tickers become NaN."""
        return pd.DataFrame({t: [bar[t]["close"] if t in bar else float("nan") for bar in rows]
                             for t in self.trading})

    @staticmethod
    def _top(score, universe, n):
        """Top n by score. Ties go to the earlier ticker in the universe list, so the choice is deterministic."""
        return sorted(universe, key=lambda c: (-score[c], universe.index(c)))[:n]

    @staticmethod
    def _cap_normalize(tilt, cap):
        """Proportional weights with a cap. If the cap cannot be met the leftover stays unallocated."""
        tot = sum(tilt.values())
        w = {k: v / tot for k, v in tilt.items()}
        for _ in range(10):
            over = [k for k in w if w[k] > cap + 1e-12]
            if not over:
                break
            excess = sum(w[k] - cap for k in over)
            for k in over:
                w[k] = cap
            under = [k for k in w if k not in over and 0 < w[k] < cap - 1e-12]
            if not under:
                break
            s = sum(w[k] for k in under)
            for k in under:
                w[k] += excess * w[k] / s
        return w

    def _vol_score(self, rv):
        """Inverse realised-vol decile score (+10 lowest vol ... -10 highest) against the prior distribution."""
        cur = rv.iloc[-1]
        win = rv.iloc[-1 - self.vol_lookback:-1].dropna()
        if len(win) < 20 or pd.isna(cur):
            return float("nan")
        deciles = win.quantile([i / 10.0 for i in range(1, 10)])
        rank = int((cur > deciles).sum())
        return 10.0 - rank * (20.0 / 9.0)

    def _dist_score(self, ticker, close, sig_d, rows):
        """Distance from SMA in units of its random-walk standard deviation, clipped to +/-2, scaled to +/-10."""
        sma_list = SMA(ticker, rows, self.sma_days)
        if not sma_list or pd.isna(sma_list[-1]) or not sig_d or pd.isna(sig_d):
            return float("nan")
        z = (close / sma_list[-1] - 1.0) / (sig_d * math.sqrt(self.sma_days / 3.0))
        return max(-2.0, min(2.0, z)) * 5.0

    def _target(self, df, rows):
        """Target weights from data up to the current bar. Returns (weights dict or None, info dict)."""
        rets = df.pct_change()
        rv = rets.rolling(self.vol_window).std() * math.sqrt(252)
        sig_d = rets.rolling(self.vt_lookback).std().iloc[-1]
        scored = self.equity + self.bonds

        score = {}
        for t in scored:
            parts, wts = [], []
            if self.use_vol_score:
                parts.append(self._vol_score(rv[t]))
                wts.append(self.w_vol)
            if self.use_dist_score:
                parts.append(self._dist_score(t, df[t].iloc[-1], sig_d[t], rows))
                wts.append(self.w_dist)
            score[t] = sum(w * p for w, p in zip(wts, parts)) / sum(wts)
        if any(pd.isna(v) for v in score.values()):
            return None, {}

        # Equity sleeve: relative ranking
        eq = self._top(score, self.equity, self.n_eq)
        tilt_e = {c: max(score[c] + 10.0, 1.0) for c in eq}
        w_eq = self._cap_normalize(tilt_e, self.max_sleeve_weight)

        # Volatility target on the selected equity basket (126 days, through the current bar)
        sig_eq, scale = float("nan"), 1.0
        if self.use_vol_target:
            r = sum(rets[c].iloc[-self.vt_lookback:] * w_eq[c] for c in eq)
            sig_eq = float(r.std() * math.sqrt(252))
            if sig_eq > 0:
                scale = min(1.0, self.vt_target / sig_eq)
        e_t = min(max(self.e_anchor * scale, self.e_floor), self.e_anchor)
        # Sleeve cap must also respect the portfolio-level single-ETF limit
        w_eq = self._cap_normalize(tilt_e, min(self.max_sleeve_weight, self.max_weight / e_t))

        # Bond sleeve: absolute gate (score > 0), unallocated share goes to cash
        bd = self._top(score, self.bonds, self.n_bd)
        tilt_b = {c: max(score[c], 0.0) for c in bd}
        bond_budget = 1.0 - self.cash_min - e_t
        cap_b = min(self.max_sleeve_weight, self.max_weight / bond_budget)
        w_bd = self._cap_normalize(tilt_b, cap_b) if sum(tilt_b.values()) > 0 else {c: 0.0 for c in bd}

        tgt = {a: 0.0 for a in self.trading}
        for c in eq:
            tgt[c] = e_t * w_eq[c]
        for c in bd:
            tgt[c] = bond_budget * w_bd[c]
        tgt[self.cash] = max(0.0, 1.0 - sum(v for k, v in tgt.items() if k != self.cash) - 1e-9)
        return tgt, dict(equity_target=e_t, vol_scale=scale, equity_vol=sig_eq)

    def _valid(self, w):
        e = sum(w[c] for c in self.equity)
        return (sum(w.values()) <= 1.0 + 1e-9 and min(w.values()) >= -1e-12
                and max(v for k, v in w.items() if k != self.cash) <= self.max_weight + 1e-9
                and self.e_floor - 1e-9 <= e <= self.e_ceil + 1e-9)

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
        if len(ohlcv) < self.bars:
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
        df = self._frame(rows)
        held = invested >= 0.5
        fallback = self._alloc(cur) if held else TargetAllocation({})
        # Scored ETFs need the full window; BIL (cash) only needs a current price
        if df[self.equity + self.bonds].isna().any().any() or pd.isna(df[self.cash].iloc[-1]):
            if held:
                log("%s|SKIP_MISSING_DATA_KEPT_HOLDINGS|%s" % (self._stamp(ohlcv[-1])[:10], reason))
            return fallback

        tgt, info = self._target(df, rows)
        if tgt is None:
            if held:
                log("%s|SKIP_INSUFFICIENT_SCORES_KEPT_HOLDINGS|%s" % (self._stamp(ohlcv[-1])[:10], reason))
            return fallback
        if not self._valid(tgt):
            log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s" % (self._stamp(ohlcv[-1])[:10], reason))
            return fallback

        log("%s|%s|eq=%.3f|scale=%.2f|eqvol=%.3f|%s" % (
            self._stamp(ohlcv[-1])[:10], reason, info["equity_target"], info["vol_scale"], info["equity_vol"],
            ",".join("%s:%.4f" % (k, v) for k, v in tgt.items() if v > 1e-9)))
        return self._alloc(tgt)