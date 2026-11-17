"""
TraderAI - Apex High-Velocity Dashboard (v3.4.0-clean)
Ultra-Clean, High-Velocity Indian Momentum Recommender & Automated Paper Tracker
- Tab 1: ⚡ Apex Picks & Radar (Top 3 Execution Cards + Coiling Radar Watchlist)
- Tab 2: 🛡️ Automated Live Paper Tracker (Option 2 vs Option 3 Live Duel with 30-min Auto-Refresh)
- Tab 3: 💼 Demat Holdings & Sizing (Kotak Sync, Holdings Audit & Sizing Calculator)
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime

import streamlit as st
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import (
    ALLOCATION_PROFILES,
    DEFAULT_ALLOCATION_PROFILE,
    HIGH_BETA_APEX_STOCKS,
    MONTHLY_STOCK_BUDGET,
)
from portfolio.manager import (
    portfolio_summary,
    sync_from_kotak,
    upsert_holding,
)
from engine.pipeline import run_pipeline
from engine.apex_engine import run_apex_scan
from engine.dual_tracker import (
    audit_and_update_dual_tracker,
    log_today_picks,
    compute_dual_summary,
)
from data.market_calendar import get_market_status
from data.broker import is_configured

logging.basicConfig(level=logging.INFO)
st.set_page_config(
    page_title="TraderAI ⚡ Apex Super-Movers",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 🔄 30-Minute Auto-Refresh Meta Tag for Live Market Tracking
st.markdown('<meta http-equiv="refresh" content="1800">', unsafe_allow_html=True)


def format_display_date(d_str: str) -> str:
    """Format dates/timestamps into clean human-readable tags like '16 Nov' or '17 Nov 09:35'."""
    if not d_str:
        return "—"
    try:
        s = str(d_str).strip()
        if len(s) >= 16 and " " in s:
            dt = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%d %b %H:%M")
        elif len(s) >= 10:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return dt.strftime("%d %b")
    except Exception:
        pass
    return str(d_str)


# ─── Top Header & Market Status ──────────────────────────────────────────────
h_col1, h_col2 = st.columns([3, 1])
with h_col1:
    st.title("TraderAI ⚡ Apex Super-Movers")
    st.caption("High-Velocity Indian Momentum Engine • 🇮🇳 NSE Cash Delivery (CNC Only) • Automated Paper Tracker")

with h_col2:
    m_status = get_market_status()
    if m_status.get("is_open"):
        st.success(f"🟢 **{m_status['badge']}** ({m_status['detail']})")
    else:
        st.info(f"⚪ **{m_status['badge']}** ({m_status['detail']})")

# ─── Minimalist Sidebar Controls ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚡ Trading Controls")

    swing_capital = st.number_input(
        "Active Capital (INR)",
        min_value=10000.0,
        value=float(MONTHLY_STOCK_BUDGET if MONTHLY_STOCK_BUDGET >= 10000 else 100000.0),
        step=10000.0,
        format="%.0f",
        help="Capital allocated across concentrated high-velocity slots (33.3% per slot)",
    )

    profile = st.selectbox(
        "Risk Profile",
        options=["apex_3slot", "balanced", "growth"],
        format_func=lambda k: ALLOCATION_PROFILES.get(k, {}).get("label", k),
        index=0,
    )

    universe = st.selectbox(
        "Universe",
        options=["high_beta_apex", "high_beta_rockets", "nifty500"],
        format_func=lambda u: "⚡ Apex Super-Movers (86+ High-Beta Leaders)" if u == "high_beta_apex" else u.upper(),
        index=0,
    )

    run_btn = st.button("⚡ Run Live Market Scan", type="primary", use_container_width=True)

    with st.expander("💼 Demat & Broker Settings", expanded=False):
        sync_broker = st.checkbox("Sync Kotak Neo on Run", value=False)
        totp = ""
        if sync_broker:
            totp = st.text_input("Kotak TOTP (if needed)", type="password")
            if not is_configured():
                st.warning("Kotak keys missing in secrets / .env")

        st.divider()
        st.caption("Manual Demat Holding Entry:")
        m_tick = st.text_input("Ticker", value="TECHM.NS")
        m_q = st.number_input("Shares", min_value=1, value=10)
        m_px = st.number_input("Avg Price", min_value=0.0, value=1700.0)
        if st.button("Save Holding", use_container_width=True):
            upsert_holding(m_tick.strip().upper(), int(m_q), float(m_px), timeframe="short_term")
            st.success(f"Saved {m_tick} to Demat holdings!")

# ─── Run Pipeline / Load Cached Scan ─────────────────────────────────────────
if run_btn:
    with st.spinner("Scanning 86+ high-beta leaders, institutional volume & relative strength…"):
        res = run_apex_scan(capital=swing_capital, top_slots=3, radar_slots=12)
        st.session_state["brief"] = res
        t1_picks = res.get("picks") or res.get("top_picks") or []
        t2_radar = res.get("radar_watchlist") or []
        if t1_picks or t2_radar:
            log_today_picks(t1_picks, t2_radar)

brief = st.session_state.get("brief")
if not brief or not (brief.get("picks") or brief.get("top_picks")):
    with st.spinner("Loading live Apex market intelligence…"):
        res = run_apex_scan(capital=swing_capital, top_slots=3, radar_slots=12)
        st.session_state["brief"] = res
        brief = res
        t1_picks = res.get("picks") or res.get("top_picks") or []
        t2_radar = res.get("radar_watchlist") or []
        if t1_picks or t2_radar:
            log_today_picks(t1_picks, t2_radar)

# ─── Streamlined 3-Tab Interface ─────────────────────────────────────────────
tab_picks, tab_paper, tab_portfolio = st.tabs([
    "⚡ Apex Picks & Radar",
    "🛡️ Live Paper Tracker (Automated)",
    "💼 My Demat Portfolio & Sizing",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: APEX PICKS & RADAR (EXECUTION)
# ─────────────────────────────────────────────────────────────────────────────
with tab_picks:
    picks = brief.get("picks") or brief.get("top_picks") or []
    radar = brief.get("radar_watchlist") or []
    macro = brief.get("macro") or {
        "regime": brief.get("regime", "BULLISH"),
        "is_regime_gate_cleared": brief.get("nifty_cleared", True),
    }
    leading_secs = brief.get("leading_sectors") or []


    # 1. Macro Regime & Institutional Leading Sector Banner
    b_col1, b_col2 = st.columns([1, 2])
    with b_col1:
        regime = macro.get("regime", "BULLISH")
        reg_cleared = macro.get("is_regime_gate_cleared", True)
        if reg_cleared:
            st.metric("Market Climate", f"🟢 {regime}", "NIFTY Cleared (Longs Active)")
        else:
            st.metric("Market Climate", f"🛡️ {regime}", "NIFTY < 50 SMA (Selective Alpha)")

    with b_col2:
        if leading_secs:
            st.write("**🏆 Current Leading Institutional Sectors (Tailwind Gate):**")
            scols = st.columns(min(3, len(leading_secs)))
            for i, s in enumerate(leading_secs[:3]):
                with scols[i]:
                    st.metric(
                        f"Rank #{s.get('sector_rank', i+1)}: {s.get('sector')}",
                        f"{s.get('composite_rs', 0):+.1f}% RS",
                        f"+{s.get('bonus_points', 0):.0f} pts ({s.get('status')})"
                    )

    st.divider()

    # 2. Tier 1: Active 3-Slot Execution Cards
    st.subheader("⚡ Tier 1: High-Conviction Execution Cards (33.3% Capital Each)")
    st.caption("Active breakouts firing today with heavy institutional volume (RVOL ≥ 1.6x), Stage-2 momentum, and 2:1+ Reward-to-Risk.")

    if picks:
        p_cols = st.columns(len(picks[:3]))
        for idx, p in enumerate(picks[:3]):
            with p_cols[idx]:
                with st.container(border=True):
                    st.markdown(f"### Slot {idx+1}: **{p.get('name', p['ticker'].replace('.NS',''))}**")
                    st.caption(f"Pattern: **{p.get('pattern', 'BREAKOUT')}** | Sector: **{p.get('sector', 'General')}**")
                    
                    st.metric("Entry Price", f"₹{p['current_price']:,.2f}")
                    st.metric("Target (+20%)", f"₹{p['target_price']:,.2f}", f"+{p.get('target_pct', 20.0):.1f}%")
                    st.metric("Stop Loss (-7%)", f"₹{p['stop_loss']:,.2f}", f"-{p.get('stop_loss_pct', 7.0):.1f}% (Close)", delta_color="inverse")
                    
                    st.divider()
                    st.markdown(f"**Recommended Allocation:**")
                    st.write(f"• **{p.get('shares', 0)} shares** = **₹{p.get('allocated_rupees', 0):,.2f}** ({p.get('weight_pct', 33.3)}% of corpus)")
                    st.write(f"• **RVOL**: `{p.get('rvol', 1.0):.2f}x` | **RS vs Nifty**: `{p.get('rs_vs_nifty', 0):+.1f}%`")
                    st.write(f"• **Est Delivery**: `{p.get('est_delivery_pct', 50):.1f}%`")
                    
                    st.info("💡 **Execution Rule**: Buy under **CNC / Delivery**. Immediately place a **GTT Stop Loss** at planned stop.")
    else:
        st.info("🛡️ No Tier-1 stocks cleared the strict momentum gate today. Capital preserved in cash.")

    st.divider()

    # 3. Tier 2: High-Velocity Radar Watchlist (No Missed Runners)
    if radar:
        st.subheader("📡 Tier 2: High-Velocity Radar Watchlist (Coiled Setups)")
        st.caption("Solves the shortlisting problem: High-RS leaders coiling near 52W highs. Set a GTT Buy-Stop at the **Pivot Trigger**—when a Tier-1 holding exits, rotate capital here immediately.")

        radar_table = [
            {
                "Ticker": r["ticker"].replace(".NS", ""),
                "Shortlisted": format_display_date(r.get("shortlist_date", datetime.now().strftime("%Y-%m-%d"))),
                "Current Price": f"₹{r['current_price']:,.2f}",
                "Pivot Trigger (GTT Buy-Stop)": f"₹{r['pivot_buy_stop']:,.2f}",
                "Target (+20%)": f"₹{r['target_price']:,.2f}",
                "Stop (-7% Close)": f"₹{r['stop_loss']:,.2f}",
                "Setup Stage": r.get("readiness", "COILING"),
                "RS vs Nifty": f"{r.get('rs_vs_nifty', 0):+.1f}%",
                "RVOL": f"{r.get('rvol', 1.0):.2f}x",
                "Order Type": "GTT Buy-Stop (Pending)",
                "Action Plan": r.get("action_plan", "Track for breakout"),
            }
            for r in radar[:10]
        ]
        st.dataframe(pd.DataFrame(radar_table), use_container_width=True)
        st.info("💡 **Execution Guide**: Place a **GTT Buy-Stop** order overnight in your broker app (Zerodha, Kotak Neo, Groww) at the **Pivot Trigger** under **CNC / Delivery**. The order will **ONLY execute during live market hours (09:15 AM – 03:30 PM IST)** if the price breaks above the trigger. If it doesn't break out, you risk zero capital!")

    st.divider()

    # 4. 1-Click Fast Backtest
    with st.expander("⚡ 1-Click Backtest on Today's Shortlist", expanded=False):
        bcol1, bcol2, bcol3 = st.columns([2, 1, 1])
        with bcol1:
            p_period = st.selectbox("Lookback", ["6mo", "1y", "2y", "3y", "5y"], index=1, key="bt_lookback")
        with bcol2:
            p_cap = st.number_input("Capital (INR)", min_value=10000.0, value=float(swing_capital), step=10000.0, key="bt_cap")
        with bcol3:
            st.write("")
            st.write("")
            run_bt_btn = st.button("Run Simulation", type="primary", key="btn_run_bt")

        if run_bt_btn:
            with st.spinner("Simulating strategy on shortlisted names…"):
                from backtesting.engine import run_simple_backtest
                p_tickers = [p["ticker"] for p in picks if p.get("ticker")]
                bt_res = run_simple_backtest(
                    p_tickers,
                    period=p_period,
                    initial_capital=p_cap,
                    use_trailing_stop=False,
                    use_trend_filter=True,
                    allow_runners=True,
                )
                if bt_res.get("error"):
                    st.error(bt_res["error"])
                else:
                    st.success(f"Simulation completed ({bt_res.get('start_date')} to {bt_res.get('end_date')})")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Strategy Return", f"{bt_res.get('total_return', 0):+.2f}%")
                    m2.metric("Nifty Benchmark", f"{bt_res.get('benchmark_return', 0):+.2f}%")
                    m3.metric("Alpha", f"{bt_res.get('alpha', 0):+.2f}%")
                    m4.metric("Win Rate", f"{bt_res.get('win_rate', 0):.1f}%")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: AUTOMATED LIVE PAPER TRACKER (OPTION 2 VS OPTION 3)
# ─────────────────────────────────────────────────────────────────────────────
with tab_paper:
    st.subheader("🛡️ Automated Paper Testing Journal")
    st.caption("100% automated forward-tracking: All AI picks are automatically paper-traded and audited every 30 minutes with live MTM.")

    # Periodic live audit
    dual_summary = audit_and_update_dual_tracker()
    o2 = dual_summary["option_2"]
    o3 = dual_summary["option_3"]
    oc = dual_summary.get("track_c", {})

    r_col1, r_col2 = st.columns([3, 1])
    with r_col1:
        st.info(f"### {dual_summary.get('winner', 'TIE (Evaluating)')}\n\nLast auto-audited: **{dual_summary.get('updated_at')}** | Simulated Corpus: ₹1,00,000 per strategy")
    with r_col2:
        if st.button("🔄 Force Audit Now", use_container_width=True):
            dual_summary = audit_and_update_dual_tracker()
            st.rerun()

    # 📖 Order & Table Guide for User Clarity
    with st.expander("📖 Order Guide: How to Read Tables & When to Place Orders", expanded=True):
        g1, g2, g3 = st.columns(3)
        with g1:
            st.markdown("##### 1️⃣ Shortlisted Date (Radar)")
            st.caption("When the AI algorithm discovered the setup. Pending triggers sit on radar awaiting breakout confirmation.")
        with g2:
            st.markdown("##### 2️⃣ When to Place GTT Orders")
            st.caption("Place **GTT Buy-Stop** orders on Zerodha / Kotak Neo in the evening at the specified **Trigger Price** under **CNC / Delivery**.")
        with g3:
            st.markdown("##### 3️⃣ Bought On (Market Hours Fill)")
            st.caption("Orders **ONLY execute during live NSE hours (09:15 AM – 03:30 PM IST)** when price crosses the trigger. If flat, zero risk & zero loss!")

    # 3-Way Parallel Scorecards
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        with st.container(border=True):
            st.markdown("#### 🟢 Track A: Option 2")
            st.caption("9:20 AM Confirmation Rule. Fills on normal open, blocks bad gap downs, -7% stop, +20% target.")
            c1, c2 = st.columns(2)
            c1.metric("Total P&L", f"₹{o2['total_pnl_inr']:+,.0f}", f"{o2['total_pnl_pct']:+.2f}%")
            c2.metric("Win Rate", f"{o2['win_rate']:.1f}%")
            c3, c4 = st.columns(2)
            c3.metric("Profit Factor", f"{o2['profit_factor']:.2f}")
            c4.metric("Active Trades", f"{o2['open_count']} open", f"{o2['aborted_count']} blocked")

    with sc2:
        with st.container(border=True):
            st.markdown("#### 🔵 Track B: Option 3")
            st.caption("GTT Buy-Stop Trigger. Fills only when breakout fires. If flat, zero risk & capital preserved. +20% target.")
            c5, c6 = st.columns(2)
            c5.metric("Total P&L", f"₹{o3['total_pnl_inr']:+,.0f}", f"{o3['total_pnl_pct']:+.2f}%")
            c6.metric("Win Rate", f"{o3['win_rate']:.1f}%")
            c7, c8 = st.columns(2)
            c7.metric("Profit Factor", f"{o3['profit_factor']:.2f}")
            c8.metric("Active Trades", f"{o3['open_count']} open", f"{o3['pending_count']} pending")

    with sc3:
        with st.container(border=True):
            st.markdown("#### ⚡ Track C: Benchmark Sniper")
            st.caption("High-Velocity Benchmark. GTT Pivot entry, expanded +25% target, -6% stop, 72h velocity kill on dead money.")
            c9, c10 = st.columns(2)
            c9.metric("Total P&L", f"₹{oc.get('total_pnl_inr', 0.0):+,.0f}", f"{oc.get('total_pnl_pct', 0.0):+.2f}%")
            c10.metric("Win Rate", f"{oc.get('win_rate', 0.0):.1f}%")
            c11, c12 = st.columns(2)
            c11.metric("Profit Factor", f"{oc.get('profit_factor', 1.0):.2f}")
            c12.metric("Active Trades", f"{oc.get('open_count', 0)} open", f"{oc.get('pending_count', 0)} pending")

    st.divider()

    # Active Trades 3 Columns Side by Side
    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        st.markdown("##### 📋 Track A: Active Trades")
        if o2["open_trades"]:
            df_o2 = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", t.get("entry_date", ""))),
                    "Bought On": format_display_date(t.get("fill_date", t.get("entry_date", ""))),
                    "Entry": f"₹{t['entry_price']:,.2f}",
                    "Cur": f"₹{t['current_price']:,.2f}",
                    "Target": f"₹{t['target_price']:,.2f}",
                    "Stop": f"₹{t['stop_loss']:,.2f}",
                    "MTM": f"{t['pnl_pct']:+.2f}%",
                    "P&L": f"₹{t['pnl_rupees']:+,.0f}",
                }
                for t in o2["open_trades"]
            ])
            st.dataframe(df_o2, use_container_width=True)
        else:
            st.write("No active open trades in Option 2.")

        if o2["closed_trades"]:
            st.markdown("##### 🏁 Track A History")
            st.dataframe(pd.DataFrame(o2["closed_trades"]), use_container_width=True)

    with col_t2:
        st.markdown("##### 🎯 Track B: GTT & Active")
        if o3["pending_triggers"]:
            st.caption("⏳ Pending GTT Buy-Stop Triggers (Awaiting Breakout):")
            df_pend = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", t.get("log_date", ""))),
                    "Scan Px": f"₹{t['scan_price']:,.2f}",
                    "Trigger Px": f"₹{t['pivot_trigger']:,.2f}",
                    "Target (+20%)": f"₹{t['target_price']:,.2f}",
                    "Stop (-7%)": f"₹{t['stop_loss']:,.2f}",
                }
                for t in o3["pending_triggers"]
            ])
            st.dataframe(df_pend, use_container_width=True)

        if o3["open_trades"]:
            st.caption("⚡ Triggered Active Trades (Bought during Market Hours):")
            df_o3_open = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", t.get("log_date", t.get("entry_date", "")))),
                    "Bought On": format_display_date(t.get("fill_date", t.get("entry_date", ""))),
                    "Fill Px": f"₹{t['entry_price']:,.2f}",
                    "Cur Px": f"₹{t['current_price']:,.2f}",
                    "Target": f"₹{t['target_price']:,.2f}",
                    "Stop": f"₹{t['stop_loss']:,.2f}",
                    "MTM": f"{t['pnl_pct']:+.2f}%",
                    "P&L": f"₹{t['pnl_rupees']:+,.0f}",
                }
                for t in o3["open_trades"]
            ])
            st.dataframe(df_o3_open, use_container_width=True)
        elif not o3["pending_triggers"]:
            st.write("No active trades in Option 3.")

    with col_t3:
        st.markdown("##### ⚡ Track C: Benchmark Sniper")
        if oc.get("pending_triggers"):
            st.caption("⏳ Pending Benchmark Triggers (+25% Target):")
            df_c_pend = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", t.get("log_date", ""))),
                    "Trigger Px": f"₹{t['pivot_trigger']:,.2f}",
                    "Target (+25%)": f"₹{t['target_price']:,.2f}",
                    "Stop (-6%)": f"₹{t['stop_loss']:,.2f}",
                }
                for t in oc["pending_triggers"]
            ])
            st.dataframe(df_c_pend, use_container_width=True)

        if oc.get("open_trades"):
            st.caption("⚡ Active Velocity Trades (Bought during Market Hours):")
            df_c_open = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", t.get("log_date", t.get("entry_date", "")))),
                    "Bought On": format_display_date(t.get("fill_date", t.get("entry_date", ""))),
                    "Fill Px": f"₹{t['entry_price']:,.2f}",
                    "Cur Px": f"₹{t['current_price']:,.2f}",
                    "Target": f"₹{t['target_price']:,.2f}",
                    "Stop": f"₹{t['stop_loss']:,.2f}",
                    "MTM": f"{t['pnl_pct']:+.2f}%",
                    "P&L": f"₹{t['pnl_rupees']:+,.0f}",
                    "Days": t.get("days_held", 0),
                }
                for t in oc["open_trades"]
            ])
            st.dataframe(df_c_open, use_container_width=True)
        elif not oc.get("pending_triggers"):
            st.write("No active trades in Track C.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: DEMAT HOLDINGS & SIZING CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────
with tab_portfolio:
    st.subheader("💼 Demat Holdings & Capital Sizing")
    
    port = portfolio_summary()
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("Holdings Count", port.get("holdings_count", 0))
    pc2.metric("Portfolio Value", f"₹{port.get('total_value', 0):,.2f}")
    pc3.metric("Floating P&L", f"₹{port.get('total_pnl', 0):+,.2f} ({port.get('total_pnl_percent', 0):+.2f}%)")

    if port.get("holdings"):
        st.dataframe(pd.DataFrame(port["holdings"]), use_container_width=True)
    else:
        st.info("No active holdings recorded. Sync with Kotak Neo or add manually via the sidebar.")

    st.divider()
    st.subheader("🎯 Instant Position Sizing Calculator")
    st.caption("Calculate exact share quantities and GTT stop levels for any custom rupee amount:")
    
    sim_cap = st.number_input("Rupees to deploy", min_value=5000.0, value=30000.0, step=5000.0)
    if sim_cap > 0 and picks:
        calc_rows = []
        for p in picks:
            px = float(p.get("current_price") or 1.0)
            target = float(p.get("target_price") or px * 1.20)
            stop = float(p.get("stop_loss") or px * 0.93)
            shs = int(sim_cap // px)
            inv = shs * px
            calc_rows.append({
                "Stock": p.get("name", p["ticker"].replace(".NS", "")),
                "Price": f"₹{px:,.2f}",
                "Shares to Buy": f"{shs} shares",
                "Total Investment": f"₹{inv:,.2f}",
                "GTT Target (+20%)": f"₹{target:,.2f} (+₹{(target - px) * shs:,.0f})",
                "GTT Stop (-7%)": f"₹{stop:,.2f} (-₹{(px - stop) * shs:,.0f})",
            })
        st.dataframe(pd.DataFrame(calc_rows), use_container_width=True)
