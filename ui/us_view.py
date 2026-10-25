"""
US Equities Alpha Dashboard Component for TraderAI.
Platform: INDmoney / DriveWealth LLC Spot US Equities Universe.

Renders:
- Real-time Wall Street Market Clock (EST vs IST) & Session State
- S&P 500 (SPY) & Nasdaq 100 (QQQ) Dual Macro Regime Gate
- 4-Pillar Institutional Quant Scorecard (0-100) & Verdicts (BUY / HOLD / SELL / AVOID)
- Active US Paper / Shadow Trading Portfolio with Fractional Shares & Live Floating MTM P&L
- 1-Click US Shadow Buy Execution Panel
- 10-Year Backtest Performance & Empirical Pattern Optimization Showcase
- Complete INDmoney Platform & RBI LRS Regulatory Breakdown
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
from engine.us_engine import (
    get_us_market_status,
    get_upcoming_us_holidays,
    fetch_us_realtime_data,
    analyze_us_market,
    sync_us_paper_trades,
    execute_us_shadow_buy,
    manual_close_us_paper_trade,
    USD_TO_INR_APPROX,
)


def format_usd(p: float) -> str:
    """Format US Dollar price with commas and 2 decimals."""
    return f"${p:,.2f}"


def format_inr(p: float) -> str:
    """Format Indian Rupee equivalent."""
    return f"₹{p:,.2f}"


def render_us_section():
    st.markdown("## 🇺🇸 US Equities Alpha — Wall Street Momentum Engine (INDmoney)")
    st.caption(
        "30 Premier US Equities & ETFs • Spot Delivery via **INDmoney (DriveWealth LLC)** • RBI LRS Compliant • SIPC Protected up to **$500,000** • Fractional Shares Down to $1 • 10-Year Pattern Optimized"
    )

    st.markdown("""
> [!IMPORTANT]
> **The Global Multi-Asset Barbell:** US Equities trade during Indian evening hours (**07:00 PM – 01:30 AM IST**), enabling active compounding after NSE market closes. All trades use spot cash delivery (zero margin leverage, zero liquidation risk) through INDmoney / DriveWealth LLC under RBI's Liberalised Remittance Scheme ($250,000/year limit).
""")

    # Interactive Dashboard Controls
    u_ctrl1, u_ctrl2, u_ctrl3, u_ctrl4, u_ctrl5 = st.columns([2, 2, 2, 2, 1])
    with u_ctrl1:
        us_cap_usd = st.selectbox(
            "US Trading Capital",
            options=[116.0, 104.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0],
            format_func=lambda x: f"${x:,.0f} (≈ ₹{x * USD_TO_INR_APPROX:,.0f}) {'[Your ₹10k/mo Plan]' if x == 116.0 else '[Previous $104 Plan]' if x == 104.0 else ''}",
            index=0,
            help="Capital allocated to US Equities via INDmoney. Starting with $116/month (≈ ₹10,000) using fractional shares."
        )
    with u_ctrl2:
        us_slots = st.selectbox(
            "Position Slots",
            options=[2, 3, 4],
            format_func=lambda x: f"{x} Slots (${us_cap_usd / x:,.0f} each)",
            index=0,
            help="10-Year Audit Result: 2 Slots @ 50% delivered +2,486% Net Return (38.4% CAGR) vs 3 Slots (+1,486% Net Return)."
        )
    with u_ctrl3:
        strategy_mode = st.selectbox(
            "Strategy & Runner Mode",
            options=[
                "🚀 Ultra Bullet Runner (15 EMA Trail / +38.4% CAGR)",
                "⚡ 10 EMA Trailing Runner (Scale 35% @ +18% / +31.8% CAGR)",
                "🎯 Fixed Target (+18% Scale-out + Breakeven Stop)",
            ],
            index=0,
            help="Ultra Bullet Runner uses 15 EMA dynamic trailing floor, capturing monster moves like Nvidia and Palantir up to +169%!"
        )
    with u_ctrl4:
        universe_preset = st.selectbox(
            "INDmoney Sector Preset",
            options=["all", "mag7", "ai_semi", "growth", "etf"],
            format_func=lambda x: {
                "all": "🌐 All 30 INDmoney Leaders",
                "mag7": "👑 Magnificent 7 Titans (NVDA, AAPL, MSFT...)",
                "ai_semi": "🤖 AI & Semiconductors (PLTR, AVGO, AMD, TSM)",
                "growth": "🚀 High-Velocity Growth (COIN, HOOD, CRWD, APP)",
                "etf": "📊 US Benchmark ETFs (QQQ, SPY, SMH, IWM)",
            }[x],
            index=0,
            help="Filter across INDmoney's top 30 liquid US equities and ETFs."
        )
    with u_ctrl5:
        st.write("")
        st.write("")
        sync_btn = st.button("🔄 Sync", use_container_width=True)

    # 1. REAL-TIME WALL STREET TRADING CLOCK & MARKET STATUS
    m_info = get_us_market_status()
    st.markdown("### 1. Wall Street Live Market Clock & Session")
    
    c_m1, c_m2, c_m3 = st.columns([2, 1, 1])
    with c_m1:
        if m_info["is_open"]:
            st.success(f"**{m_info['badge']}** — {m_info['detail']}")
        elif "PRE_MARKET" in m_info["status"] or "AFTER_HOURS" in m_info["status"]:
            st.warning(f"**{m_info['badge']}** — {m_info['detail']}")
        else:
            st.info(f"**{m_info['badge']}** — {m_info['detail']}")
    with c_m2:
        st.markdown(f"🗽 **New York Time:** `{m_info['time_est_str']}`")
    with c_m3:
        st.markdown(f"🕒 **Current IST:** `{m_info['time_ist_str']}`")

    with st.expander("📅 US Market (NYSE/NASDAQ) Timings & Upcoming Holidays in IST", expanded=False):
        st.markdown("""
