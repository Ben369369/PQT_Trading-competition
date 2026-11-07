"""Team59: predictive market maker on all four symbols.

    pqt backtest strategies/team59.py --data data --name s01
    pqt run strategies/team59.py --mode test --server https://sandbox.princeton-quant.com --cancel-on-disconnect

How it works (plain English)
----------------------------
Every half-second, for each symbol:
1. Estimate a FAIR VALUE = current mid + a forecast of where the mid will be in 60 s.  The forecast
   is a linear model fitted on the 24 historical sessions (analysis/model.py).  Main ingredients:
   order-book imbalance, recent momentum, HPPO's recent moves (CRRT moves opposite to HPPO), and
   the ETF gap HPPO - (BNKY + 2 BRRY) (BRRY catches up to what HPPO implies).
2. Rest one BID below fair and one ASK above fair (we earn the spread + maker rebate).  If we hold
   inventory, both quotes shift to sell it off (long -> lower prices).
3. If the other side's quote is clearly wrong versus fair (more than a per-symbol edge beyond fees),
   trade against it immediately (IOC).
Safety: kill switch, soft position caps, an exposure guard, pull quotes on news and halts, never
trade against our own orders, and stay under the message budget.

Every knob below shows up in the GUI's model-control panel and can be changed live.
"""

from collections import deque
import math
import re

from pqt_client.v2 import BatchState, ParamKind, ParamSpec, Side, Strategy

SYMS = ("HPPO", "BNKY", "CRRT", "BRRY")
HIST = 1205  # batches of history kept (10 minutes for the inventory tilt)
# Inventory tilt for RAW PnL: beyond 60 s prices mean-revert (analysis/drift_test.py; BNKY corr
# -0.21/-0.32 in two halves). Target position = -TILT x (10-minute move in cents), capped.
TILT = {"BNKY": 75.0, "CRRT": 40.0}  # shares per cent of 10-minute move
TILT_MAX = {"BNKY": 1800, "CRRT": 1000}

# Forecast of mid(t+60s) - mid(t), in cents (fitted on all 24 sessions by analysis/model.py).
# Features: imb_sp = (bidq-askq)/(bidq+askq) * spread/2 ; gap = HPPO - (BNKY + 2 BRRY) mids ;
# dHk = HPPO mid change over last k batches ; dSk = own mid change over last k batches.
COEFS = {
    "HPPO": {"imb_sp": 0.7684, "gap": -0.051, "dH10": 0.648, "dS10": 0.0, "dH40": 0.4044,
             "dS40": 0.0, "dH120": 0.0488, "dS120": 0.0},
    "BNKY": {"imb_sp": 0.7169, "gap": 0.0105, "dH10": 0.1096, "dS10": 0.2522, "dH40": 0.0197,
             "dS40": 0.4694, "dH120": 0.0223, "dS120": -0.0285},
    "CRRT": {"imb_sp": 0.3543, "gap": -0.0096, "dH10": -0.1736, "dS10": 0.0244, "dH40": -0.1097,
             "dS40": 0.3021, "dH120": -0.0116, "dS120": 0.016},
    "BRRY": {"imb_sp": 0.1828, "gap": 0.2644, "dH10": 0.2695, "dS10": 0.0102, "dH40": 0.1793,
             "dS40": 0.0788, "dH120": 0.0268, "dS120": -0.0181},
}
CAP = {"HPPO": 700, "BNKY": 2000, "CRRT": 2000, "BRRY": 450}  # soft position caps (shares)
BASE_SIZE = {"HPPO": 40, "BNKY": 120, "CRRT": 120, "BRRY": 25}  # shares per quote at size=1
TAKE_CLIP = {"HPPO": 120, "BNKY": 300, "CRRT": 300, "BRRY": 60}  # max shares per aggressive take
# cents of edge beyond the taker fee needed to snipe a stale quote (held-out test: analysis/snipe_test.py)
TAKE_EDGE = {"HPPO": 1.0, "BNKY": 1.0, "CRRT": 1.0, "BRRY": 1.5}
EXPO_WEIGHT = {"HPPO": 1.0, "BNKY": 0.15, "CRRT": -0.29, "BRRY": 0.425}
EXPO_SOFT = 500  # stay inside +-500 net exposure (the hard limit is 600)
TAKER_FEE = 0.4  # cents per share
TICKERS = re.compile(r"\b(HPPO|BNKY|BRRY|CRRT)\b")
REPORT_EVERY = 120  # one status line a minute


