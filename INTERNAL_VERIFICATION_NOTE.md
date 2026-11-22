# TraderAI Internal Quantitative Verification Note

**Status**: Verified & Reproducible from Code  
**Audit Date**: 2026-11-22  
**Dataset**: 25 Liquid NSE Large/Mid-Cap Stocks (2021–2026), $N = 11,900$ Non-Overlapping Trades  
**Primary Reproducibility Script**: [`analysis/reproduce_prereg_census.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/analysis/reproduce_prereg_census.py)  
**Execution Command**:
```bash
python analysis/reproduce_prereg_census.py
```

---

## 1. Executive Summary

This document serves as the internal audit verification note for all empirical figures, transition matrices, statistical bounds, and variant specifications referenced in [`PRE_REGISTRATION.md`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/PRE_REGISTRATION.md). 

Every metric below is generated directly from deterministic simulation code over the census universe without manual adjustments or recollections.

---

## 2. Trade-Level Subset Verification (Trade-by-Trade Proof)

A core question in the engine reconciliation is whether every trade that stopped out under the superseded engine rules also stopped out under the canonical engine rules.

Trade-by-trade evaluation across all $N = 11,900$ historical trade instances confirms:

1. **Superseded Original Stops ($N = 2,406$) $\subset$ Canonical Stops ($N = 3,769$)**:
   - `df_t[df_t['orig_is_stop']]['canon_is_stop'].all() == True`
   - Every single trade that triggered a close-only stop in the original model also triggered a stop in the canonical model. Under conservative stop-first ordering, if $Close \le Stop$, then $Low \le Close \le Stop$ holds unconditionally on that session.

2. **Superseded Corrected Stops ($N = 2,625$) $\subset$ Canonical Stops ($N = 3,769$)**:
   - `df_t[df_t['corr_is_stop']]['canon_is_stop'].all() == True`
   - Every trade that stopped under open-gap or close-only stops also stopped under the canonical engine.

**Mathematical Hierarchy**:
$$\text{Superseded Original Stops } (2,406) \subset \text{Superseded Corrected Stops } (2,625) \subset \text{Canonical Stops } (3,769)$$

---

## 3. Reconciled Transition Matrices ($N = 11,900$)

### Matrix A: Superseded Original $\to$ Superseded Corrected
*Shows the exact effect of adding broker open-gap fills to close-only exits:*

| Superseded Original $\downarrow$ \ Corrected $\rightarrow$ | MAX_7D_CAP | STOP_LOSS | TARGET | VELOCITY_KILL | **Total Original** |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **MAX_7D_CAP** | 1,530 | 13 | 0 | 0 | **1,543** |
| **STOP_LOSS** | 0 | 2,406 | 0 | 0 | **2,406** |
| **TARGET** | 0 | 12 | 1,219 | 0 | **1,231** |
| **VELOCITY_KILL** | 0 | 194 | 0 | 6,526 | **6,720** |
| **Total Corrected** | **1,530** | **2,625** | **1,219** | **6,526** | **11,900** |

- **194 Velocity Kills $\to$ Stops**: Trades that gapped below $-4.0\%$ at open on Day 1, 2, or 3. Under the original model, they were evaluated at Day 3 close as $< +1.5\%$ (velocity kill). Under corrected rules, they exited at the open on the gap day.
- **13 Caps $\to$ Stops**: Gapped down at open on Days 4–7.
- **12 Targets $\to$ Stops**: Gapped down at open below $-4.0\%$ early, but rebounded to $+12.0\%$ by Day 7. In reality, the broker executed the stop at the open gap, eliminating the rebound.
- **Net Stop Outflow**: $194 + 13 + 12 = 219$ trades added to stops ($2,406 + 219 = \mathbf{2,625}$).

---

### Matrix B: Superseded Corrected $\to$ Canonical
*Shows the exact effect of adding intraday-low continuous monitoring:*

| Superseded Corrected $\downarrow$ \ Canonical $\rightarrow$ | MAX_7D_CAP | STOP_LOSS | TARGET | VELOCITY_KILL | **Total Corrected** |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **MAX_7D_CAP** | 1,486 | 44 | 0 | 0 | **1,530** |
| **STOP_LOSS** | 0 | 2,625 | 0 | 0 | **2,625** |
| **TARGET** | 0 | 44 | 1,175 | 0 | **1,219** |
| **VELOCITY_KILL** | 0 | 1,056 | 0 | 5,470 | **6,526** |
| **Total Canonical** | **1,486** | **3,769** | **1,175** | **5,470** | **11,900** |

- **1,056 Velocity Kills $\to$ Stops**: Positions where intraday $Low \le -4.0\%$ triggered a stop before the Day-3 velocity evaluation.
- **44 Targets $\to$ Stops**: Positions where price dipped to $-4.0\%$ intraday before rallying to $+12.0\%$. Under exchange GTT rules, the stop executed first.
- **44 Caps $\to$ Stops**: Positions that experienced an intraday $-4.0\%$ breach between Days 4 and 7.
- **Net Stop Outflow**: $1,056 + 44 + 44 = 1,144$ trades added to stops ($2,625 + 1,144 = \mathbf{3,769}$).

---

### Matrix C: Superseded Original $\to$ Canonical
*Direct mapping between legacy close-only and frozen canonical engine:*

| Superseded Original $\downarrow$ \ Canonical $\rightarrow$ | MAX_7D_CAP | STOP_LOSS | TARGET | VELOCITY_KILL | **Total Original** |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **MAX_7D_CAP** | 1,486 | 57 | 0 | 0 | **1,543** |
| **STOP_LOSS** | 0 | 2,406 | 0 | 0 | **2,406** |
| **TARGET** | 0 | 56 | 1,175 | 0 | **1,231** |
| **VELOCITY_KILL** | 0 | 1,250 | 0 | 5,470 | **6,720** |
| **Total Canonical** | **1,486** | **3,769** | **1,175** | **5,470** | **11,900** |

- Total trades flowing into canonical stops: $1,250 + 57 + 56 = 1,363$ ($2,406 + 1,363 = \mathbf{3,769}$).

---

### Matrix D: Variant 1 (Canonical Pure Stop) $\to$ Variant 2 (Candidate Ratchet)
*Ablation transition matrix explaining the exact empirical origin of the 770 choked trades:*

| Variant 1 (Pure Stop) $\downarrow$ \ Variant 2 (Ratchet) $\rightarrow$ | MAX_7D_CAP | RATCHET_STOP | STOP_LOSS | TARGET | VELOCITY_KILL | **Total V1** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **MAX_7D_CAP** | 1,216 | 270 | 0 | 0 | 0 | **1,486** |
| **STOP_LOSS** | 0 | 228 | 3,541 | 0 | 0 | **3,769** |
| **TARGET** | 0 | 255 | 0 | 920 | 0 | **1,175** |
| **VELOCITY_KILL** | 0 | 770 | 0 | 0 | 4,700 | **5,470** |
| **Total V2** | **1,216** | **1,523** | **3,541** | **920** | **4,700** | **11,900** |

#### Key Insights:
1. **The 770 Trades**: Exactly **770 trades** that were ordinary Velocity Kills in Variant 1 touched $+5.0\%$ gain intraday before pulling back to the $+0.6\%$ trailing stop, converting into `RATCHET_STOP` exits.
2. **The 255 Choked Target Winners**: Exactly **255 trades** that achieved the full $+12.0\%$ target in Variant 1 had touched $+5.0\%$ early and then suffered a temporary intraday dip below $+0.6\%$, causing Variant 2 to exit prematurely at $+0.6\%$. This surrendered $11.4\%$ of gain per trade, causing a catastrophic $-24.5$ bps drag across the portfolio.
3. **The 228 Saved Stops**: Variant 2 protected 228 trades that touched $+5.0\%$ before reversing into full $-4.0\%$ stop-outs. However, the gain from saving 228 stops ($+4.6\%$ each) was completely swamped by choking 255 full target runners ($-11.4\%$ each) and prematurely exiting 270 cap trades.

---

## 4. Final Canonical Model Census & Formulas ($N = 11,900$)

**Model Name**: `TraderAI Final Canonical Engine: Pure Fixed Floor (-4% Base Stop, Gap-Aware Open Fill, No Ratchet)`

| Metric | Slippage-Adjusted Gross | Statutory Friction (0.303%) | Net Deliverable | Exact Formula |
| :--- | :---: | :---: | :---: | :--- |
| **Portfolio Mean Expectancy** | **$+0.0465\%$** | $-0.3030\%$ | **$-0.2565\%$** | $\frac{1}{N} \sum r_i$ |
| **Win Rate** | **$39.76\%$** (4,731 wins) | — | **$35.83\%$** (4,264 wins) | $\frac{N(r > 0)}{N}$ |
| **Trade-Matched Avg Win** | **$+4.8007\%$** | $-0.3030\%$ | **$+4.4977\%$** | $\frac{1}{N_w} \sum_{r_i > 0} r_i$ |
| **Trade-Matched Avg Loss** | **$-3.0910\%$** | $-0.3030\%$ | **$-3.3940\%$** | $\frac{1}{N_l} \sum_{r_i \le 0} r_i$ |
| **Profit Factor** | **1.025** | — | **0.875** | $\frac{\sum \text{Wins}}{\sum \|\text{Losses}\|}$ |

### Profit Factor Derivation:
- **Gross Profit Factor**:
  $$\text{PF}_{\text{gross}} = \frac{\sum_{r_i > 0} r_i}{\sum_{r_i \le 0} |r_i|} = \frac{22,712.3371}{22,159.0500} = \mathbf{1.024969} \approx \mathbf{1.025}$$
- **Net Profit Factor**:
  $$\text{PF}_{\text{net}} = \frac{\sum_{r_{\text{net}} > 0} r_{\text{net}}}{\sum_{r_{\text{net}} \le 0} |r_{\text{net}}|} = \frac{21,349.0888}{24,401.5018} = \mathbf{0.874909} \approx \mathbf{0.875}$$

---

## 5. Exit Breakdown: Separation of Gapped vs Intraday Stops

To ensure complete transparency regarding the loss distribution, the stop group is partitioned into its two physical execution modes:

| Exit Category | Count | Share (%) | Mean Gross Return | Mean Net Return | Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **72H Velocity Kill** | 5,470 | 45.97% | $-0.652\%$ | $-0.955\%$ | 2,070 positive kills ($+0.65\%$), 3,400 negative kills ($-1.44\%$) |
| **Stop Loss: Intraday Low Fill** | 3,104 | 26.08% | $-4.240\%$ | $-4.543\%$ | Normal $-4.0\%$ stop + $0.25\%$ exit slippage |
| **Stop Loss: Gapped Open Fill** | 665 | 5.59% | **$-6.157\%$** | **$-6.460\%$** | Gapped down at open below $-4.0\%$ floor (17.64% of all stops) |
| **Max 7D Cap (Time Expiry)** | 1,486 | 12.49% | $+5.116\%$ | $+4.813\%$ | Exited at session close on Day 7 |
| **Target Hit (+12% Velocity)** | 1,175 | 9.87% | $+11.720\%$ | $+11.417\%$ | $+12.0\%$ target less $0.25\%$ exit slippage |
| **Total Population** | **11,900** | **100.00%** | **$+0.046\%$** | **$-0.257\%$** | Sum of all exit channels |

- **Combined Stop Loss Average**:
  $$\frac{3,104 \times (-4.240) + 665 \times (-6.157)}{3,769} = \mathbf{-4.578\%} \text{ (Gross)} \implies \mathbf{-4.881\%} \text{ (Net)}$$
- **Total Portfolio Loss Average** ($3,769 \text{ stops} + 3,400 \text{ negative velocity kills} = 7,169 \text{ losses}$):
  $$\frac{3,769 \times (-4.578) + 3,400 \times (-1.442)}{7,169} = \frac{-17,255.37 - 4,902.80}{7,169} = \mathbf{-3.091\%} \text{ (Gross)} \implies \mathbf{-3.394\%} \text{ (Net)}$$

---

## 6. Multiple Testing Search-Space Catalog ($M = 9$)

To provide family-wise error rate (FWER) control at $\alpha = 0.05$, the Bonferroni count is fixed at $M = 9$, corresponding to:
$$\alpha_{\text{Bonf}} = \frac{0.05}{9} \approx 0.005556 \implies \mathbf{99.444\% \text{ One-Sided Confidence Gate (0.556\% Tail)}}$$

Every configuration is defined by its exact `(entry_rule, exit_rule, sizing, universe)` tuple from the project's historical experiment records:

### Tournament Configurations ($M_1 = 6$):
1. **Track A Legacy**: `(09:20 Open Confirmation, +20% / -7% EOD Close, 3-Slot ₹33k Tier, 25 Liquid NSE)`
2. **Track B Legacy**: `(Consolidation GTT Buy-Stop, +25% / -6% EOD Close, 3-Slot ₹33k Tier, 25 Liquid NSE)`
3. **Track C Legacy**: `(Intraday Velocity Sniper, +15% / -5% EOD Close, 3-Slot ₹33k Tier, 25 Liquid NSE)`
4. **Track A Canonical**: `(09:20 Open Confirmation, +12% / -4% Intraday GTT + Gap Open + 72h Kill, 5-Slot ₹20k Fixed, 25 Liquid NSE)`
5. **Track B Canonical**: `(Consolidation GTT Buy-Stop, +12% / -4% Intraday GTT + Gap Open + 72h Kill, 5-Slot ₹20k Fixed, 25 Liquid NSE)`
6. **Track C Canonical**: `(Intraday Velocity Sniper, +12% / -4% Intraday GTT + Gap Open + 72h Kill, 5-Slot ₹20k Fixed, 25 Liquid NSE)`

### Historical Exploratory In-Sample Runs ($M_2 = 3$):
7. **Exploratory Run 1 (20 EMA Pullback Swing)**: `(20 EMA Touch in Trend, +10% / -5% / 20D Hold, 5-Slot ₹20k, 136-Stock Universe)`
8. **Exploratory Run 2 (Fast Volume Surge Breakout)**: `(2.0x Vol + 50D High Breakout, +15% / -5% / 10D Hold, 3-Slot ₹10k, 136-Stock Universe)`
9. **Exploratory Run 3 (Freeroll Half-Exit Runner)**: `(20D Breakout, +6% Half-Exit + 20 EMA Trail / -4% Initial, 5-Slot ₹20k, 25 Liquid NSE)`

---

## 7. Ratchet Ablation Block Bootstrap Verification

- **Resampling Method**: Non-parametric Block Bootstrap by Calendar Week ($W = 249$ clusters)
- **Iterations**: $B = 20,000$ draws
- **Random Seed**: `20261122`
- **Mean Net Difference (Variant 2 $-$ Variant 1)**: **$-0.2484\%$**
- **95% Two-Sided Confidence Interval**: $[-0.2993\%,\; -0.1996\%]$
- **One-Sided 99.444% Lower Bound (0.556% tail, ~111 draws)**: **$-0.3145\%$** ($\approx \mathbf{-0.315\%}$)
- **Ablation Gate**: Lower Bound $\le 0.00\%$ $\implies$ **FAIL**. The ratchet is permanently excluded.

---

## 8. Source File and Metric Reproducibility Map

| Metric / Table | Source Code Location | Reproducing Command |
| :--- | :--- | :--- |
| **Census Returns & Win Rates** | [`analysis/reproduce_prereg_census.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/analysis/reproduce_prereg_census.py)#L155-L185 | `python analysis/reproduce_prereg_census.py` |
| **Transition Matrices A, B, C, D** | [`analysis/reproduce_prereg_census.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/analysis/reproduce_prereg_census.py)#L120-L150 | `python analysis/reproduce_prereg_census.py` |
| **Trade Subset Proof** | [`analysis/reproduce_prereg_census.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/analysis/reproduce_prereg_census.py)#L105-L115 | `python analysis/reproduce_prereg_census.py` |
| **Block Bootstrap Ablation** | [`analysis/reproduce_prereg_census.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/analysis/reproduce_prereg_census.py)#L205-L235 | `python analysis/reproduce_prereg_census.py` |
| **Statutory Indian Friction (0.303%)** | [`data/costs.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/data/costs.py)#L35-L95 | `pytest tests/test_invariants.py -k test_friction_golden_values_exact_paisa` |
| **Stop-First Bar Execution** | [`engine/dual_tracker.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/engine/dual_tracker.py)#L515-L530 | `pytest tests/test_invariants.py -k test_intrabar_exit_ordering_stop_first_conservative` |
| **5-Slot ₹20k Capital Mutex** | [`engine/dual_tracker.py`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/engine/dual_tracker.py)#L44-L56 | `pytest tests/test_dual_tracker.py -k test_max_slots_and_capital_enforcement_prevents_leverage` |
| **Full Invariants Test Suite (40/40)** | [`tests/`](file:///c:/Users/Varun%20Gani/Downloads/trader-ai/tests/) | `pytest tests/ -v` |
