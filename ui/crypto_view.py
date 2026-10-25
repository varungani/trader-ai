"""
Crypto Alpha Dashboard Component for TraderAI.
Renders real-time Bitcoin Macro Regime Gate, 4-Pillar Quant Scorecard (0-100),
Institutional Verdicts (BUY / HOLD / SELL / AVOID), Live Shadow Tracking Ledger,
and 1% Indian TDS / Statutory Fee Modeling.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
from engine.crypto_engine import (
    fetch_crypto_realtime_data,
    analyze_crypto_market,
    sync_crypto_paper_trades,
    execute_crypto_shadow_buy,
    manual_close_crypto_paper_trade,
    get_crypto_backtest_stats,
    USD_TO_INR_APPROX,
)

def render_crypto_section():
    st.markdown("## 🪙 Crypto Alpha — Quantitative Satellite & Shadow Engine")
    st.caption(
        "Isolated High-Convexity Capital: **₹3,000 Initial** (scaling to **₹6,000 in Feb**) • 2 Position Slots • Spot Only (Zero Leverage) • 100% Segregated from Core NSE Demat Portfolio"
    )

    st.markdown("""
> [!IMPORTANT]
> **The Barbell Architecture:** This crypto section is a completely isolated satellite bucket. Your main ₹30,000 capital and monthly savings remain in institutional NSE Cash Equities. In crypto, you only deploy ₹3,000, risking a maximum of **₹98 per trade** (-6.5% hard stop on a ₹1,500 slot).
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
            options=[
                "🚀 Parabolic Moonshot Runner (7–30 Days / High-Beta Focus)",
                "🌊 Multi-Week Swing Runner (7–28 Days / 4 Wk Max)",
                "⚡ Quick Momentum Burst (3–7 Days)"
            ],
            index=0,
            help="Parabolic Moonshot Runner: Focuses on explosive high-beta altcoins (SOL, AVAX, NEAR, DOGE, LINK) outperforming BTC. Aims for +50% to +150%+ runners with -6.5% stop!"
        )
    with c_ctrl4:
        refresh_btn = st.button("🔄 Refresh Live Data & Sync", use_container_width=True)

    is_moonshot = "Moonshot" in style_mode
    is_fast_mode = "Quick" in style_mode

    with st.spinner("Fetching live 24/7 crypto market data, computing 4-Pillar Quant Scores and syncing paper ledger..."):
        data = fetch_crypto_realtime_data()
        analysis = analyze_crypto_market(data)
        paper_ledger = sync_crypto_paper_trades(data)

    if analysis.get("status") != "OK":
        st.error(analysis.get("message", "Error analyzing crypto market."))
        return

    btc = analysis["btc_macro"]

    # 1. BITCOIN MACRO REGIME BANNER
    st.markdown("### 1. Bitcoin Macro Regime Gate")
    b_col1, b_col2, b_col3, b_col4 = st.columns(4)
    b_col1.metric("BTC Price (USD)", f"${btc['price_usd']:,.0f}", help="Live Bitcoin price")
    b_col1.caption(f"≈ ₹{btc['price_inr']:,.0f}")
    b_col2.metric("BTC 50 EMA", f"${btc['ema50']:,.0f}", help="Macro trend divider: Price above 50 EMA is required for risk-on buys")
    b_col3.metric("BTC 20 EMA", f"${btc['ema20']:,.0f}", help="Short-term trend momentum")
    
    if btc["regime"] == "BULLISH_EXPANSION":
        b_col4.metric("Macro Gate", "🟢 GREEN LIGHT", delta="Bull Trend Active")
        st.success(f"**{btc['regime']}:** {btc['verdict']}")
    elif btc["regime"] == "CONSOLIDATION_CHOP":
        b_col4.metric("Macro Gate", "🟡 YELLOW LIGHT", delta="Caution / Chop")
        st.warning(f"**{btc['regime']}:** {btc['verdict']}")
    else:
        b_col4.metric("Macro Gate", "🔴 100% CASH LOCK", delta="Bear Downtrend", delta_color="inverse")
        st.error(f"**{btc['regime']}:** {btc['verdict']}")

    # Auto-exit notifications
    if paper_ledger.get("auto_exits"):
        for ax in paper_ledger["auto_exits"]:
            st.warning(f"🔔 **Automated Paper Trade Exit Triggered:** {ax['symbol']} exited via **{ax['reason']}** | Realized Net P&L: **₹{ax['pnl_inr']:+,.2f} ({ax['pnl_pct']:+.1f}%)**")

    # 2. ACTIVE SHADOW / PAPER TRADING PORTFOLIO LEDGER
    st.markdown("### 2. Live Crypto Paper Trading Portfolio (Shadow Ledger)")
    st.caption("Real-time forward simulation with 100% statutory Indian friction (1% TDS + 0.20% exchange fee) deducted.")

    open_pos = paper_ledger.get("open_positions", [])
    closed_pos = paper_ledger.get("closed_trades", [])
    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Open Paper Slots", f"{len(open_pos)} / {max_slots}", help="Number of currently active simulated crypto positions")
    m2.metric("Deployed Capital", f"₹{paper_ledger.get('total_allocated', 0):,.0f}", help="Virtual cash allocated to open paper trades")
    
    float_pnl = paper_ledger.get("floating_pnl_inr", 0.0)
    alloc = paper_ledger.get("total_allocated", 1.0) or 1.0
    float_pct = (float_pnl / alloc) * 100.0 if open_pos else 0.0
    m3.metric("Floating Unrealized P&L", f"₹{float_pnl:+,.1f}", delta=f"{float_pct:+.2f}%")
    
    real_pnl = paper_ledger.get("realized_pnl_inr", 0.0)
    m4.metric("Closed Realized P&L", f"₹{real_pnl:+,.1f}", delta="Net of 1% TDS" if real_pnl != 0 else None)
    m5.metric("Paper Win Rate", f"{paper_ledger.get('win_rate', 0):.1f}%", help=f"Across {paper_ledger.get('total_closed_count', 0)} closed simulated trades")

    if open_pos:
        pos_rows = []
        for p in open_pos:
            pos_rows.append({
                "Trade ID": p["id"],
                "Token": p["symbol"].replace("-USD", ""),
                "Entry Date": p["entry_date"],
                "Entry (USD)": f"${p['entry_price_usd']:,.2f}" if p['entry_price_usd'] >= 1 else f"${p['entry_price_usd']:.4f}",
                "Live (USD)": f"${p.get('current_price_usd', 0):,.2f}" if p.get('current_price_usd', 0) >= 1 else f"${p.get('current_price_usd', 0):.4f}",
                "Tokens": f"{p['quantity_tokens']:.4f}",
                "Allocated (INR)": f"₹{p['allocated_inr']:,.0f}",
                "Unrealized P&L (INR)": f"₹{p.get('unrealized_pnl_inr', 0):+,.1f}",
                "Net Return %": f"{p.get('unrealized_pnl_pct', 0):+.2f}%",
                "Stop-Loss (USD)": f"${p['stop_loss_usd']:,.2f}" if p['stop_loss_usd'] >= 1 else f"${p['stop_loss_usd']:.4f}",
                "Stop Cushion": f"{p.get('dist_to_stop_pct', 0):.1f}%",
                "Trail Level (USD)": f"${p.get('trailing_ema_usd', 0):,.2f}" if p.get('trailing_ema_usd', 0) >= 1 else f"${p.get('trailing_ema_usd', 0):.4f}",
            })
        st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)

        # Manual Exit Controls
        with st.expander("⚙️ Manual Paper Position Management", expanded=False):
            col_sel, col_act = st.columns([3, 1])
            with col_sel:
                selected_trade_id = st.selectbox(
                    "Select Open Paper Trade to Close Manually",
                    options=[p["id"] for p in open_pos],
                    format_func=lambda x: next(f"ID #{x}: {p['symbol']} (P&L: ₹{p.get('unrealized_pnl_inr', 0):+,.1f})" for p in open_pos if p["id"] == x)
                )
            with col_act:
                if st.button("❌ Close Paper Trade Now", use_container_width=True):
                    target_trade = next(p for p in open_pos if p["id"] == selected_trade_id)
                    res = manual_close_crypto_paper_trade(selected_trade_id, target_trade.get("current_price_usd", target_trade["entry_price_usd"]))
                    if res.get("ok"):
                        st.success(f"Closed trade #{selected_trade_id} at market. Realized P&L: ₹{res['pnl_inr']:+,.2f}")
                        st.rerun()
    else:
        st.info("ℹ️ **No active open paper trades.** Select a BUY candidate below and click **'⚡ Execute Shadow Buy'** to test the strategy in live market conditions.")

    # 3. LIVE 4-PILLAR QUANT SCORECARD & BREAKOUT SCANNER
    st.markdown("### 3. Live Institutional Quant Scorecard (0–100) & Signals")
    if is_moonshot:
        st.success("🚀 **Parabolic Moonshot Mode:** High-beta altcoins outperforming BTC. Score $\ge 78$ triggers `BUY 🟢` with uncapped trailing runner!")
    elif is_fast_mode:
        st.info("⚡ **Quick Momentum Burst:** Fast 3–7 day velocity bursts. Triggers on 10-day breakouts with RVOL ≥ 1.3x and 5 EMA trail.")
    else:
        st.success("🌊 **Multi-Week Swing Runner (7–28 Days):** Highest-compounding institutional crypto strategy (+154.1% Net Return).")

    candidates = analysis.get("candidates", [])
    
    table_rows = []
    for c in candidates:
        table_rows.append({
            "Asset": f"{c['name']} ({c['symbol'].replace('-USD', '')})",
            "Price (USD)": f"${c['price_usd']:,.2f}" if c['price_usd'] >= 1 else f"${c['price_usd']:.4f}",
            "Price (INR)": f"₹{c['price_inr']:,.1f}" if c['price_inr'] >= 10 else f"₹{c['price_inr']:.3f}",
            "24h %": f"{c['change_24h']:+.2f}%",
            "Quant Score": f"{c['score']:.1f} / 100",
            "Verdict": c["verdict"],
            "Action Thesis": c["action"],
            "RS vs BTC": f"{c['mansfield_rs']:+.1f}%",
            "RVOL": f"{c['rvol']:.2f}x",
            "Breakout (20D)": "YES 🚀" if c["is_breakout"] else "No",
            "Hard Stop (-6.5%)": f"${c['stop_loss_usd']:,.2f}" if c['stop_loss_usd'] >= 1 else f"${c['stop_loss_usd']:.4f}",
            "Scale-Out (+25%)": f"${c['target1_usd']:,.2f}" if c['target1_usd'] >= 1 else f"${c['target1_usd']:.4f}",
            "Trail (10 EMA)": f"${c['trailing_10ema_usd']:,.2f}" if c['trailing_10ema_usd'] >= 1 else f"${c['trailing_10ema_usd']:.4f}",
        })
    
    cand_df = pd.DataFrame(table_rows)
    st.dataframe(cand_df, use_container_width=True, hide_index=True)

    # 4. ONE-CLICK SHADOW BUY EXECUTION PANEL
    st.markdown("### 4. Shadow Trade Execution Panel")
    slot_amount = crypto_cap / max_slots
    free_slots = max_slots - len(open_pos)

    buy_candidates = [c for c in candidates if "BUY" in c["verdict"]]
    
    if free_slots <= 0:
        st.warning(f"⚠️ All {max_slots} paper slots are currently occupied. To open a new paper trade, wait for an active position to hit its stop/target, or close one manually above.")
    elif not btc["entries_allowed"]:
        st.error("🛑 **Bitcoin Macro Gate is RED.** New simulated entries are blocked by risk policy to protect capital.")
    else:
        st.success(f"✅ **{free_slots} Slot(s) Available for Shadow Trading.** Dedicated allocation: **₹{slot_amount:,.0f} per slot**.")
        
        col_cand, col_btn = st.columns([3, 1])
        with col_cand:
            options_pool = buy_candidates if buy_candidates else candidates
            selected_sym = st.selectbox(
                "Select Candidate to Shadow Buy",
                options=[c["symbol"] for c in options_pool],
                format_func=lambda s: next(f"{c['name']} ({s.replace('-USD', '')}) — Score: {c['score']} [{c['verdict']}]" for c in options_pool if c["symbol"] == s)
            )
        with col_btn:
            st.write("")
            st.write("")
            if st.button("⚡ Execute Shadow Buy", type="primary", use_container_width=True):
                cand = next(c for c in options_pool if c["symbol"] == selected_sym)
                res = execute_crypto_shadow_buy(selected_sym, cand, allocated_inr=slot_amount, strategy_mode=style_mode)
                if res.get("ok"):
                    st.success(f"🚀 Shadow Trade Logged! Bought {res['qty']} {selected_sym} at ${cand['price_usd']:,.2f} (₹{cand['price_inr']:,.1f}).")
                    st.rerun()
                else:
                    st.error(res.get("error", "Failed to execute shadow buy."))

    # 5. CLOSED PAPER TRADING AUDIT LEDGER
    if closed_pos:
        st.markdown("### 5. Closed Paper Trades Audit History")
        hist_rows = []
        for cp in closed_pos:
            hist_rows.append({
                "ID": cp["id"],
                "Token": cp["symbol"].replace("-USD", ""),
                "Entry Date": cp["entry_date"],
                "Exit Date": cp.get("exit_date", "—"),
                "Entry ($)": f"${cp['entry_price_usd']:,.2f}" if cp['entry_price_usd'] >= 1 else f"${cp['entry_price_usd']:.4f}",
                "Exit ($)": f"${cp.get('exit_price_usd', 0):,.2f}" if cp.get('exit_price_usd', 0) >= 1 else f"${cp.get('exit_price_usd', 0):.4f}",
                "Allocated (₹)": f"₹{cp['allocated_inr']:,.0f}",
                "Net P&L (₹)": f"₹{cp.get('pnl_inr', 0):+,.2f}",
                "Net Return %": f"{cp.get('pnl_pct', 0):+.2f}%",
                "TDS Paid (₹)": f"₹{cp.get('tds_inr', 0):,.2f}",
                "Exit Reason": cp.get("exit_reason", "MANUAL"),
            })
        st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)

    # 6. POSITION SIZING & INDIAN TAX BREAKDOWN
    st.markdown("### 6. Position Sizing & Indian Tax Simulator")
    stop_risk_pct = 0.05 if is_fast_mode else 0.065
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

- **Scenario B: Stop Loss Cut (-6.5% Move)**
  * Gross Exit Value: ₹{slot_amount * 0.935:,.2f}
  * Net Loss Including All Fees & TDS: **-₹{slot_amount - (slot_amount * 0.935 * 0.987):,.2f}** (~₹{max_risk_amount:,.0f})
""")

    # 7. 5-YEAR EMPIRICAL BACKTEST RESULTS
    st.markdown("### 7. 5-Year Empirical Backtest Results (2021–2026)")
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

    # 8. PLATFORM EXECUTION GUIDE
    st.markdown("### 8. Recommended Execution Platforms in India")
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
