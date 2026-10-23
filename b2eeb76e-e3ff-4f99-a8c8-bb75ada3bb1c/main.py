from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import ATR
from surmount.logging import log
import pandas as pd
import math


class TradingStrategy(Strategy):
    """
    Moderate: dual momentum ETF allocation with a gold-ratio gate and an SPY ATR risk-off switch.
    Long only, no leverage, daily bars.

    Risk profile: anchor 60% equity, band 50% to 65% (BIL >= 2%) in the normal regime.
    Universe: 16 equity ETFs, 6 bond ETFs, BIL as cash. SPY (ATR regime) and GLD (ratio gate) are data only, always 0%.

    Score per ETF (-10 to +10), dual momentum on the 12-1 return (close[-22] / close[-253] - 1):
      relative = percentile rank inside its sleeve (equity or bond), mapped to -10..+10
      absolute = +10 if the ETF's 12-1 return beats BIL's, else -10
      Score    = 0.5 * relative + 0.5 * absolute

    Asset gate (replaces the EMA gate): ratio = ETF close / GLD close. The ETF is selectable only if the ratio
    is above its own 100-day SMA. BIL is exempt. Bonds also need Score > 0.
    Absolute momentum filter (abs_mom_filter): an ETF whose 12-1 return does not beat BIL's is excluded outright,
    in both sleeves. Its share falls to BIL. This is what lets the portfolio sit in cash when stocks AND bonds fall.

    Risk-off: SPY ATR(10) >= 80th percentile of its last 252 ATR(10) values (top two deciles), OR ATR(10) > ATR(100).
    When true, equity is excluded and only the bond sleeve is allocated (rest in BIL). Risk-off overrides the
    50% equity floor, like the gate does.

    Allocation (unchanged otherwise): equity top 5, weights proportional to (score + 10), max 40% of sleeve and 25%
    of portfolio; equity budget = anchor * min(1, 15% / 126d basket vol), kept in [floor, anchor]; bond top 4 with
    score > 0 proportional to score; unallocated share to BIL. If the gate leaves too few equities, the equity
    budget shrinks to n_names * 25% and the band floor is relaxed.

    Triggers: first bar of a rebalance period (rebalance_months=1: monthly), nothing held yet, equity above the band, and (regime_daily=True, off by default)
    equity held while risk-off, or equity below the floor. Default: schedule and upper band only.
    No-trade band: a held position is left alone if its target moves less than 2% of the portfolio.

    History: needs 200 bars, fetches up to 260. With fewer than 253 bars the 12-1 lookback shortens
    (rebalance log shows mom_lb). The ATR(10) distribution uses the available values, up to 252.
    Never raises: missing data or history keeps current holdings (or cash if none), and every skip is logged.
    """

    def __init__(self):
        # Universe
        self.equity = ["VT", "IXN", "GSLC", "VIG", "MTUM", "IMTM", "XLV", "XLU", "XLE", "XLP", "QQQ", "RSP", "EFA", "IJT"]
        self.bonds = ["GLD", "AGG", "IEF", "BND", "TIP", "LQD"]
        self.cash = "BIL"
        self.benchmark = "SPY"   # benchmark and ATR regime source, never traded
        self.gold = "TLT"        # ratio gate reference, never traded
        self.trading = self.equity + self.bonds + [self.cash]

        # Risk profile band
        self.e_anchor = 0.6
        self.e_floor = 0.5
        self.e_ceil = 0.65
        self.cash_min = 0.005
        self.max_weight = 0.4

        # Dual momentum (12-1)
        self.mom_lookback = 220
        self.mom_skip = 30

        # Hard absolute momentum filter (12-1 return must beat BIL's)
        self.abs_mom_filter = True

        # GLD ratio gate
        self.ratio_sma = 100

        # SPY ATR risk-off
        self.atr_fast = 10
        self.atr_slow = 50
        self.atr_dist = 252
        self.atr_q = 0.9               # top two deciles
        self.atr_min_obs = 100

        # Volatility targeting
        self.use_vol_target = False
        self.vt_lookback = 126
        self.vt_target = 0.15

        # Selection
        self.n_eq = 5
        self.n_bd = 3
        self.max_sleeve_weight = 0.40

        # Rebalance schedule: monthly (3 = calendar quarters), plus regime triggers
        self.rebalance_months = 1
        self.regime_daily = False   # True = rebalance on any regime flip (heavy turnover)
        self.min_trade = 0.02       # no-trade band: keep a held position if its target moves less than this

        self.min_bars = 200
        self.bars = 260

    @property
    def assets(self):
        return self.trading + [self.benchmark, self.gold]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []  # price data only

    # ---------- helpers ----------
    @staticmethod
    def _stamp(bar):
        for v in bar.values():
            return str(v["date"])
        return ""

    def _period(self, bar):
        stamp = self._stamp(bar)
        try:
            return (int(stamp[:4]) * 12 + int(stamp[5:7]) - 1) // self.rebalance_months
        except ValueError:
            return -1

    def _frame(self, rows):
        """Close prices of trading universe + GLD. Missing tickers become NaN."""
        cols = self.trading + [self.gold]
        return pd.DataFrame({t: [bar[t]["close"] if t in bar else float("nan") for bar in rows] for t in cols})

    @staticmethod
    def _top(score, universe, n):
        return sorted(universe, key=lambda c: (-score[c], universe.index(c)))[:n]

    @staticmethod
    def _cap_normalize(tilt, cap):
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

    def _risk_off(self, rows):
        """True if SPY ATR(10) is in the top 2 deciles of the last 252 values or above ATR(100). None if unknown."""
        try:
            a_f = ATR(self.benchmark, rows, self.atr_fast)
            a_s = ATR(self.benchmark, rows, self.atr_slow)
        except Exception:
            return None
        if not a_f or not a_s:
            return None
        s_f = pd.Series(a_f).dropna()
        cur_s = a_s[-1]
        if len(s_f) < self.atr_min_obs or pd.isna(cur_s):
            return None
        win = s_f.iloc[-self.atr_dist:]
        cur_f = s_f.iloc[-1]
        return bool(cur_f >= win.quantile(self.atr_q) or cur_f > cur_s)

    def _target(self, df, risk_off):
        """Target weights from data up to the current bar. Returns (weights dict or None, info dict)."""
        rets = df.pct_change()
        scored = self.equity + self.bonds
        n = len(df)

        # Dual momentum over the longest lookback available
        L = min(self.mom_lookback, n - 1)
        mom = df.iloc[-1 - self.mom_skip] / df.iloc[-1 - L] - 1.0
        if mom[scored + [self.cash]].isna().any():
            return None, {}
        score = {}
        for group in (self.equity, self.bonds):
            rk = mom[group].rank(pct=True)
            for t in group:
                rel = (rk[t] - 0.5) * 20.0
                ab = 10.0 if mom[t] > mom[self.cash] else -10.0
                score[t] = 0.5 * rel + 0.5 * ab

        # Gate: ETF/GLD ratio above its 100-day SMA
        ratio = df[scored].div(df[self.gold], axis=0)
        sma = ratio.rolling(self.ratio_sma).mean().iloc[-1]
        if sma.isna().any():
            return None, {}
        up = {t: bool(ratio[t].iloc[-1] > sma[t]) for t in scored}

        pos = {t: (not self.abs_mom_filter) or bool(mom[t] > mom[self.cash]) for t in scored}
        eq = [] if risk_off else self._top(score, [t for t in self.equity if up[t] and pos[t]], self.n_eq)
        bd = self._top(score, [t for t in self.bonds if up[t] and pos[t] and score[t] > 0], self.n_bd)

        # Equity sleeve with volatility target
        sig_eq, scale, e_t, w_eq = float("nan"), 1.0, 0.0, {}
        if eq:
            tilt_e = {c: max(score[c] + 10.0, 1.0) for c in eq}
            sleeve_cap = max(self.max_sleeve_weight, 1.0 / len(eq))
            w_eq = self._cap_normalize(tilt_e, sleeve_cap)
            if self.use_vol_target:
                r = sum(rets[c].iloc[-self.vt_lookback:] * w_eq[c] for c in eq)
                sig_eq = float(r.std() * math.sqrt(252))
                if sig_eq > 0:
                    scale = min(1.0, self.vt_target / sig_eq)
            e_t = min(max(self.e_anchor * scale, self.e_floor), self.e_anchor)
            e_t = min(e_t, len(eq) * self.max_weight)
            w_eq = self._cap_normalize(tilt_e, min(sleeve_cap, self.max_weight / e_t))
        limited = e_t < self.e_floor - 1e-9

        # Bond sleeve: gated, score > 0, unallocated share goes to cash
        bond_budget = 1.0 - self.cash_min - e_t
        w_bd = {}
        if bd:
            tilt_b = {c: score[c] for c in bd}
            cap_b = min(self.max_sleeve_weight, self.max_weight / bond_budget)
            w_bd = self._cap_normalize(tilt_b, cap_b)

        tgt = {a: 0.0 for a in self.trading}
        for c in eq:
            tgt[c] = e_t * w_eq[c]
        for c in bd:
            tgt[c] = bond_budget * w_bd[c]
        tgt[self.cash] = max(0.0, 1.0 - sum(v for k, v in tgt.items() if k != self.cash) - 1e-9)
        return tgt, dict(equity_target=e_t, vol_scale=scale, equity_vol=sig_eq, limited=limited,
                         n_eq=len(eq), n_bd=len(bd), mom_lb=L)

    def _sticky(self, tgt, cur):
        """Skip small trades: keep a held position when the target is within min_trade of it. BIL absorbs the rest."""
        out = dict(tgt)
        for a in self.trading:
            if a != self.cash and cur[a] > 0 and out[a] > 0 and cur[a] <= self.max_weight \
                    and abs(out[a] - cur[a]) < self.min_trade:
                out[a] = cur[a]
        out[self.cash] = max(0.0, 1.0 - sum(v for k, v in out.items() if k != self.cash) - 1e-9)
        return out

    def _valid(self, w, relax_floor=False):
        e = sum(w[c] for c in self.equity)
        return (sum(w.values()) <= 1.0 + 1e-9 and min(w.values()) >= -1e-12
                and max(v for k, v in w.items() if k != self.cash) <= self.max_weight + 1e-9
                and (relax_floor or e >= self.e_floor - 1e-9) and e <= self.e_ceil + 1e-9)

    def _alloc(self, w):
        out = {a: float(w.get(a, 0.0)) for a in self.trading}
        out[self.benchmark] = 0.0
        out[self.gold] = 0.0
        total = sum(out.values())
        if total > 1.0:
            out = {k: v / total for k, v in out.items()}
        return TargetAllocation(out)

    # ---------- strategy ----------
    def run(self, data):
        ohlcv = data["ohlcv"]
        if len(ohlcv) < self.min_bars:
            if len(ohlcv) % 50 == 0:
                log("WAITING_FOR_HISTORY|have=%d|need=%d" % (len(ohlcv), self.min_bars))
            return TargetAllocation({})

        holdings = data.get("holdings") or {}
        cur = {a: float(holdings.get(a) or 0.0) for a in self.trading}
        invested = sum(cur.values())
        equity_now = sum(cur[a] for a in self.equity)
        stamp = self._stamp(ohlcv[-1])[:10]

        rows = ohlcv[-self.bars:]
        risk_off = bool(self._risk_off(rows))  # unknown regime counts as risk-on

        new_period = self._period(ohlcv[-1]) != self._period(ohlcv[-2])
        if invested < 0.5:
            reason = "initial"
        elif new_period:
            reason = "scheduled"
        elif self.regime_daily and risk_off and equity_now > 0.05:
            reason = "risk_off"
        elif equity_now > self.e_ceil + 1e-9 or (self.regime_daily and equity_now < self.e_floor - 1e-9):
            reason = "band"
        else:
            return self._alloc(cur)

        df = self._frame(rows)
        held = invested >= 0.5
        fallback = self._alloc(cur) if held else TargetAllocation({})
        need = self.equity + self.bonds + [self.gold]
        if df[need].isna().any().any() or pd.isna(df[self.cash].iloc[-1]):
            log("%s|SKIP_MISSING_DATA|held=%s|%s" % (stamp, held, reason))
            return fallback

        tgt, info = self._target(df, risk_off)
        if tgt is None:
            log("%s|SKIP_INSUFFICIENT_DATA|held=%s|%s" % (stamp, held, reason))
            return fallback
        if reason == "band" and info["limited"]:
            return self._alloc(cur)  # equity is low because of the filters, not drift: do not churn
        if held:
            tgt = self._sticky(tgt, cur)
        if not self._valid(tgt, info["limited"]):
            log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s" % (stamp, reason))
            return fallback

        turn = sum(abs(tgt[a] - cur[a]) for a in self.trading) / 2.0
        log("%s|%s|riskoff=%s|turn=%.3f|eq=%.3f|scale=%.2f|eqvol=%.3f|pass=%d/%d|mom_lb=%d|%s" % (
            stamp, reason, risk_off, turn, info["equity_target"], info["vol_scale"], info["equity_vol"],
            info["n_eq"], info["n_bd"], info["mom_lb"],
            ",".join("%s:%.4f" % (k, v) for k, v in tgt.items() if v > 1e-9)))
        return self._alloc(tgt)