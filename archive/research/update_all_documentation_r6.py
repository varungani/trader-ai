"""
Update README.md and TRADER_AI_ARCHITECTURE_AND_TECHNICALS.md for Review Round 6
"""
import os, re

def update_technical_doc():
    path = "TRADER_AI_ARCHITECTURE_AND_TECHNICALS.md"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update version
    content = content.replace(
        "> **Document Version:** 2.3.0-fortress-patterns",
        "> **Document Version:** 2.3.0-empirical-audit"
    )

    # 2. Section 14.5 replacement
    old_sec_14_5_start = "### 14.5 Option 1: 5-Year Widened Universe (136 Stocks) Swing Momentum Empirical Test"
    old_sec_15_start = "## 15. Regulatory & Legal Disclaimer"
    
    idx_14_5 = content.find(old_sec_14_5_start)
    idx_15 = content.find(old_sec_15_start)
    
    if idx_14_5 == -1 or idx_15 == -1:
        raise ValueError(f"Could not locate Section 14.5 or Section 15 markers in {path}")

    new_sec_14_5_to_14_7 = """### 14.5 Option 1: 5-Year Widened Universe (136 Stocks) Swing Momentum Empirical Test

To resolve the **"Large-Cap Cost Trap"** (where 25 low-beta large caps move only 2%–4% in 15 days, allowing ₹75 statutory delivery friction to consume 30%–50% of trade gains), we widened the universe to **136 liquid Indian equities** (Nifty 100 + Liquid Midcaps) across a **5-year empirical horizon (2021–2026, ~1,250 trading bars)**.

The backtest was executed via [`backtesting/swing_midcap_backtest.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/backtesting/swing_midcap_backtest.py) with exact Indian statutory delivery costs (STT, GST, flat ₹15.93 CDSL DP charges, 5 bps slippage) and stop-first daily bar sequencing.

#### 5-Year Comparative Performance Matrix:

| Strategy / Benchmark | Total Trades | Win Rate | Total Net Return | Avg % Invested | Matched Benchmark | Matched Alpha | Avg Win | Avg Loss | Payoff (W/L) | Profit Factor | Expectancy / Trade (95% Block CI) | Two-Sided p-Val | Max DD | Sharpe |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Benchmark: NIFTYBEES** | — | — | **+32.7%** | 100.0% | — | — | — | — | — | — | — | — | -17.5% | 0.88 |
| **Benchmark: MID150BEES** | — | — | **+81.6%** | 100.0% | — | — | — | — | — | — | — | — | -22.1% | **1.15** |
| **Benchmark: Equal-Weight 136 Universe** | — | — | **+104.6%** | 100.0% | — | — | — | — | — | — | — | — | -24.8% | 1.02 |
| **Option 1A: 20 EMA Pullback Swing (20D hold)** | 359 | 34.0% | **+11.1%** | 46.1% | +48.2% | **-37.1%** | ₹1,709 | ₹833 | 2.05 : 1 | 1.06 | +₹31.0 [-₹112, +₹174] | 0.652 | -28.3% | 0.27 |
| **Option 1B: Volume 50D Breakout Swing (20D hold)** | 331 | 43.2% | **+62.2%** | **42.3%** | +47.7% | **+14.5%** | ₹1,596 | ₹883 | 1.81 : 1 | 1.37 | **+₹187.8** [+₹16.8, +₹352.4] | **0.0284** | **-9.91%** | 1.11 |
| **Option 1C: Dual-Engine Swing (Pullback+Breakout)** | 374 | 39.0% | **+36.6%** | 48.5% | +50.7% | **-14.1%** | ₹1,644 | ₹892 | 1.84 : 1 | 1.18 | +₹97.9 [-₹35, +₹231] | 0.164 | -14.4% | 0.68 |

#### Critical Quantitative Audit & Methodological Caveats:
1. **Unmatched Gross Return Did NOT Beat Buy-and-Hold**:
   Option 1B returned **+62.2%**, trailing both the Equal-Weight Universe (+104.6%) and MID150BEES (+81.6%). Its Sharpe ratio (**1.11**) is below MID150BEES (**1.15**).
   The lower drawdown (-9.91% vs -22.1%) is primarily a mechanical artifact of holding **57.7% cash on average** (average exposure was only 42.3%). On an exposure-matched basis, alpha vs the universe is **+14.5%**, but zero vs raw buy-and-hold.
2. **Survivorship Bias Warning**:
   The 136-stock universe was constructed from liquid Nifty 100 and midcap constituents as of 2026. The equal-weight basket gained +104.6% vs +32.7% for NIFTYBEES (over 3.2x the index), indicating severe survivorship tilt (delisted, bankrupt, or severely impaired companies from 2021–2026 are excluded).
3. **Severe Regime Concentration**:
   Option 1B profits were concentrated in the 2023–2024 bull run:
   - 2023 contributed **+₹33,366.6** (~54% of all profits).
   - 2023–2024 combined contributed **+₹53,321.0** (~85% of all profits).
   - Trailing 21 Months (Jan 2025 – Oct 2026): **+₹2,233.0 net profit** (2025: -₹398; 2026 YTD: +₹2,631). Performance over the last two years has been effectively flat. Forward expectations should be anchored on flat periods, not the 2023 anomaly.
4. **Multiple Testing Failure under Family-Wise Error Correction**:
   Option 1B’s $t = +2.54$ yields a two-sided $p = 0.011$. Under a stationary block bootstrap (block size 10 trades, 5,000 resamples), the two-sided p-value is **$p = 0.0284$** (95% CI $[+₹16.77, +₹352.38]$). When adjusted for family-wise error across multiple parameter sweeps (Bonferroni threshold $\alpha \le 0.005$), Option 1B **fails** the multiple-testing hurdle. It represents an in-sample hypothesis, not a proven statistical certainty.

---

### 14.6 Empirical Pattern Mining: Full 7-Pattern In-Sample Disclosure

To test individual technical claims, we simulated **all 7 price-action and volume patterns** across the 136-stock universe over 5 years (1,236 sessions) with exact statutory Indian delivery friction (STT, GST, ₹15.93 CDSL DP fee, slippage) on an initial capital of ₹30,000.

#### Complete 7-Pattern In-Sample Benchmark Matrix (No Omissions):

| Pattern Strategy | 5Y Trades | Win Rate | Total Net P&L (₹30k cap) | Profit Factor | Payoff Ratio | Max Drawdown | Best Month | Worst Month | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1. Baseline 50D Breakout** (No Base) | 177 | 40.1% | **-₹2,792.1** | 0.93 | 1.39 : 1 | -22.9% | +₹2,262.5 | -₹3,565.7 | Failed |
| **2. Minervini VCP Contraction** ($VCP \le 0.65$) | 150 | 45.3% | **+₹18,854.0** | 1.56 | 1.88 : 1 | -11.3% | +₹3,806.7 | -₹2,306.9 | In-Sample Candidate |
| **3. Raw RS High Leader** (No Base) | 180 | 36.1% | **-₹5,193.0** | 0.89 | 1.57 : 1 | -32.8% | +₹1,950.0 | -₹3,210.0 | Failed |
| **4. 20 EMA Sweet-Spot Pullback** ($0\text{-}2.2\%$) | 177 | 44.6% | **+₹20,153.1** | 1.55 | 1.92 : 1 | -10.5% | +₹3,447.1 | -₹2,091.1 | In-Sample Candidate |
| **5. Volume Dry-Up (VDU) Breakout** | 121 | 37.2% | **+₹1,489.0** | 1.05 | 1.77 : 1 | -23.3% | +₹2,100.0 | -₹2,840.0 | Marginal / Inconclusive |
| **6. Master Confluence (Stage 2+VCP+RS+SweetSpot)** | 41 | 24.4% | **-₹5,118.5** | 0.42 | 1.30 : 1 | -18.7% | +₹562.6 | -₹713.5 | Failed (Over-Filtered) |
| **7. Master Confluence + Uncapped Runner** | 40 | 32.5% | **-₹3,087.8** | 0.65 | 1.35 : 1 | -16.3% | +₹1,275.4 | -₹785.3 | Failed (Over-Filtered) |

#### Critical Takeaways:
1. **Extreme Parameter Fragility (Symptom of In-Sample Noise Fitting)**:
   - 50-day breakout varied from **+₹62,159** (Option 1B: 12% target, 5 positions of ₹20k) to **-₹2,792** (Pattern 1: 15% target, 3 positions of ₹10k).
   - 20 EMA pullback varied from **+11.1%** (Option 1A: 20D hold, 5 positions) to **+67.2%** (Pattern 4: Sweet Spot rebound).
   - When minor rule adjustments cause strategies to flip from strong profits to net losses, it signals high sensitivity to parameter tuning rather than structural market robustness.
2. **Look-Ahead Execution Timing Warning**:
   All patterns utilizing `Close > Open`, `Close >= high20`, daily RVOL, or VCP ratios require the daily close to compute. Simulating entry at the exact same close is a look-ahead flaw. In live trading, orders must be executed at the **next trading session Open**, absorbing overnight gap risk and slippage.
3. **Over-Filtering Penalty (Patterns 6 & 7)**:
   Demanding simultaneous confluence across 5 indicators reduced trade sample size to ~40 over 5 years (<8 trades/year), resulting in negative returns (-₹5,118) because entries occurred after the bulk of the momentum move had already passed.

---

### 14.7 Live Gating Architecture vs Backtest Reconciliation

The live production engine implements a composite rule set that combines multiple filters:

#### 1. The 5 Fortress Gating Filters (`engine/recommender.py`):
* **Gate 1: Zero-Tolerance Sector Drag**: Candidates in sectors with negative Relative Strength vs Nifty ($Sector\ RS < 0.0\%$) are forced to `HOLD (SECTOR_DRAG)`.
* **Gate 2: Minervini Stage 2 Trend Template**: Price must satisfy $Close > EMA_{50} > SMA_{200}$ (Stage 3/4 distribution prohibited).
* **Gate 3: Sweet-Spot Entry Corridor**: Distance to the 20 EMA must be within $-2.0\% \le \text{deviation} \le +4.0\%$.
* **Gate 4: Volume Confirmation**: Relative Volume ($RVOL$) must be $\ge 1.05\times$ to $1.4\times$ 20-day average.
* **Gate 5: Absolute Macro Regime Circuit Breaker**: If Nifty is below its 50 SMA, fresh BUYs are **strictly vetoed with zero exceptions** (`100% CASH PRESERVATION`).

#### 2. Sector Allocation Multipliers & Hard Position Caps:
* Multipliers (`LEADING` = 1.35x, `SEVERE_DRAG` = 0.50x) adjust relative weighting among candidates, but **must never breach the immutable 20.0% single-position cap** (`RISK_CONFIG['max_position_pct'] = 0.20`) on 5-position portfolios, or 33.3% on 3-position small-capital portfolios. Any unallocated balance remains in cash.

#### 3. Unification of Exit Policies:
* **Session 10 Stagnation Exit**: If an open trade remains bounded within $\pm 2.0\%$ at session 10, it is exited at market price to prevent dead money.
* **Session 15–20 Hard Time Expiry**: Positions hitting neither stop nor target exit by session 15 (live rule) / session 20 (backtest benchmark).

> [!WARNING]
> **Live Rules Have Not Been Backtested End-to-End**:
> The composite combination of the 5 Fortress Gates, Sector Tournament Multipliers, 10-session Stagnation Exit, and Score $\ge 72$ has **NOT been simulated as a unified end-to-end backtest across 5 years**. It represents a synthesis of standalone heuristics and **must be validated via the forward paper graduation protocol before deploying real capital**.

---

"""

    content = content[:idx_14_5] + new_sec_14_5_to_14_7 + content[idx_15:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Successfully updated {path}")

def update_readme():
    path = "README.md"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update Decision Thresholds
    thresh_repl = """> **Decision Thresholds (Harmonized with config.py)**:
> * $\\ge 72/100$ = **BUY** (requires clearing all 5 Institutional Edge Gates, sector tailwinds, and R:R $\\ge 2.0$)
> * $40.0 \\text{ to } 71.9$ = **HOLD** (active position monitoring; capital preservation)
> * $\\le 40.0$ = **SELL / AVOID**"""
    content = re.sub(
        r"> \*\*Decision Thresholds.*?\n> \* \\le 44\.9 = \*\*SELL / AVOID\*\*",
        lambda m: thresh_repl,
        content,
        flags=re.DOTALL
    )

    # 2. Update Gate 5 (remove score >= 80 leak)
    content = content.replace(
        "When NIFTY 50 breaks below its 50-day SMA, all fresh BUY entries are frozen (`100% CASH PRESERVATION`), unless an individual scrip scores an exceptional $\\ge 80$.",
        "When NIFTY 50 breaks below its 50-day SMA, all fresh BUY entries are strictly vetoed with zero exceptions (`100% CASH PRESERVATION`)."
    )

    # 3. Update Pattern Table with ALL 7 patterns and In-Sample disclaimer
    pattern_section = """## 🎯 In-Sample Pattern Mining Simulation Results (Not Forward Guidance)

Simulation across **136 NSE equities over 5 years (1,236 trading sessions)** under exact Indian statutory delivery friction (STT, GST, flat ₹15.93 CDSL DP fee, slippage) on ₹30,000 initial capital. These represent **in-sample hypotheses requiring forward paper validation**, not guaranteed statistical certainty:

| Pattern Strategy | 5Y Trades | Win Rate | Total Net P&L (₹30k cap) | Profit Factor | Payoff Ratio | Max Drawdown | Best Month | Worst Month | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1. Blind 50D Breakout** (No Base) | 177 | 40.1% | **-₹2,792.1** | 0.93 | 1.39 : 1 | -22.9% | +₹2,262.5 | -₹3,565.7 | Failed |
| **2. Minervini VCP Contraction** ($VCP \\le 0.65$) | 150 | 45.3% | **+₹18,854.0 (+62.8%)** | **1.56** | **1.88 : 1** | **-11.3%** 🛡️ | +₹3,806.7 | -₹2,306.9 | In-Sample Candidate |
| **3. Raw RS High Leader** (No Base) | 180 | 36.1% | **-₹5,193.0** | 0.89 | 1.57 : 1 | -32.8% | +₹1,950.0 | -₹3,210.0 | Failed |
| **4. 20 EMA Sweet-Spot Pullback** ($0\\text{-}2.2\%$) | 177 | 44.6% | **+₹20,153.1 (+67.2%)** | **1.55** | **1.92 : 1** | **-10.5%** 🛡️ | +₹3,447.1 | -₹2,091.1 | In-Sample Candidate |
| **5. Volume Dry-Up (VDU) Breakout** | 121 | 37.2% | **+₹1,489.0** | 1.05 | 1.77 : 1 | -23.3% | +₹2,100.0 | -₹2,840.0 | Marginal / Inconclusive |
| **6. Master Confluence (Stage 2+VCP+RS+SweetSpot)** | 41 | 24.4% | **-₹5,118.5** | 0.42 | 1.30 : 1 | -18.7% | +₹562.6 | -₹713.5 | Failed (Over-Filtered) |
| **7. Master Confluence + Uncapped Runner** | 40 | 32.5% | **-₹3,087.8** | 0.65 | 1.35 : 1 | -16.3% | +₹1,275.4 | -₹785.3 | Failed (Over-Filtered) |

> ⚠️ **Severe Caveats**: 
> 1. **Survivorship Bias**: The 136-stock universe beat NIFTYBEES by 3.2x (+104.6% vs +32.7%), confirming substantial survivorship tilt.
> 2. **Regime Concentration**: Option 1B generated ~85% of its profits during 2023–2024; the trailing 21 months (2025 to Oct 2026) were practically flat (+₹2,233).
> 3. **Rule Fragility**: Shifting target from 12% to 15% flipped 50D Breakout from +₹62k to -₹2.8k, demonstrating parameter sensitivity."""

    content = re.sub(
        r"## 🎯 The Two Verified Monster Patterns.*?(?=## 🏆 Dynamic Sector Momentum Tournament)",
        lambda m: pattern_section + "\n\n---\n\n",
        content,
        flags=re.DOTALL
    )

    # 4. Update Monthly Expectations to In-Sample Simulation Results
    horizon_section = """## ⏱️ Pure Short-Term Swing Horizon: In-Sample Simulation Metrics

TraderAI is an active short-term swing trading engine:
* **Average Holding Period**: **9.6 trading days** (3 to 10 sessions average; 15-day maximum hard stop).
* **10-Session Stagnation Exit**: If a stock stays stagnant between $-2.0\%$ and $+2.0\%$ for 10 sessions, it is automatically exited at market to free up capital.

### In-Sample Historical Monthly Distribution (₹30,000 Portfolio):
* **Historical Average Month**: **+₹420 to +₹600 (+1.4% per month average across 51 months)**.
* **Best Historical Month**: **+₹3,500 to +₹5,210 (+11.9% to +17.4% on ₹30k)** (e.g. Feb 2024 momentum wave).
* **Worst Historical Month**: **-₹1,800 to -₹2,370 (-6.0% to -7.9% on ₹30k)**. Note: Overnight gap-downs through stops and multiple correlated stop-outs can exceed theoretical individual stops.

> [!WARNING]
> **Not Forward Guidance**: Past in-sample performance during bull markets (such as 2023) is not indicative of future results. Real forward deployment remains locked until 50–100 closed trades pass the statistical graduation bar."""

    content = re.sub(
        r"## ⏱️ Pure Short-Term Swing Horizon: What to Expect on ₹30,000.*?(?=## 📰 3-Tier News)",
        lambda m: horizon_section + "\n\n",
        content,
        flags=re.DOTALL
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Successfully updated {path}")

update_technical_doc()
update_readme()
