"""
Crypto Alpha Dashboard Component for TraderAI.
Renders real-time Bitcoin Macro Regime, live momentum breakouts,
Indian tax/TDS simulation, and 5-year empirical backtest metrics.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
from engine.crypto_engine import (
    fetch_crypto_realtime_data,
    analyze_crypto_market,
    get_crypto_backtest_stats,
    USD_TO_INR_APPROX,
)

def render_crypto_section():
    st.markdown("## 🪙 Crypto Alpha — Satellite Convexity Bucket")
    st.caption(
        "Isolated High-Convexity Capital: **₹3,000 Initial** (scaling to **₹6,000 in Feb**) • 2 Position Slots • Spot Only (Zero Leverage) • 100% Segregated from Core NSE Demat Portfolio"
    )

    st.markdown("""
> [!IMPORTANT]
> **The Barbell Architecture:** This crypto section is a completely isolated satellite bucket. Your main ₹30,000 capital and monthly savings remain in institutional NSE Cash Equities. In crypto, you only deploy ₹3,000, risking a maximum of **₹90 per trade** (-6% stop on a ₹1,500 slot).
""")

    # Interactive Controls
    c_ctrl1, c_ctrl2, c_ctrl3, c_ctrl4 = st.columns([2, 2, 2, 2])
    with c_ctrl1:
        crypto_cap = st.selectbox(
            "Crypto Dedicated Capital",
            options=[3000.0, 6000.0, 10000.0],
            format_func=lambda x: f"₹{x:,.0f} ({'Current Seed' if x == 3000 else 'Feb Plan' if x == 6000 else 'Custom'})",
            index=0,
            help="Strictly isolated capital. Will never touch your main NSE equity funds."
        )
    with c_ctrl2:
        max_slots = st.selectbox(
            "Position Slots",
            options=[2, 1],
            format_func=lambda x: f"{x} Slots (₹{crypto_cap/x:,.0f} each)",
            index=0,
            help="2 slots cut portfolio volatility by 50% compared to all-in 1 slot."
        )
    with c_ctrl3:
        style_mode = st.selectbox(
            "Horizon & Trading Style",
            options=["⚡ Fast Momentum (3–7 Days)", "🌊 Trend Compounding (7–15 Days)"],
            index=0,
            help="Fast Momentum: 10D breakout, -5% stop, +12% target, 5 EMA trail. Trend Compounding: 20D breakout, -6% stop, +18% target, 10 EMA trail."
        )
    with c_ctrl4:
        refresh_btn = st.button("🔄 Refresh Live Data", use_container_width=True)

    is_fast_mode = "Fast" in style_mode

    with st.spinner("Fetching live 24/7 crypto market data and calculating Mansfield RS vs BTC..."):
        data = fetch_crypto_realtime_data()
        analysis = analyze_crypto_market(data)

    if analysis.get("status") != "OK":
        st.error(analysis.get("message", "Error analyzing crypto market."))
        return

    btc = analysis["btc_macro"]

    # 1. BITCOIN MACRO REGIME BANNER
    st.markdown("### 1. Bitcoin Macro Regime Gate")
    b_col1, b_col2, b_col3, b_col4 = st.columns(4)
    b_col1.metric("BTC Price (USD)", f"${btc['price_usd']:,.0f}")
    b_col1.caption(f"≈ ₹{btc['price_inr']:,.0f}")
    b_col2.metric("BTC 50 EMA", f"${btc['ema50']:,.0f}")
    b_col3.metric("BTC 20 EMA", f"${btc['ema20']:,.0f}")
    
    if btc["regime"] == "BULLISH_EXPANSION":
        b_col4.metric("Macro Gate", "🟢 GREEN LIGHT", delta="Bull Trend Active")
        st.success(f"**{btc['regime']}:** {btc['verdict']}")
    elif btc["regime"] == "CONSOLIDATION_CHOP":
        b_col4.metric("Macro Gate", "🟡 YELLOW LIGHT", delta="Caution / Chop")
        st.warning(f"**{btc['regime']}:** {btc['verdict']}")
    else:
        b_col4.metric("Macro Gate", "🔴 100% CASH LOCK", delta="Bear Downtrend", delta_color="inverse")
        st.error(f"**{btc['regime']}:** {btc['verdict']}")

    # 2. LIVE CANDIDATES & BREAKOUT SCANNER
    st.markdown("### 2. Live Top-12 Liquid Crypto Scanner (CoinDCX / CoinSwitch Traded)")
    if is_fast_mode:
        st.info("⚡ **Fast Momentum Mode Active:** Optimized for quick 3–7 day velocity bursts. Triggers on 10-day breakouts with RVOL ≥ 1.3x, -5.0% hard stop, +12.0% target, and dynamic daily 5 EMA trailing exit.")
    else:
        st.info("🌊 **Trend Compounding Mode Active:** Optimized for multi-week 7–15 day monster trends. Triggers on 20-day Donchian breakouts, -6.0% hard stop, +18.0% partial profit target, and daily 10 EMA trailing runner.")

    candidates = analysis.get("candidates", [])
    
    table_rows = []
    for c in candidates:
        if is_fast_mode:
            table_rows.append({
                "Asset": f"{c['name']} ({c['symbol'].replace('-USD', '')})",
                "Category": c["type"],
                "Price (USD)": f"${c['price_usd']:,.2f}" if c['price_usd'] >= 1 else f"${c['price_usd']:.4f}",
                "Price (INR)": f"₹{c['price_inr']:,.1f}" if c['price_inr'] >= 10 else f"₹{c['price_inr']:.3f}",
                "24h %": f"{c['change_24h']:+.2f}%",
                "Action": c["action"],
                "Score": c["score"],
                "RS vs BTC": f"{c['mansfield_rs']:+.1f}%",
                "RVOL": f"{c['rvol']:.2f}x",
                "10D Breakout": "YES ⚡" if c.get("is_fast_breakout") else "No",
                "Fast Stop (-5%)": f"${c.get('fast_stop_usd', 0):,.2f}" if c.get('fast_stop_usd', 0) >= 1 else f"${c.get('fast_stop_usd', 0):.4f}",
                "Fast Target (+12%)": f"${c.get('fast_target_usd', 0):,.2f}" if c.get('fast_target_usd', 0) >= 1 else f"${c.get('fast_target_usd', 0):.4f}",
                "Trail 5 EMA": f"${c.get('trailing_5ema_usd', 0):,.2f}" if c.get('trailing_5ema_usd', 0) >= 1 else f"${c.get('trailing_5ema_usd', 0):.4f}"
            })
        else:
            table_rows.append({
                "Asset": f"{c['name']} ({c['symbol'].replace('-USD', '')})",
                "Category": c["type"],
                "Price (USD)": f"${c['price_usd']:,.2f}" if c['price_usd'] >= 1 else f"${c['price_usd']:.4f}",
                "Price (INR)": f"₹{c['price_inr']:,.1f}" if c['price_inr'] >= 10 else f"₹{c['price_inr']:.3f}",
                "24h %": f"{c['change_24h']:+.2f}%",
                "Action": c["action"],
                "Score": c["score"],
                "RS vs BTC": f"{c['mansfield_rs']:+.1f}%",
                "RVOL": f"{c['rvol']:.2f}x",
                "20D Breakout": "YES 🚀" if c["is_breakout"] else "No",
                "Stop Loss (-6%)": f"${c['stop_loss_usd']:,.2f}" if c['stop_loss_usd'] >= 1 else f"${c['stop_loss_usd']:.4f}",
                "Target 1 (+18%)": f"${c['target1_usd']:,.2f}" if c['target1_usd'] >= 1 else f"${c['target1_usd']:.4f}",
                "Trail 10 EMA": f"${c['trailing_10ema_usd']:,.2f}" if c['trailing_10ema_usd'] >= 1 else f"${c['trailing_10ema_usd']:.4f}"
            })
    
    cand_df = pd.DataFrame(table_rows)
    st.dataframe(cand_df, use_container_width=True, hide_index=True)

    # 3. POSITION SIZING & INDIAN TAX BREAKDOWN
    st.markdown("### 3. Position Sizing & Indian Tax Simulator")
    slot_amount = crypto_cap / max_slots
    stop_risk_pct = 0.05 if is_fast_mode else 0.06
    max_risk_amount = slot_amount * stop_risk_pct

    p1, p2, p3 = st.columns(3)
    p1.metric("Dedicated Capital", f"₹{crypto_cap:,.0f}")
    p2.metric(f"Allocation Per Slot ({max_slots} slots)", f"₹{slot_amount:,.0f}")
    p3.metric(f"Max Risk Per Trade (-{int(stop_risk_pct*100)}% Stop)", f"₹{max_risk_amount:,.1f}", help=f"If the trade hits stop loss, you lose only ₹{max_risk_amount:,.0f}!")

    with st.expander("🧾 Exact Indian Crypto Statutory Tax Breakdown (Sec 115BBH & 194S)", expanded=False):
        st.markdown(f"""