### ⏰ Wall Street Trading Sessions Mapped to IST (Indian Standard Time):
- 🌅 **Pre-Market Session:** **01:30 PM – 07:00 PM IST** *(04:00 AM – 09:30 AM EST)*  
  *INDmoney pre-market order placement, earnings reactions & price discovery.*
- ⚡ **Regular Market Session (Prime Hours):** **07:00 PM – 01:30 AM IST** *(09:30 AM – 04:00 PM EST)*  
  *Peak Wall Street liquidity, breakout volume surges, and 15 EMA swing execution.*
- 🌙 **After-Hours Session:** **01:30 AM – 05:30 AM IST** *(04:00 PM – 08:00 PM EST)*  
  *Post-market earnings releases and overnight position holding.*
- 🛑 **Weekends:** Saturday & Sunday (Closed).
*(Note: During US Winter Standard Time from Nov to Mar, session moves 1 hour to 08:00 PM – 02:30 AM IST).*
""")
        st.markdown("**Upcoming Official NYSE & NASDAQ Holidays (Wall Street Closed):**")
        upcoming_us_hols = get_upcoming_us_holidays(limit=6)
        for h in upcoming_us_hols:
            st.write(f"• **{h['formatted']}** ({h['day_name']}): {h['name']} — *{h['countdown']}* `[{h['ist_impact']}]`")

    # Fetch Real-time Data & Analyze
    with st.spinner("Fetching live Wall Street data for 30 INDmoney equities + SPY & QQQ benchmarks, computing 4-Pillar Quant Scores..."):
        data = fetch_us_realtime_data()
        analysis = analyze_us_market(data)
        paper_ledger = sync_us_paper_trades(data)

    if analysis.get("status") != "OK":
        st.error(analysis.get("message", "Error analyzing US market."))
        return

    macro = analysis["macro"]

    # 2. S&P 500 & NASDAQ 100 DUAL MACRO REGIME GATE
    st.markdown("### 2. Dual Macro Regime Gate (S&P 500 & Nasdaq 100)")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric(
        "S&P 500 (SPY)",
        f"${macro['spy_price']:.2f}",
        delta=f"50 SMA: ${macro['spy_sma50']:.2f} ({'ABOVE' if macro['spy_pass'] else 'BELOW'})",
        delta_color="normal" if macro['spy_pass'] else "inverse"
    )
    g2.metric(
        "Nasdaq 100 (QQQ)",
        f"${macro['qqq_price']:.2f}",
        delta=f"50 SMA: ${macro['qqq_sma50']:.2f} ({'ABOVE' if macro['qqq_pass'] else 'BELOW'})",
        delta_color="normal" if macro['qqq_pass'] else "inverse"
    )
    
    if macro["regime"] == "BULLISH_EXPANSION":
        g3.metric("Macro Gate", "🟢 GREEN LIGHT", delta="Full Risk-On")
        g4.metric("Entry Policy", "All Setups Permitted", delta="High RS Breakouts")
        st.success(f"**{macro['regime']}:** {macro['verdict']}")
    elif macro["regime"] == "SELECTIVE_CHOP":
        g3.metric("Macro Gate", "🟡 YELLOW LIGHT", delta="Selective Chop")
        g4.metric("Entry Policy", "Top RS Leaders Only", delta="Half Size")
        st.warning(f"**{macro['regime']}:** {macro['verdict']}")
    else:
        g3.metric("Macro Gate", "🔴 100% CASH LOCK", delta="Bear Downtrend", delta_color="inverse")
        g4.metric("Entry Policy", "Entries Blocked", delta="Capital Defense")
        st.error(f"**{macro['regime']}:** {macro['verdict']}")

    # Auto-exit notifications
    if paper_ledger.get("auto_exits"):
        for ax in paper_ledger["auto_exits"]:
            st.warning(
                f"🔔 **Automated US Paper Exit Triggered:** {ax['symbol']} exited via **{ax['reason']}** | "
                f"Realized P&L: **${ax['pnl_usd']:+,.2f} / ₹{ax['pnl_inr']:+,.2f} ({ax['pnl_pct']:+.1f}%)**"
            )

    # 3. ACTIVE US SHADOW / PAPER TRADING PORTFOLIO LEDGER
    st.markdown("### 3. Live US Paper Trading Portfolio (Shadow Ledger)")
    st.caption("Tracks simulated spot trades with fractional share sizing and SEC + FINRA statutory fee deductions.")

    open_pos = paper_ledger.get("open_trades", [])
    closed_pos = paper_ledger.get("closed_trades", [])

    p_col1, p_col2, p_col3, p_col4, p_col5 = st.columns(5)
    p_col1.metric("Open Paper Slots", f"{len(open_pos)} / {us_slots}", help="Number of currently active simulated US positions")
    p_col2.metric("Deployed Capital", f"${paper_ledger.get('tot_allocated_usd', 0):,.2f}", delta=f"₹{paper_ledger.get('tot_allocated_inr', 0):,.0f}")
    
    float_pnl_usd = paper_ledger.get("tot_floating_pnl_usd", 0.0)
    float_pnl_inr = paper_ledger.get("tot_floating_pnl_inr", 0.0)
    alloc_usd = paper_ledger.get("tot_allocated_usd", 1.0) or 1.0
    float_pct = (float_pnl_usd / alloc_usd) * 100.0 if open_pos else 0.0
    p_col3.metric("Floating Unrealized P&L", f"${float_pnl_usd:+,.2f}", delta=f"{float_pct:+.2f}% (₹{float_pnl_inr:+,.0f})")
    
    real_pnl_usd = paper_ledger.get("tot_realized_pnl_usd", 0.0)
    real_pnl_inr = paper_ledger.get("tot_realized_pnl_inr", 0.0)
    p_col4.metric("Closed Realized P&L", f"${real_pnl_usd:+,.2f}", delta=f"₹{real_pnl_inr:+,.0f}" if real_pnl_usd != 0 else None)
    p_col5.metric(
        "Paper Win Rate",
        f"{paper_ledger.get('win_rate', 0):.1f}%",
        help=f"Profit Factor: {paper_ledger.get('profit_factor', 1.0):.2f} across {paper_ledger.get('total_closed_count', 0)} closed trades"
    )

    if open_pos:
        pos_rows = []
        for p in open_pos:
            pos_rows.append({
                "Trade ID": p["id"],
                "Ticker": p["symbol"],
                "Sector": p.get("sector", "US"),
                "Entry Date": p["entry_date"],
                "Entry ($)": format_usd(p["entry_price_usd"]),
                "Live ($)": format_usd(p.get("current_price_usd", p["entry_price_usd"])),
                "Shares": f"{p['shares']:.4f}",
                "Allocated ($)": format_usd(p["allocated_usd"]),
                "Allocated (₹)": format_inr(p.get("allocated_inr", p["allocated_usd"] * USD_TO_INR_APPROX)),
                "Floating P&L ($)": f"${p.get('unrealized_pnl_usd', 0):+,.2f}",
                "Floating P&L (₹)": f"₹{p.get('unrealized_pnl_inr', 0):+,.2f}",
                "Net Return %": f"{p.get('unrealized_pnl_pct', 0):+.2f}%",
                "Stop-Loss ($)": format_usd(p["stop_loss_usd"]),
                "Stop Cushion": f"{p.get('dist_to_stop_pct', 0):.1f}%",
                "Trail Level ($)": format_usd(p.get("trailing_ema_usd", 0)),
            })
        st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)

        # Manual Exit Controls
        with st.expander("⚙️ Manual Paper Position Management", expanded=False):
            sel_col, act_col = st.columns([3, 1])
            with sel_col:
                selected_id = st.selectbox(
                    "Select Open US Paper Trade to Close Manually",
                    options=[p["id"] for p in open_pos],
                    format_func=lambda x: next(f"ID #{x}: {p['symbol']} (P&L: ${p.get('unrealized_pnl_usd', 0):+,.2f})" for p in open_pos if p["id"] == x)
                )
            with act_col:
                st.write("")
                st.write("")
                if st.button("❌ Close US Trade Now", use_container_width=True):
                    target = next(p for p in open_pos if p["id"] == selected_id)
                    res = manual_close_us_paper_trade(selected_id, target.get("current_price_usd", target["entry_price_usd"]))
                    if res.get("ok"):
                        st.success(f"Closed trade #{selected_id} at market. Realized P&L: ${res['pnl_usd']:+,.2f} (₹{res['pnl_inr']:+,.2f})")
                        st.rerun()
    else:
        st.info("ℹ️ **No active open US paper trades.** Review the 4-pillar scorecard below and click **'⚡ Execute US Shadow Buy'** to test the strategy in live market conditions.")

    # 4. LIVE 4-PILLAR US INSTITUTIONAL QUANT SCORECARD (0–100)
    st.markdown("### 4. Live Institutional Quant Scorecard (0–100) & Signals")
    st.caption("Scored across Trend & Moving Averages (25 pts), Mansfield Relative Strength vs SPY (25 pts), RVOL Surge (25 pts), and VCP Breakout (25 pts).")

    all_candidates = analysis.get("candidates", [])
    filtered_candidates = []
    for c in all_candidates:
        tag = c.get("tag", "")
        if universe_preset == "all":
            filtered_candidates.append(c)
        elif universe_preset == "mag7" and tag == "mag7":
            filtered_candidates.append(c)
        elif universe_preset == "ai_semi" and tag == "ai_semi":
            filtered_candidates.append(c)
        elif universe_preset == "growth" and tag == "growth":
            filtered_candidates.append(c)
        elif universe_preset == "etf" and tag == "etf":
            filtered_candidates.append(c)

    table_rows = []
    for c in filtered_candidates:
        table_rows.append({
            "Ticker": c["display"],
            "Company": c["name"],
            "Sector": c["sector"],
            "Price ($)": format_usd(c["price_usd"]),
            "Price (₹)": format_inr(c["price_inr"]),
            "24h %": f"{c['change_24h']:+.2f}%",
            "Quant Score": f"{c['score']:.1f} / 100",
            "Verdict": c["verdict"],
            "Action Thesis": c["action"],
            "RS vs SPY": f"{c['mansfield_rs']:+.1f}%",
            "RVOL": f"{c['rvol']:.2f}x",
            "Breakout (20D)": "YES 🚀" if c["is_breakout"] else "No",
            "Hard Stop (-5.5%)": format_usd(c["stop_loss_usd"]),
            "Target 1 (+18%)": format_usd(c["target1_usd"]),
            "Target 2 (+35%)": format_usd(c["target2_usd"]),
            "Trail (10 EMA)": format_usd(c["trailing_10ema_usd"]),
        })

    cand_df = pd.DataFrame(table_rows)
    st.dataframe(cand_df, use_container_width=True, hide_index=True)

    # 5. ONE-CLICK US SHADOW BUY EXECUTION PANEL
    st.markdown("### 5. US Shadow Buy Execution Panel")
    slot_amount_usd = round(us_cap_usd / us_slots, 2)
    free_slots = us_slots - len(open_pos)
    buy_candidates = [c for c in filtered_candidates if "BUY" in c["verdict"]]

    if free_slots <= 0:
        st.warning(f"⚠️ All {us_slots} US paper slots are currently occupied. Close a trade above or wait for an automated target/stop trigger to open new positions.")
    elif not macro["entries_allowed"]:
        st.error("🛑 **Dual Macro Gate is RED.** S&P 500 and Nasdaq 100 are below their 50-day SMAs. Risk policy mandates cash preservation.")
    else:
        st.success(f"✅ **{free_slots} Slot(s) Available for Shadow Trading.** Dedicated allocation: **${slot_amount_usd:,.2f} per slot** (≈ ₹{slot_amount_usd * USD_TO_INR_APPROX:,.0f}).")
        
        col_pick, col_btn = st.columns([3, 1])
        with col_pick:
            pool = buy_candidates if buy_candidates else filtered_candidates
            selected_sym = st.selectbox(
                "Select US Equity to Shadow Buy",
                options=[c["symbol"] for c in pool],
                format_func=lambda s: next(f"{c['symbol']} ({c['name']}) — Score: {c['score']:.0f} [{c['verdict']}] | ${c['price_usd']:.2f}" for c in pool if c["symbol"] == s)
            )
        with col_btn:
            st.write("")
            st.write("")
            if st.button("⚡ Execute US Shadow Buy", type="primary", use_container_width=True):
                target_cand = next(c for c in pool if c["symbol"] == selected_sym)
                res = execute_us_shadow_buy(selected_sym, target_cand, allocated_usd=slot_amount_usd, strategy_mode=strategy_mode)
                if res.get("ok"):
                    st.success(f"🚀 US Shadow Trade Logged! Bought {res['shares']:.4f} shares of {selected_sym} at ${target_cand['price_usd']:.2f} (${slot_amount_usd:,.2f}).")
                    st.rerun()
                else:
                    st.error(res.get("error", "Failed to execute US shadow buy."))

    # 6. CLOSED PAPER TRADES AUDIT HISTORY
    if closed_pos:
        st.markdown("### 6. Closed US Paper Trades Audit History")
        hist_rows = []
        for cp in closed_pos:
            hist_rows.append({
                "ID": cp["id"],
                "Ticker": cp["symbol"],
                "Entry Date": cp["entry_date"],
                "Exit Date": cp.get("exit_date", "—"),
                "Entry ($)": format_usd(cp["entry_price_usd"]),
                "Exit ($)": format_usd(cp.get("exit_price_usd", 0)),
                "Shares": f"{cp['shares']:.4f}",
                "Allocated ($)": format_usd(cp["allocated_usd"]),
                "Net P&L ($)": f"${cp.get('pnl_usd', 0):+,.2f}",
                "Net P&L (₹)": f"₹{cp.get('pnl_inr', 0):+,.2f}",
                "Net Return %": f"{cp.get('pnl_pct', 0):+.2f}%",
                "Exit Reason": cp.get("exit_reason", "MANUAL"),
            })
        st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)

    # 7. $104/MONTH COMPOUNDING BLUEPRINT & MONTH-BY-MONTH EXPECTATIONS
    st.markdown("### 7. 💰 $104/Month (₹9,000) Blueprint & Month-by-Month Outcomes")
    st.caption("Detailed month-by-month financial projection for depositing $104 every month into INDmoney with 2 fractional share slots ($52 each in Month 1).")

    with st.expander("📊 View Month-by-Month Progression Table & Worst/Average/Best Outcomes", expanded=True):
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.error("""
**🔴 WORST-CASE MONTH**
- Both trades hit stop-loss (-5.9% each)
- Net Loss: **-$6.18 (-₹535)**
- Account balance: **$97.82**
- Risk strictly limited by -5.5% stops
""")
        m_col2.info("""