class Team59(Strategy):
    MODEL_PARAMS = (
        ParamSpec("on", ParamKind.BOOL, 1),  # master switch: 0 = cancel everything, trade nothing
        ParamSpec("trade_HPPO", ParamKind.BOOL, 1),
        ParamSpec("trade_BNKY", ParamKind.BOOL, 1),
        ParamSpec("trade_CRRT", ParamKind.BOOL, 1),
        ParamSpec("trade_BRRY", ParamKind.BOOL, 1),
        ParamSpec("width", ParamKind.FLOAT, 1.0, 0.3, 5.0),  # x the default distance from fair
        ParamSpec("size", ParamKind.FLOAT, 1.5, 0.0, 4.0),  # x the default quote size
        ParamSpec("skew", ParamKind.FLOAT, 4.0, 0.0, 30.0),  # cents of lean at a full soft cap
        ParamSpec("inv_tilt", ParamKind.FLOAT, 0.0, 0.0, 2.0),  # raw-PnL inventory gamble (0 = off)
        ParamSpec("expo_skew", ParamKind.FLOAT, 4.0, 0.0, 30.0),  # cents of lean at exposure 600
        ParamSpec("take_mult", ParamKind.FLOAT, 3.0, 0.2, 10.0),  # x per-symbol snipe threshold
        ParamSpec("imb_scale", ParamKind.FLOAT, 1.0, 0.0, 1.5),  # trust in book imbalance (spoof defence)
        ParamSpec("take_on", ParamKind.BOOL, 1),  # allow aggressive (IOC) trades
        ParamSpec("pred_scale", ParamKind.FLOAT, 1.0, 0.0, 2.0),  # trust in the forecast
        ParamSpec("news_pause_s", ParamKind.INT, 20, 0, 300),  # seconds to stand aside on news
        ParamSpec("kill_floor", ParamKind.INT, -4000, -50000, 0),  # dollars; kill switch floor
    )
    # default half-distance from fair, cents (x width)
    HALF = {"HPPO": 2.0, "BNKY": 1.5, "CRRT": 2.0, "BRRY": 4.5}

    def on_start(self) -> None:
        self.mids = {s: deque(maxlen=HIST) for s in SYMS}
        self.aside_until = {s: -1 for s in SYMS}
        self.fills_log: list = []  # (batch, symbol, signed qty, price, fee_mills) for analysis
        self.fair: dict[str, float] = {}
        self.target: dict[str, float] = {}
        self._csv = None
        try:  # local CSV log of fills + mids so Claude can measure 60 s markouts
            import os, time
            os.makedirs("logs", exist_ok=True)
            self._csv = open(f"logs/live_{time.strftime('%H%M%S')}.csv", "a", buffering=1)
            self._csv.write("kind,batch,symbol,qty,price,fee_mills,liq\n")
        except Exception:
            self._csv = None
        self._set_kill()

    def _set_kill(self) -> None:
        floor = int(self.model_params["kill_floor"])
        self.set_kill_switch(floor * 1000 if floor < 0 else None)

    def on_model_params(self, changed) -> None:
        if "kill_floor" in changed:
            self._set_kill()
        if not self.model_params["on"]:
            self.cancel_all()

    def on_reconnect(self) -> None:
        self._set_kill()

    def on_fill(self, fill) -> None:
        q = fill.qty if fill.side is Side.BUY else -fill.qty
        self.fills_log.append((fill.batch, fill.symbol, q, fill.price, fill.fee_mills))
        if self._csv:
            try:
                liq = getattr(fill, "liquidity", "")
                self._csv.write(f"F,{fill.batch},{fill.symbol},{q},{fill.price},{fill.fee_mills},{liq}\n")
            except Exception:
                pass

    def on_news(self, item) -> None:
        named = set(TICKERS.findall(f"{item.headline} {item.body}")) or set(SYMS)
        if "HPPO" in named:  # the ETF moves with its basket and vice versa
            named |= {"BNKY", "BRRY"}
        if named & {"BNKY", "BRRY"}:
            named.add("HPPO")
        pause = int(self.model_params["news_pause_s"]) * 2  # batches
        self.log.warning("NEWS batch %d %s: %s", item.batch, sorted(named), item.headline)
        for s in named:
            self.cancel_all(s)
            self.aside_until[s] = item.batch + pause

    # ------------------------------------------------------------------ main loop
    def on_batch(self, state: BatchState) -> None:
        p = self.model_params
        self._pend_hi = self._pend_lo = 0.0
        for s in SYMS:
            m = state.top[s].mid
            if m is not None:
                self.mids[s].append(m)
            elif self.mids[s]:
                self.mids[s].append(self.mids[s][-1])
            if self._csv and state.batch % 2 == 0 and m is not None:
                try:
                    self._csv.write(f"M,{state.batch},{s},0,{m},0,\n")
                except Exception:
                    pass
        if (state.batch + 1) % REPORT_EVERY == 0:
            self.report(state)
        if not p["on"] or state.blocked or self.kill_switch.engaged:
            return
        gap = None
        if all(self.mids[s] for s in ("HPPO", "BNKY", "BRRY")):
            gap = self.mids["HPPO"][-1] - self.mids["BNKY"][-1] - 2 * self.mids["BRRY"][-1]

        # BRRY first: thinnest book, biggest edge (message budget priority)
        for s in ("BRRY", "HPPO", "CRRT", "BNKY"):
            top = state.top[s]
            if (not p[f"trade_{s}"] or top.halted or state.batch < self.aside_until[s]
                    or top.bid_px is None or top.ask_px is None or gap is None):
                if self.open_orders(s) and self.messages_left() > 0:
                    self.cancel_all(s)
                continue
            fair = self.fair_value(s, state, gap, p["pred_scale"])
            self.fair[s] = fair
            self.trade_symbol(s, state, fair, p)

    def fair_value(self, s, state, gap, scale) -> float:
        top = state.top[s]
        tot = (top.bid_qty or 0) + (top.ask_qty or 0)
        imb = ((top.bid_qty or 0) - (top.ask_qty or 0)) / tot if tot else 0.0
        # imbalance can be faked by spoofers: its effect is bounded by half the spread and scalable
        f = {"imb_sp": self.model_params["imb_scale"] * imb * (top.ask_px - top.bid_px) / 2,
             "gap": gap}
        h, o = self.mids["HPPO"], self.mids[s]
        for k in (10, 40, 120):
            f[f"dH{k}"] = h[-1] - h[-1 - k] if len(h) > k else 0.0
            f[f"dS{k}"] = o[-1] - o[-1 - k] if len(o) > k else 0.0
        pred = sum(c * f[n] for n, c in COEFS[s].items())
        return top.mid + scale * pred

    def exposure_after(self, s, signed_qty) -> float:
        """Worst-case net exposure if signed_qty more of s were added on top of positions+orders."""
        e_long = e_short = 0.0
        for x in SYMS:
            pos = self.position(x)
            buys = sum(o.remaining for o in self.open_orders(x) if o.side is Side.BUY)
            sells = sum(o.remaining for o in self.open_orders(x) if o.side is Side.SELL)
            w = EXPO_WEIGHT[x]
            hi, lo = pos + buys, pos - sells
            e_long += max(w * hi, w * lo)
            e_short += min(w * hi, w * lo)
        e_long += self._pend_hi  # orders sent earlier this batch, not yet acknowledged
        e_short += self._pend_lo
        w = EXPO_WEIGHT[s] * signed_qty
        return max(abs(e_long + max(w, 0)), abs(e_short + min(w, 0)))

    def _note(self, s, side, q) -> None:
        """Remember the worst-case exposure an order sent this batch adds."""
        if q <= 0:
            return
        x = EXPO_WEIGHT[s] * q * (1 if side is Side.BUY else -1)
        if x > 0:
            self._pend_hi += x
        else:
            self._pend_lo += x

    def trade_symbol(self, s, state, fair, p) -> None:
        top = state.top[s]
        pos = self.position(s)
        cap = CAP[s]
        # lean against our own position, and against total net exposure (ETF-equivalent shares)
        expo = state.exposure / 1000
        w = EXPO_WEIGHT[s]
        target = 0.0
        if s in TILT and p["inv_tilt"] > 0 and len(self.mids[s]) > 1200:
            move = self.mids[s][-1] - self.mids[s][-1201]
            target = max(-TILT_MAX[s], min(TILT_MAX[s], -TILT[s] * p["inv_tilt"] * move))
        self.target[s] = target
        centre = (fair - p["skew"] * (pos - target) / cap
                  - p["expo_skew"] * (expo / 600) * (1 if w > 0 else -1) * (abs(w) ** 0.5))
        half = self.HALF[s] * p["width"]
        size = max(0, int(round(BASE_SIZE[s] * p["size"])))
        largest = self.symbol_info[s].max_order_qty

        # 1) aggressive take when the book is clearly wrong vs our fair value
        took = False
        if p["take_on"] and size > 0:
            edge = TAKE_EDGE[s] * p["take_mult"] + TAKER_FEE
            if centre - top.ask_px > edge and pos < cap:
                q = min(TAKE_CLIP[s], top.ask_qty or 0, cap - pos, largest)
                if q > 0 and self.exposure_after(s, q) <= EXPO_SOFT and self.messages_left() > 3:
                    self._clear_own(s, Side.SELL, top.ask_px)  # never trade with ourselves
                    self.buy(s, q, top.ask_px, ioc=True)
                    self._note(s, Side.BUY, q)
                    took = True
            elif top.bid_px - centre > edge and pos > -cap:
                q = min(TAKE_CLIP[s], top.bid_qty or 0, cap + pos, largest)
                if q > 0 and self.exposure_after(s, -q) <= EXPO_SOFT and self.messages_left() > 3:
                    self._clear_own(s, Side.BUY, top.bid_px)
                    self.sell(s, q, top.bid_px, ioc=True)
                    self._note(s, Side.SELL, q)
                    took = True
        if took:
            return  # requote next batch, once the take's result is known

        # 2) passive quotes, never crossing the book
        bid = min(math.floor(centre - half), top.ask_px - 1)
        ask = max(math.ceil(centre + half), top.bid_px + 1)
        if bid >= ask:
            bid, ask = ask - 1, bid + 1
        # bet more where the expected edge is bigger (between 0.5x and 2.5x the base size)
        def scaled(edge_c):
            return int(round(size * min(2.5, max(0.5, edge_c / max(half, 0.5)))))
        bq = min(scaled(fair - bid), cap - pos, largest)
        aq = min(scaled(ask - fair), cap + pos, largest)
        now = self.exposure_after(s, 0)
        if bq > 0 and self.exposure_after(s, bq) > max(EXPO_SOFT, now):
            bq = 0  # this bid would push worst-case exposure past the soft limit
        if aq > 0 and self.exposure_after(s, -aq) > max(EXPO_SOFT, now):
            aq = 0
        self.keep_quote(s, Side.BUY, bid if bq > 0 else None, bq)
        self.keep_quote(s, Side.SELL, ask if aq > 0 else None, aq)

    def _clear_own(self, s, side, price) -> None:
        for o in self.open_orders(s):
            if o.side is side and ((side is Side.SELL and o.price <= price)
                                   or (side is Side.BUY and o.price >= price)):
                self.cancel(order_id=o.order_id)

    def keep_quote(self, s, side, price, size) -> None:
        """Exactly one resting order on this side at price (none if price is None), cheaply."""
        mine = [o for o in self.open_orders(s) if o.side is side]
        for extra in mine[1:]:
            if self.messages_left() > 0:
                self.cancel(order_id=extra.order_id)
        if self.messages_left() <= 0:
            return
        if price is None:
            if mine:
                self.cancel(order_id=mine[0].order_id)
        elif not mine:
            (self.buy if side is Side.BUY else self.sell)(s, size, price)
            self._note(s, side, size)
        elif mine[0].price != price or mine[0].remaining < size // 2:
            self.replace(order_id=mine[0].order_id, price=price, qty=size)
            self._note(s, side, size - mine[0].remaining)

    def report(self, state: BatchState) -> None:
        parts = []
        for s in SYMS:
            f = self.fair.get(s)
            parts.append(f"{s} {self.position(s):+d}" + (f" fair {f / 100:.2f}" if f else ""))
        self.log.info("min %d | %s | expo %+.0f | estPnL $%.2f", (state.batch + 1) // 120,
                      " | ".join(parts), state.exposure / 1000, state.pnl_est_mills / 1000)

    def on_reject(self, reject) -> None:
        code = getattr(reject, "code", None) or getattr(reject, "reason", "")
        if str(code).endswith(("UNKNOWN_ORDER", "NOT_RUNNING")):
            return  # harmless: the order filled while we moved it / the session just ended
        self.log.warning("reject: %s", reject)