Suppose you take a trade on a breakout candidate with **1 slot of ₹{slot_amount:,.0f}**:
- **Entry Costs:**
  * Capital Deployed: ₹{slot_amount:,.0f}
  * Exchange Taker Fee (0.20%): ₹{slot_amount * 0.002:,.2f}
  * Slippage (0.10%): ₹{slot_amount * 0.001:,.2f}
  * Net Asset Value Bought: ₹{slot_amount * 0.997:,.2f}

- **Scenario A: Winner (+25% Move)**
  * Gross Exit Value: ₹{slot_amount * 1.25:,.2f}
  * Indian Section 194S TDS (1.0% on Sell Value): **-₹{slot_amount * 1.25 * 0.01:,.2f}** (credited to your Form 26AS)
  * Exchange Exit Fee (0.20%): -₹{slot_amount * 1.25 * 0.002:,.2f}
  * Slippage (0.10%): -₹{slot_amount * 1.25 * 0.001:,.2f}
  * **Net In-Pocket Rupee Profit:** **+₹{(slot_amount * 1.25 * 0.987) - slot_amount:,.2f} (+{(((slot_amount * 1.25 * 0.987) - slot_amount)/slot_amount)*100:.1f}% Net)**

- **Scenario B: Stop Loss Cut (-6% Move)**
  * Gross Exit Value: ₹{slot_amount * 0.94:,.2f}
  * Net Loss Including All Fees & TDS: **-₹{slot_amount - (slot_amount * 0.94 * 0.987):,.2f}** (~₹{max_risk_amount:,.0f})