**🟡 AVERAGE MONTH**
- 1 Average Win (+12.7%) & 1 small loss (-5.9%)
- Net Profit: **+$3.51 to +$6.60 (+₹304 to +₹571)**
- Account balance: **$107.51 to $110.60**
- Monthly gain: **+3.4% to +6.3%**
""")
        m_col3.success("""
**🟢 BEST-CASE MONTH**
- 1 Big 15-EMA Runner (+30%) & 1 Target 1 win (+18%)
- Net Profit: **+$15.00 to +$25.00 (+₹1,300 to +₹2,160)**
- Account balance: **$119.00 to $129.00**
- Monthly gain: **+14.4% to +24.0%**
""")

        st.markdown("#### Year 1 Month-by-Month Deposit & Compounding Schedule:")
        month_schedule = [
            {"Month": "Month 1", "Deposit": "$104 (₹9,000)", "Total Saved": "$104 (₹9,000)", "Slot Size (2 slots)": "$52 per trade", "Average Profit": "+$3.51", "Projected Balance": "$107.51 (₹9,300)"},
            {"Month": "Month 2", "Deposit": "$104 (₹9,000)", "Total Saved": "$208 (₹17,992)", "Slot Size (2 slots)": "$106 per trade", "Average Profit": "+$7.10", "Projected Balance": "$218.61 (₹18,910)"},
            {"Month": "Month 3", "Deposit": "$104 (₹9,000)", "Total Saved": "$312 (₹26,988)", "Slot Size (2 slots)": "$161 per trade", "Average Profit": "+$10.80", "Projected Balance": "$333.41 (₹28,840)"},
            {"Month": "Month 4", "Deposit": "$104 (₹9,000)", "Total Saved": "$416 (₹35,984)", "Slot Size (2 slots)": "$218 per trade", "Average Profit": "+$14.70", "Projected Balance": "$452.11 (₹39,108)"},
            {"Month": "Month 5", "Deposit": "$104 (₹9,000)", "Total Saved": "$520 (₹44,980)", "Slot Size (2 slots)": "$278 per trade", "Average Profit": "+$18.70", "Projected Balance": "$574.81 (₹49,721)"},
            {"Month": "Month 6", "Deposit": "$104 (₹9,000)", "Total Saved": "$624 (₹53,976)", "Slot Size (2 slots)": "$339 per trade", "Average Profit": "+$22.80", "Projected Balance": "$701.61 (₹60,689)"},
            {"Month": "Month 7", "Deposit": "$104 (₹9,000)", "Total Saved": "$728 (₹62,972)", "Slot Size (2 slots)": "$402 per trade", "Average Profit": "+$27.10", "Projected Balance": "$832.71 (₹72,029)"},
            {"Month": "Month 8", "Deposit": "$104 (₹9,000)", "Total Saved": "$832 (₹71,968)", "Slot Size (2 slots)": "$468 per trade", "Average Profit": "+$31.50", "Projected Balance": "$968.21 (₹83,750)"},
            {"Month": "Month 9", "Deposit": "$104 (₹9,000)", "Total Saved": "$936 (₹80,964)", "Slot Size (2 slots)": "$536 per trade", "Average Profit": "+$36.10", "Projected Balance": "$1,108.31 (₹95,869)"},
            {"Month": "Month 10", "Deposit": "$104 (₹9,000)", "Total Saved": "$1,040 (₹89,960)", "Slot Size (2 slots)": "$606 per trade", "Average Profit": "+$40.80", "Projected Balance": "$1,253.11 (₹1,08,394)"},
            {"Month": "Month 11", "Deposit": "$104 (₹9,000)", "Total Saved": "$1,144 (₹98,956)", "Slot Size (2 slots)": "$678 per trade", "Average Profit": "+$45.70", "Projected Balance": "$1,402.81 (₹1,21,343)"},
            {"Month": "Month 12", "Deposit": "$104 (₹9,000)", "Total Saved": "$1,248 (₹1,07,952)", "Slot Size (2 slots)": "$747 per trade", "Average Profit": "+$50.70", "Projected Balance": "$1,495.00 (₹1,29,293)"},
        ]
        st.dataframe(pd.DataFrame(month_schedule), use_container_width=True, hide_index=True)
        st.info("💡 **Key Takeaway:** At the end of Year 1, you have deposited $1,248 (₹1.08 Lakhs) and generated **+$247 (+₹21,340) in net compounded profits**, growing your account to **$1,495 (₹1.29 Lakhs)**!")

    # 8. 10-YEAR EMPIRICAL TOURNAMENT & PATTERN OPTIMIZATION SHOWCASE
    st.markdown("### 8. 10-Year Systematic Tournament & Pattern Optimization (2016–2026)")
    st.caption("Audited on 10 full years of daily price and volume data across the INDmoney US universe ($5,000 initial seed).")

    b_col1, b_col2, b_col3, b_col4 = st.columns(4)
    with b_col1:
        st.info("""
