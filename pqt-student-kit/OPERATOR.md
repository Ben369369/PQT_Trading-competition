# Team59 Operator Cheat Sheet

## What the program does (30-second version)
Every half-second it estimates each stock's **fair value**: where the price should be in about 60 s.
It keeps one **bid** below fair and one **ask** above fair, and earns the gap plus a rebate when others trade with it.
When it holds shares, it shifts its prices to get rid of them. When another trader's price is clearly wrong, it trades against it straight away.
On **news** or a **halt** it pulls its quotes. If losses reach the **kill floor**, the exchange stops it.

## Start it

```powershell
cd "$HOME\OneDrive - Princeton University\Desktop\PQT Trading Competition\pqt-student-kit"
.\.venv\Scripts\Activate.ps1
$env:PQT_API_KEY = "pqt_...algo1..."
# sandbox (practice):
pqt run strategies/team59.py --mode test --server https://sandbox.princeton-quant.com --cancel-on-disconnect
# COMPETITION (Saturday):
pqt run strategies/team59.py --mode live --server https://play.princeton-quant.com --cancel-on-disconnect
```
- Run **only one** copy of the program, using **algo1**. Keep algo2 as a spare in case algo1 has a problem.
- Don't place manual GUI orders in symbols the program is trading. You could trade against yourself, which costs $0.10/share.
- Stop the program with **Ctrl+C**. With `--cancel-on-disconnect`, its orders are cancelled.

## The knobs (GUI → model-control panel)

| Knob | Default | What it does | When to change it |
|---|---|---|---|
| `on` | 1 | Master switch. 0 = cancel everything and stop trading | Something looks wrong → set it to 0 first, think second |
| `trade_HPPO` / `_BNKY` / `_CRRT` / `_BRRY` | 1 | Turns each symbol on or off | The report shows one symbol losing → turn it off |
| `width` | 1.0 | Distance of the quotes from fair (multiplier) | Getting picked off (price moves against you right after fills) → 1.3–2.0. Very few fills → 0.8 |
| `size` | 1.5 | Shares per quote (multiplier). It's already risk-seeking, and quotes grow up to 2.5x on their own when the edge is big | R1 went well → 2–2.5 for R2. Going badly → 0.7 |
| `skew` | 4 | How hard it sells off its own inventory | Positions keep hitting the caps → 8–10 |
| `expo_skew` | 4 | How hard it reduces total net exposure | Exposure is near ±450 for a long time → 8 |
| `take_mult` | 1.0 | Multiplies the snipe thresholds (HPPO/BNKY/CRRT 1.0¢, BRRY 1.5¢ beyond the fee) | Aggressive (TAKER) fills losing in the report → 2–3. To turn them off, use `take_on` |
| `imb_scale` | 1.0 | How much we trust the buy/sell sizes waiting in the book | Book sizes look fake (huge orders appearing and vanishing = someone spoofing) → 0 |
| `take_on` | 1 | Allows aggressive (IOC) trades | Set to 0 if they look bad |
| `inv_tilt` | 0 | Raw-PnL gamble: holds BNKY/CRRT against the last 10-minute move (prices mean-revert beyond 60 s). Costs ~3% of skill score | Only under the R2 rule below |
| `pred_scale` | 1.0 | How much to trust the forecast | Live market behaves very differently from the history → 0.5 |
| `news_pause_s` | 20 | Seconds to step aside after news | Big moves after news → 60 |
| `kill_floor` | -4000 | Exchange stops us if realized PnL falls to this ($) | Leave it alone. Lower it only if we're clearly scoring well but PnL is swinging |

## What to watch
- **The terminal prints one line a minute:** position and fair value per symbol, total exposure, and estimated PnL.
- **Many `reject:` warnings** (other than `UNKNOWN_ORDER`, which is harmless) → tell the coder. `RATE_LIMIT` means too many messages.
- **Positions stuck at their caps** (HPPO ±700, BNKY/CRRT ±2000, BRRY ±450) → raise `skew`. "Stuck" means the **same sign** at the cap for 3+ status lines in a row. Flipping from +2000 to −2000 between lines is normal: the sandbox did that all session and still finished positive.
- **Estimated PnL dips of about −$1,000** are normal (sandbox: −$1,100 at min 12, then +$2,500 at the end). Act only if it goes below −$2,500 **and** the report shows negative scores.
- **Estimated PnL** is *not* the score. Positions marked at the market make it swing a lot. Don't panic over swings.

## Emergencies
1. Set `on` = 0 in the panel, **or** use the GUI kill switch, **or** press Ctrl+C.
2. Program crashed or disconnected → restart it with the same command.
3. Laptop died → teammate starts the same command on their laptop with **algo2**.

## The 3:00 break (most important 15 minutes). R1 = 2:15–3:00, R2 = 3:15–4:00
**The program stops at the end of R1.** Start it again for R2 with the same command. Panel values go back to the defaults,
so **re-enter any R2 changes in the panel right after it reconnects**. The kill switch resets on its own.
Read the official R1 report in the GUI's **Session reports** panel at the bottom of the page. It arrives a couple of minutes after R1.
It shows the score for each symbol and the markout curves at 1/10/30/60 s.
- **Symbol score < 0** → turn that symbol off for R2, or double its width.
- **Markouts falling from 1 s to 60 s** (we're getting picked off) → `width` 1.5.
- **Everything positive** → `size` 1.5–2.0 for R2. R2 counts **double**.
Do **not** edit code during the break unless something is clearly broken.

## Prizes and the pre-written R2 rule (decided Nov 6, do not renegotiate on the day)
- **Skill-adjusted PnL** = the markout score. Our whole strategy targets it.
- **Raw PnL** = score + luck from positions held past 60 s. In backtests our raw PnL ≈ our skill score, so **the same strategy competes for both.**
- **R2 rule:**
  - If our R1 score is in roughly the top 10 → change nothing except `size` (see above).
  - If we're clearly mid-pack after R1 → set `inv_tilt` = 1.5 for R2. That adds variance, which only helps when you're behind. Never raise it above 2.
- **Ask at the 9:30 briefing:**
  1. Is skill-adjusted PnL the markout score from the guide?
  2. Is raw PnL also R1 + 2×R2?
  3. Can we see standings after R1?
