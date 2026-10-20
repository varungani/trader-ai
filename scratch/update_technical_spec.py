import os

filepath = r"c:\Users\Varun Gani\Downloads\trader-ai\TRADER_AI_ARCHITECTURE_AND_TECHNICALS.md"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target_marker = "### 14.4 Comprehensive Ablation Matrix (Choked vs. Unshackled Exits)"
end_marker = "## 15. Regulatory & Legal Disclaimer"

start_idx = content.find(target_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print(f"Error: Markers not found! start_idx={start_idx}, end_idx={end_idx}")
    exit(1)

new_section_14 = """### 14.4 Comprehensive Ablation Matrix (Choked vs. Unshackled Exits)

To prove what was doing the work, we simulated all variants under both the old choked exit policy and the new unshackled exit policy across the full 3-year historical period:

| Experiment Variant | Trades | Win Rate | $T_1$ Hits | Gross P&L | Total Friction | Net Return | Alpha vs NIFTY | Profit Factor | Expectancy | Max Drawdown | Sharpe |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **NIFTYBEES Buy & Hold (Benchmark)** | — | — | — | — | — | **+21.1%** | *Benchmark* | — | — | -13.2% | +1.18 |
| **Old Choked Strategy (Score $\ge 65$)** | 265 | 50.2% | **3** | -₹10,517 | ₹18,586 | **-29.1%** | -50.2% | 0.68 | -₹109.82 | -38.1% | -0.93 |
| **Strategy (Score $\ge 65$, Unshackled Exits)** | 210 | 48.6% | **13** | +₹106,214 | ₹24,475 | **+81.7%** | +60.6% | 1.58 | +₹389.23 | -25.4% | +1.23 |
| **Strategy (Score $\ge 75$, Unshackled Exits)** | 186 | 49.5% | **13** | +₹99,697 | ₹20,865 | **+78.8%** | +57.7% | 1.68 | +₹423.83 | -19.8% | +1.29 |
| **Simple Baseline (50 SMA + Vol + Unshackled)** | 189 | 47.1% | **17** | +₹189,286 | ₹27,840 | **+161.4%** | +140.3% | 2.01 | +₹854.21 | **-12.5%** | **+1.91** |
| **Zero-Skill Control (Random + Unshackled)** | 113 | 54.0% | **13** | +₹157,125 | ₹14,813 | **+142.3%** | +121.2% | 2.68 | +₹1,259.40 | **-9.2%** | **+2.13** |

#### Critical Empirical Findings:
1. **Exits Dominate Returns**: Removing the premature breakeven choke transformed the strategy from a **-29.1% loss** into an **+81.7% net return**, increasing $T_1$ target hits from 3 to 13.
2. **Simple Baseline & Random Selection Outperform**: The Simple Baseline (50-day SMA + volume breakout) (+161.4%) and Zero-Skill random entries (+142.3%) both beat the complex 5-factor scoring model (+81.7%). The complex model adds churn without adding edge over a simple trend-following rule.
3. **Turnover Reduction Protects Capital**: Raising the score threshold to $\ge 75$ reduced trade churn by 24 trades and cut maximum drawdown from -25.4% to -19.8%.

---

### 14.5 Active Feature Freeze & Mandatory Graduation Bar Protocol

**Ironclad Rule**: Never increase position sizes, risk caps, or trade real capital to chase profits until a verifiable edge is proven. Increasing risk on an unproven strategy only accelerates ruin.

#### Active Feature Freeze:
* All development on LLM prompts, news scrapers, and UI components is **strictly frozen**.
* 100% of research is restricted to signal calibration, turnover control, and exit geometry.

```mermaid
graph TD
    A[Paper Trading in Streamlit Cockpit] --> B[Accumulate 50-100 Closed Paper Trades]
    B --> C{Audit Mathematical Edge}
    C -->|Net Expectancy E > 0\\nAlpha vs NIFTY > 0\\nMax DD < 15%| D[Graduation Passed: Deploy Micro Capital ₹10k]
    C -->|Negative Expectancy or Underperforming NIFTY| E[Locked: Simplify Architecture & Refine Entry Filters]
```

1. **Closed Sample Requirement**: Minimum **50 to 100 closed forward trades** logged in the SQLite ledger across distinct market regimes (typically 3–6 months with 5 open positions).
2. **Positive Net Expectancy ($E > 0$)**:
   $$E = (P_{\\text{win}} \\times \\overline{W}_{\\text{net}}) - (P_{\\text{loss}} \\times \\overline{L}_{\\text{net}}) > 0$$
   Must be strictly positive after deducting all DP charges (₹15.93 flat), STT, and slippage.
3. **Positive Alpha ($\alpha > 0$)**: The strategy return must exceed `NIFTYBEES.NS` buy-and-hold over the exact forward evaluation window.
4. **Max Drawdown Gate**: Paper portfolio peak-to-trough drawdown must remain **under 15.0%**.
5. **Frozen Risk Caps**: The 20% position cap, 2% risk per trade, and 5-position limit are **strictly immutable**. Zero margin (MIS), zero F&O.

---

"""

updated_content = content[:start_idx] + new_section_14 + content[end_idx:]

with open(filepath, "w", encoding="utf-8") as f:
    f.write(updated_content)

print("Successfully updated TRADER_AI_ARCHITECTURE_AND_TECHNICALS.md")