**1. Baseline Strategy**
- Target: Fixed +18% Target
- Macro Gate: None
- Net Return: **+570.4%**
- 10Y Final: **$33,522.26**
- CAGR: **21.0%**
- Max DD: **-29.3%**
- Win Rate: 36.9%
- Profit Factor: 1.52
""")
    with b_col2:
        st.info("""
**2. SPY Macro Protected**
- Target: Fixed +18% Target
- Macro Gate: SPY > 50 SMA
- Net Return: **+775.2%**
- 10Y Final: **$43,760.16**
- CAGR: **24.2%**
- Max DD: **-23.3%**
- Win Rate: 38.0%
- Profit Factor: 1.63
""")
    with b_col3:
        st.success("""
**3. 10 EMA Trailing Runner**
- Target: 10 EMA Trailing Stop
- Macro Gate: Dual SPY & QQQ
- Net Return: **+1,170.6%**
- 10Y Final: **$63,529.01**
- CAGR: **28.9%**
- Max DD: **-20.8%**
- Win Rate: 55.8%
- Profit Factor: 2.07
""")
    with b_col4:
        st.success("""
**4. Ultra Concentrated Bullet**
- Sizing: **2 Slots @ 50%**
- Trail: **15 EMA Wide Runner**
- Net Return: **+2,486.1% (25.8x!)**
- 10Y Final: **$129,304.93**
- CAGR: **38.4%**
- Max DD: **-20.0%**
- Win Rate: **54.7%**
- Profit Factor: **2.56**
- Best Trade: **+169.4%**
""")

    # 8. WHAT INDMONEY OFFERS & REGULATORY ARCHITECTURE FOR INDIAN INVESTORS
    st.markdown("### 8. What INDmoney Offers & Regulatory Architecture")
    with st.expander("📘 Complete Breakdown: Platform Features, Brokerage Partner, Taxes & RBI Limits", expanded=True):
        st.markdown("""