""")

    # 4. 5-YEAR EMPIRICAL BACKTEST RESULTS
    st.markdown("### 4. 5-Year Empirical Backtest Results (2021–2026)")
    st.caption("Includes the 2021 Peak, the brutal 2022 Crypto Winter (-75% crash), 2023 Accumulation, and the 2024-2026 ETF Bull Waves.")

    stats = get_crypto_backtest_stats()
    
    col_strat, col_bh = st.columns([3, 2])
    with col_strat:
        st.markdown("#### 🎯 TraderAI Algorithmic Strategies (Rs 3,000 Seed)")
        strat_rows = []
        for s in stats["strategies"]:
            strat_rows.append({
                "Strategy": s["name"],
                "Final Equity": f"₹{s['final_equity']:,.2f}",
                "Net Return": f"{s['net_return_pct']:+.1f}%",
                "Profit Factor": f"{s['profit_factor']:.2f}",
                "Win Rate": f"{s['win_rate']:.1f}%",
                "Max Drawdown": f"{s['max_drawdown']:.1f}%",
                "Verdict": s["verdict"]
            })
        st.dataframe(pd.DataFrame(strat_rows), use_container_width=True, hide_index=True)

    with col_bh:
        st.markdown("#### 📉 Buy & Hold Benchmarks (Rs 3,000 on Oct 2021)")
        bh_rows = []
        for b in stats["benchmarks"]:
            bh_rows.append({
                "Asset": b["asset"],
                "Final Value": f"₹{b['final']:,.2f}",
                "Net Return": f"{b['ret']:+.1f}%",
                "Max Drawdown": f"{b['max_dd']:.1f}%"
            })
        st.dataframe(pd.DataFrame(bh_rows), use_container_width=True, hide_index=True)

    st.info("""
💡 **Why the Algorithm Crushed Buy-and-Hold:**
1. If you held **Solana (SOL)**, your ₹3,000 crashed by **-96.3%** down to ₹110 during the FTX collapse before recovering. Most retail traders panick-sold at the exact bottom.
2. If you held **Ethereum (ETH)**, your ₹3,000 lost **-43.2%** with a **-79.4% drawdown**.
3. **TraderAI with the Bitcoin Macro Gate** sat in **100% Cash** during the entire 2022 bear market, avoiding the crash, and multiplied ₹3,000 into **₹7,598.88 (+153.3% Net)** by taking high-volume Stage 2 breakouts!
""")

    # 5. PLATFORM EXECUTION GUIDE
    st.markdown("### 5. Recommended Execution Platforms in India")
    e1, e2 = st.columns(2)
    with e1:
        st.success("""
**✅ CoinDCX (Recommended for Safety)**
- Fully FIU-IND registered with Indian Ministry of Finance
- Direct INR deposit & withdrawal via IMPS / UPI
- Automatically deducts 1% Section 194S TDS and provides Form 16A
- Spot trading with zero margin risk
""")
    with e2:
        st.info("""
**✅ CoinSwitch PRO (Recommended for Advanced Charts)**
- FIU-IND registered with direct INR bank transfers
- Advanced TradingView charts & lower maker/taker fees (0.1%)
- Multi-exchange aggregated liquidity
- ⚠️ *Reminder:* Always avoid unverified Binance P2P sellers to prevent bank account freeze issues.
""")