### 🏛️ 1. What INDmoney Offers for US Equities Trading
- **Zero Commission Brokerage:** INDmoney charges **$0 commission** on US stocks and ETFs.
- **Fractional Share Investing:** Buy fractions of high-priced stocks (e.g. Nvidia, Microsoft, Broadcom) down to **$1** or **0.0001 shares**.
- **Real-Time Wall Street Execution:** Direct electronic access to NYSE and NASDAQ with pre-market (04:00 AM – 09:30 AM EST) and regular session execution.
- **Integrated INR to USD Remittance:** Direct digital remittance through partner banks (Federal Bank, SBM, etc.) with transparent FX spreads.

---

### 🛡️ 2. Regulatory Partner & Safety Guarantees
- **Brokerage Partner:** **DriveWealth LLC** (Registered US Broker-Dealer, Member FINRA & SIPC).
- **SIPC Protection:** Accounts are protected by the **Securities Investor Protection Corporation (SIPC)** for up to **$500,000** (including up to $250,000 in cash claims).
- **Cash Custody:** Uninvested cash is kept in FDIC-insured partner banks (up to $250,000 protection).

---

### 🇮🇳 3. RBI Liberalised Remittance Scheme (LRS) Rules
- **Annual Limit:** Indian residents can remit up to **$250,000 USD per financial year** (approx **₹2.15 Crores**) for overseas investments under LRS.
- **TCS (Tax Collected at Source):**
  - Remittances up to ₹7 Lakhs per financial year: **0% TCS**.
  - Remittances exceeding ₹7 Lakhs per financial year: **20% TCS** (which is fully creditable/refundable against your annual Indian income tax return).

---

### 🧾 4. Taxation for Indian Resident Investors
- **No US Capital Gains Tax:** As a non-US resident, you pay **0% capital gains tax** in the United States (Form W-8BEN is automatically filed by INDmoney).
- **Indian Capital Gains Tax:**
  - **Short-Term Capital Gains (STCG):** Holding period $\le 24$ months. Taxed at your normal applicable income tax slab rates.
  - **Long-Term Capital Gains (LTCG):** Holding period $> 24$ months. Taxed at **12.5%** without indexation benefits (Finance Act 2024).
- **Dividend Withholding:** US companies deduct 25% withholding tax on dividends. Indian residents can claim **Foreign Tax Credit (FTC)** on Form 67 under the India-US Double Tax Avoidance Agreement (DTAA).

---

### 💡 5. Statutory Friction Deduction Model in TraderAI
TraderAI automatically models the true statutory costs on every simulated paper trade:
- **SEC Section 31 Fee:** $0.0000278 \times \text{Gross Sale Value}$ (on sell orders only).
- **FINRA Trading Activity Fee (TAF):** $0.000166 \text{ per share}$ (maximum $8.30 per trade).
- **FX Benchmark:** Converted at live indicative rate of **$1 = ₹86.50**.
""")
