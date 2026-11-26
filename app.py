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

# 🔄 5-Minute Auto-Refresh Default for Live Market Tracking (Configurable in Sidebar)
st.markdown('<meta http-equiv="refresh" content="300">', unsafe_allow_html=True)


def format_display_date(d_str: str) -> str:
    """Format dates/timestamps into clean human-readable tags like '16 Nov', '17 Nov 09:35', or '18 Nov (Market Hours)'."""
    if not d_str:
        return "—"
    try:
        s = str(d_str).strip()
        if "15:30" in s or "Intraday" in s or "Market Hours" in s:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return f"{dt.strftime('%d %b')} (Market Hours)"
        elif len(s) >= 16 and " " in s:
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
        options=["nifty500", "high_beta_apex", "nifty50"],
        format_func=lambda u: {
            "nifty500": "⚡ Nifty 500 (Recommended — Mid/SmallCap Rockets)",
            "high_beta_apex": "🎯 Apex Super-Movers (86+ High-Beta Leaders)",
            "nifty50": "🏛️ Nifty 50 (Large-Cap Bluechips Only)",
        }.get(u, u.upper()),
        index=0,
    )

    refresh_option = st.selectbox(
        "Live Price & Portfolio Refresh",
        options=["5m", "1m", "15m", "off"],
        format_func=lambda x: {
            "5m": "⚡ Every 5 Minutes (Active)",
            "1m": "🚀 Every 1 Minute (Ultra-Fast)",
            "15m": "⏱️ Every 15 Minutes",
            "off": "⏸️ Manual Only",
        }.get(x, x),
        index=0,
        help="Controls how frequently the dashboard audits open paper positions, trigger prices, and live MTM",
    )
    refresh_seconds = {"1m": 60, "5m": 300, "15m": 900, "off": None}.get(refresh_option, 300)
    if refresh_seconds and refresh_seconds != 300:
        st.markdown(f'<meta http-equiv="refresh" content="{refresh_seconds}">', unsafe_allow_html=True)

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

# ─── Cached Apex Scanner (Prevents Blocking App Load) ────────────────────────
@st.cache_data(ttl=900, show_spinner=False)
def get_cached_apex_scan(cap: float, slots: int, radar: int, univ: str) -> dict:
    """Cache full market scans for 15 minutes across user sessions."""
    return run_apex_scan(capital=cap, top_slots=slots, radar_slots=radar, universe_preset=univ)

picks: list[dict] = []

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
    if run_btn:
        with st.spinner(f"Scanning {universe.upper()} for institutional volume, breakout pivots & relative strength…"):
            res = run_apex_scan(capital=swing_capital, top_slots=5, radar_slots=20, universe_preset=universe)
            st.session_state["brief"] = res
            t1_picks = res.get("picks") or res.get("top_picks") or []
            t2_radar = res.get("radar_watchlist") or []
            if t1_picks or t2_radar:
                log_today_picks(t1_picks, t2_radar)
            try:
                import json
                latest_scan_path = os.path.join(ROOT, "data", "latest_scan.json")
                with open(latest_scan_path, "w", encoding="utf-8") as f:
                    json.dump(res, f, indent=2, default=str)
            except Exception:
                pass

    brief = st.session_state.get("brief")
    if not brief or not (brief.get("picks") or brief.get("top_picks")):
        latest_scan_path = os.path.join(ROOT, "data", "latest_scan.json")
        if os.path.exists(latest_scan_path):
            try:
                import json
                with open(latest_scan_path, "r", encoding="utf-8") as f:
                    cached_brief = json.load(f)
                if cached_brief and (cached_brief.get("picks") or cached_brief.get("top_picks")):
                    st.session_state["brief"] = cached_brief
                    brief = cached_brief
            except Exception:
                pass

    if not brief or not (brief.get("picks") or brief.get("top_picks")):
        with st.spinner("Loading live Apex market intelligence…"):
            res = get_cached_apex_scan(swing_capital, 5, 20, universe)
            st.session_state["brief"] = res
            brief = res
            t1_picks = res.get("picks") or res.get("top_picks") or []
            t2_radar = res.get("radar_watchlist") or []
            if t1_picks or t2_radar:
                log_today_picks(t1_picks, t2_radar)

    picks = brief.get("picks") or brief.get("top_picks") or []
    radar = brief.get("radar_watchlist") or []
    macro = brief.get("macro") or {
        "regime": brief.get("regime", "BULLISH"),
        "is_regime_gate_cleared": brief.get("nifty_cleared", True),
    }
    leading_secs = brief.get("leading_sectors") or []


    # 1. Macro Regime, Live Market Breadth & Institutional Leading Sector Banner
    b_col1, b_col2, b_col3 = st.columns([1, 1, 2])
    with b_col1:
        regime = macro.get("regime", "BULLISH")
        reg_cleared = macro.get("is_regime_gate_cleared", True)
        if reg_cleared:
            st.metric("Market Climate", f"🟢 {regime}", "NIFTY Cleared (Longs Active)")
        else:
            st.metric("Market Climate", f"🛡️ {regime}", "NIFTY < 50 SMA (Selective Alpha)")

    with b_col2:
        breadth_val = float(brief.get("market_breadth_pct") or 50.0)
        if breadth_val >= 65.0:
            st.metric("NSE500 Breadth", f"🚀 {breadth_val:.1f}%", "Supercharger Regime (≥65%)")
        elif breadth_val >= 45.0:
            st.metric("NSE500 Breadth", f"🟢 {breadth_val:.1f}%", "Healthy Breadth Gate (≥45%)")
        else:
            st.metric("NSE500 Breadth", f"🛡️ {breadth_val:.1f}%", "Cash Shield Active (<45%)", delta_color="inverse")

    with b_col3:
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

    # 2. Tier 1: Active 5-Slot Execution Cards
    st.subheader("⚡ Tier 1: High-Conviction Execution Cards (5 Slots • 20% Capital Each)")
    st.caption("Active breakouts firing today with heavy institutional volume (RVOL ≥ 1.5x), Stage-2 momentum, and 2:1+ Reward-to-Risk.")

    if picks:
        p_cols = st.columns(len(picks[:5]))
        for idx, p in enumerate(picks[:5]):
            with p_cols[idx]:
                with st.container(border=True):
                    st.markdown(f"### Slot {idx+1}: **{p.get('name', p['ticker'].replace('.NS',''))}**")
                    st.caption(f"Pattern: **{p.get('pattern', 'BREAKOUT')}** | Sector: **{p.get('sector', 'General')}**")
                    
                    pivot_trigger = float(p.get("pivot_buy_stop") or (float(p.get("current_price", 0.0)) * 1.015))
                    cur_px = float(p.get("current_price", 0.0))
                    max_buy = float(p.get("max_buy_zone") or round(pivot_trigger * 1.025, 2))
                    stop_pct = float(p.get("stop_loss_pct", 5.0))
                    rr_ratio = float(p.get("reward_risk", 4.0))
                    
                    c_p1, c_p2 = st.columns(2)
                    c_p1.metric("Breakout Trigger (GTT)", f"₹{pivot_trigger:,.2f}", "Pivot Buy-Stop")
                    c_p2.metric("Buy-Zone Max (Ceiling)", f"₹{max_buy:,.2f}", "Do Not Chase >")
                    
                    c_t1, c_t2 = st.columns(2)
                    c_t1.metric("Target (+20%)", f"₹{p['target_price']:,.2f}", f"+{p.get('target_pct', 20.0):.1f}%")
                    c_t2.metric(f"Stop Loss (-{stop_pct:.1f}%)", f"₹{p['stop_loss']:,.2f}", f"R:R {rr_ratio:.1f}:1", delta_color="inverse")
                    
                    st.divider()
                    st.markdown(f"**Recommended Allocation:**")
                    st.write(f"• **{p.get('shares', 0)} shares** = **₹{p.get('allocated_rupees', 0):,.2f}** ({p.get('weight_pct', 20.0)}% of corpus)")
                    st.write(f"• **RVOL**: `{p.get('rvol', 1.0):.2f}x` | **RS vs Nifty**: `{p.get('rs_vs_nifty', 0):+.1f}%`")
                    st.write(f"• **Est Delivery**: `{p.get('est_delivery_pct', 50):.1f}%` | **72H Gate**: Active")
                    
                    st.info("💡 **Execution Rule**: Set a **GTT Buy-Stop** at the **Breakout Trigger** under **CNC / Delivery**. If opening price > Buy-Zone Max, do NOT chase!")
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
                "Comp RS": f"{r.get('composite_rs', 0):+.1f}%",
                "RS vs Nifty": f"{r.get('rs_vs_nifty', 0):+.1f}%",
                "RVOL": f"{r.get('rvol', 1.0):.2f}x",
                "Order Type": "GTT Buy-Stop (Pending)",
                "Action Plan": r.get("action_plan", "Track for breakout"),
            }
            for r in sorted(radar, key=lambda x: float(x.get("composite_rs", 0.0)), reverse=True)[:15]
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
# TAB 2: AUTOMATED LIVE PAPER TRACKER (9-WAY PARALLEL TOURNAMENT)
# ─────────────────────────────────────────────────────────────────────────────
with tab_paper:
    st.subheader("🛡️ Automated Paper Testing Journal")
    st.caption("100% automated forward-tracking: All 9 strategies are automatically paper-traded and audited every 5 minutes during market hours with live MTM.")

    # High-speed cached summary: reads data/dual_tracker.json in <2ms
    @st.cache_data(ttl=15, show_spinner=False)
    def get_fast_tournament_summary() -> dict:
        return compute_dual_summary()

    force_audit_clicked = False
    r_col1, r_col2 = st.columns([3, 1])
    with r_col2:
        if st.button("🔄 Force Audit Now", use_container_width=True):
            force_audit_clicked = True

    if force_audit_clicked:
        with st.spinner("Auditing all live ticks across all 9 tracks…"):
            dual_summary = audit_and_update_dual_tracker()
            st.cache_data.clear()
            st.rerun()
    else:
        dual_summary = get_fast_tournament_summary()

    t1 = dual_summary.get("track_algo4", dual_summary.get("track_1", {}))
    t2 = dual_summary.get("option_3", dual_summary.get("track_2", {}))
    t3 = dual_summary.get("track_algo5", dual_summary.get("track_3", {}))
    t4 = dual_summary.get("option_2", dual_summary.get("track_4", {}))
    t5 = dual_summary.get("track_c", dual_summary.get("track_5", {}))
    t6 = dual_summary.get("track_apex_compounder", dual_summary.get("track_6", {}))
    t7 = dual_summary.get("track_conviction_2slot", dual_summary.get("track_7", {}))
    t8 = dual_summary.get("track_apex_1slot", dual_summary.get("track_8", {}))
    t9 = dual_summary.get("track_monthly_swing", dual_summary.get("track_9", {}))

    t1_a = dual_summary.get("track_1_legacy", {})
    t2_a = dual_summary.get("track_2_legacy", {})
    t3_a = dual_summary.get("track_3_legacy", {})
    t4_a = dual_summary.get("track_4_legacy", {})
    t5_a = dual_summary.get("track_5_legacy", {})
    t6_a = dual_summary.get("track_6_legacy", {})
    t7_a = dual_summary.get("track_7_legacy", {})
    t8_a = dual_summary.get("track_8_legacy", {})
    t9_a = dual_summary.get("track_9_legacy", {})

    t10 = dual_summary.get("track_c_dna_1slot", dual_summary.get("track_10", {}))
    t11 = dual_summary.get("track_c_eda_2slot_10d", dual_summary.get("track_11", {}))
    t12 = dual_summary.get("track_c_dna_monthly", dual_summary.get("track_12", {}))
    t13 = dual_summary.get("track_c_dna_2slot_t1", dual_summary.get("track_13", {}))

    with r_col1:
        st.info(f"### {dual_summary.get('winner', 'TIE (Evaluating)')}\n\nLast auto-audited: **{dual_summary.get('updated_at')}** | **22-Track A/B/C Tournament**: 9 Quant EDA (Tech B) + 9 Legacy Twins (Tech A, Muted) + 4 DNA/EP Challengers (Tech C, Muted).")

    # 📖 Order & Table Guide for User Clarity
    with st.expander("📖 Order Guide: How to Read Tables & When to Place Orders", expanded=False):
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

    # ⚔️ 18-Track Live A/B Shortlist Comparison Table
    st.markdown("### ⚔️ Live A/B Shortlist Duel (New EDA Tech B vs Legacy Tech A)")
    st.caption("Compares our **Upgraded Quant EDA Shortlist (Composite RS + CLV + 45% Breadth + RS Auction + Wide Radar)** directly against the **Legacy Shortlist (RVOL + FIFO)** across all 9 tracks. Legacy A tracks are muted on Telegram.")
    ab_pairs = [
        ("Track 6: Apex 3-Slot Compounder", t6, t6_a),
        ("Track 7: 2-Slot Conviction", t7, t7_a),
        ("Track 8: 1-Slot Apex Rocket", t8, t8_a),
        ("Track 9: Active 1–2M Swing", t9, t9_a),
        ("Track 1: Algo 4 (20-EMA Bounce)", t1, t1_a),
        ("Track 2: Algo 1 (Morning Ignition)", t2, t2_a),
        ("Track 3: Algo 5 (52W Breakaway Blast)", t3, t3_a),
        ("Track 4: Algo 2 (Minervini VCP)", t4, t4_a),
        ("Track 5: Algo 3 (Velocity Sniper)", t5, t5_a),
    ]
    ab_rows = []
    for label, b_d, a_d in ab_pairs:
        b_pnl = float(b_d.get("total_pnl_inr", 0.0))
        a_pnl = float(a_d.get("total_pnl_inr", 0.0))
        delta = b_pnl - a_pnl
        edge_winner = "🚀 Tech B (EDA)" if delta > 0.01 else ("📦 Tech A (Legacy)" if delta < -0.01 else "⚖️ Tie")
        ab_rows.append({
            "Strategy Track": label,
            "Tech B (EDA) P&L": f"₹{b_pnl:+,.2f} ({b_d.get('total_pnl_pct', 0.0):+.2f}%)",
            "B Open/Cls/Pend": f"{b_d.get('open_count', 0)}/{b_d.get('closed_count', 0)}/{b_d.get('pending_count', 0)}",
            "Tech A (Legacy) P&L": f"₹{a_pnl:+,.2f} ({a_d.get('total_pnl_pct', 0.0):+.2f}%)",
            "A Open/Cls/Pend": f"{a_d.get('open_count', 0)}/{a_d.get('closed_count', 0)}/{a_d.get('pending_count', 0)}",
            "EDA Alpha Edge (B - A)": f"₹{delta:+,.2f}",
            "A/B Leader": edge_winner,
        })
    st.dataframe(pd.DataFrame(ab_rows), use_container_width=True, hide_index=True)

    # ⚡ Group C Challengers Comparison Table (Tracks 10 - 13)
    st.markdown("### ⚡ Group C Challengers (Part-A DNA, Episodic Pivots & Day-10 Rotation)")
    st.caption("Research-backed challengers running live alongside A/B (`₹2–75 Cr/day` super-mover DNA, Dip/Runaway GTT cleanup, Day-10 dead-money rotation & T1 high-win check). Telegram intraday alerts muted.")
    c_rows = []
    for c_label, c_d, ref_str in [
        ("Track 10: DNA 1-Slot EP + Day-10 Cut", t10, "56.3% CAGR | 45.8% WR | DD -38.4%"),
        ("Track 11: EDA 2-Slot + Day-10 Cut", t11, "62.9% CAGR | -37.0% DD (vs -51.9%)"),
        ("Track 12: DNA Monthly Swing", t12, "21.1% CAGR | 38.8% WR | DD -37.6%"),
        ("Track 13: DNA 2-Slot High-Win (T1+BE)", t13, "59.3% WR | 26.5% CAGR"),
    ]:
        c_pnl = float(c_d.get("total_pnl_inr", 0.0))
        c_rows.append({
            "Challenger Track": c_label,
            "5Y Audited Profile": ref_str,
            "Live P&L (INR)": f"₹{c_pnl:+,.2f} ({c_d.get('total_pnl_pct', 0.0):+.2f}%)",
            "Open / Cls / Pend": f"{c_d.get('open_count', 0)}/{c_d.get('closed_count', 0)}/{c_d.get('pending_count', 0)}",
            "Win Rate": f"{c_d.get('win_rate', 0.0):.1f}%" if c_d.get("closed_count", 0) > 0 else "—",
            "Free Cash": f"₹{c_d.get('cash_free', 100000.0):,.0f}",
        })
    st.dataframe(pd.DataFrame(c_rows), use_container_width=True, hide_index=True)

    st.markdown("### 💎 High-CAGR Apex Compounders & Swing Engines")
    sc6, sc7, sc8, sc9 = st.columns(4)
    with sc6:
        with st.container(border=True):
            st.markdown("#### 💎 Track 6: Apex 3-Slot")
            st.caption("Apex 3-Slot Compounder [57.9% CAGR]. 10W EMA trail + base-on-base pyramid. Slots: 40/30/30.")
            st.metric("Total P&L", f"₹{t6.get('total_pnl_inr', 0.0):+,.0f}", f"{t6.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t6 = f"{t6.get('win_rate', 0.0):.1f}%" if t6.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t6)
            pf_label_t6 = f"{t6.get('profit_factor', 1.0):.2f}" if t6.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t6)
            st.metric("Active Trades", f"{t6.get('open_count', 0)} open", f"{t6.get('pending_count', 0)} pending")
            st.caption("🔔 Telegram: **Armed**")

    with sc7:
        with st.container(border=True):
            st.markdown("#### 🔥 Track 7: Conviction 2-Slot")
            st.caption("2-Slot Conviction Compounder [53.5% CAGR]. Maximum focus, 50% capital per slot.")
            st.metric("Total P&L", f"₹{t7.get('total_pnl_inr', 0.0):+,.0f}", f"{t7.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t7 = f"{t7.get('win_rate', 0.0):.1f}%" if t7.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t7)
            pf_label_t7 = f"{t7.get('profit_factor', 1.0):.2f}" if t7.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t7)
            st.metric("Active Trades", f"{t7.get('open_count', 0)} open", f"{t7.get('pending_count', 0)} pending")
            st.caption("🔔 Telegram: **Armed**")

    with sc8:
        with st.container(border=True):
            st.markdown("#### 👑 Track 8: 1-Slot Rocket")
            st.caption("1-Slot Apex Leader Rocket [66.9% CAGR]. 100% all-in single monster trend rider.")
            st.metric("Total P&L", f"₹{t8.get('total_pnl_inr', 0.0):+,.0f}", f"{t8.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t8 = f"{t8.get('win_rate', 0.0):.1f}%" if t8.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t8)
            pf_label_t8 = f"{t8.get('profit_factor', 1.0):.2f}" if t8.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t8)
            st.metric("Active Trades", f"{t8.get('open_count', 0)} open", f"{t8.get('pending_count', 0)} pending")
            st.caption("🔔 Telegram: **Armed**")

    with sc9:
        with st.container(border=True):
            st.markdown("#### 🌊 Track 9: Monthly Swing")
            st.caption("Active 1-to-2 Month Swing Engine [25.6% CAGR]. 4 slots, Day 21 stagnation filter.")
            st.metric("Total P&L", f"₹{t9.get('total_pnl_inr', 0.0):+,.0f}", f"{t9.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t9 = f"{t9.get('win_rate', 0.0):.1f}%" if t9.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t9)
            pf_label_t9 = f"{t9.get('profit_factor', 1.0):.2f}" if t9.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t9)
            st.metric("Active Trades", f"{t9.get('open_count', 0)} open", f"{t9.get('pending_count', 0)} pending")
            st.caption("🔔 Telegram: **Armed**")

    st.markdown("### ⚡ Rapid Momentum & Benchmark Tracks")
    # 5-Way Parallel Tournament Scorecards
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    with sc1:
        with st.container(border=True):
            st.markdown("#### 🥇 Track 1: Algo 4")
            st.caption("Confirmed 20-EMA Bounce Pivot [Alpha Leader]. Sells 50% at +5%, trails stop, +12% target.")
            st.metric("Total P&L", f"₹{t1.get('total_pnl_inr', 0.0):+,.0f}", f"{t1.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t1 = f"{t1.get('win_rate', 0.0):.1f}%" if t1.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t1)
            pf_label_t1 = f"{t1.get('profit_factor', 1.0):.2f}" if t1.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t1)
            st.metric("Active Trades", f"{t1.get('open_count', 0)} open", f"{t1.get('pending_count', 0)} pending")
            st.caption("🔔 Telegram: **Armed**")

    with sc2:
        with st.container(border=True):
            st.markdown("#### 🚀 Track 2: Algo 1")
            st.caption("Morning Ignition Thrust [Alpha Rocket]. GTT Buy-Stop on 09:30 RVOL. +12% target.")
            st.metric("Total P&L", f"₹{t2.get('total_pnl_inr', 0.0):+,.0f}", f"{t2.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t2 = f"{t2.get('win_rate', 0.0):.1f}%" if t2.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t2)
            pf_label_t2 = f"{t2.get('profit_factor', 1.0):.2f}" if t2.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t2)
            st.metric("Active Trades", f"{t2.get('open_count', 0)} open", f"{t2.get('pending_count', 0)} pending")
            st.caption("🔔 Telegram: **Armed**")

    with sc3:
        with st.container(border=True):
            st.markdown("#### ⚡ Track 3: Algo 5")
            st.caption("High-RS 52W Breakaway Blast [Momentum Runner]. Morning gap RVOL >= 2.0x, +12% target.")
            st.metric("Total P&L", f"₹{t3.get('total_pnl_inr', 0.0):+,.0f}", f"{t3.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t3 = f"{t3.get('win_rate', 0.0):.1f}%" if t3.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t3)
            pf_label_t3 = f"{t3.get('profit_factor', 1.0):.2f}" if t3.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t3)
            st.metric("Active Trades", f"{t3.get('open_count', 0)} open", f"{t3.get('pending_count', 0)} pending")
            st.caption("🔔 Telegram: **Armed**")

    with sc4:
        with st.container(border=True):
            st.markdown("#### 🛡️ Track 4: Algo 2")
            st.caption("Minervini VCP Squeeze [Silent Benchmark]. 9:20 AM Confirmation rule.")
            st.metric("Total P&L", f"₹{t4.get('total_pnl_inr', 0.0):+,.0f}", f"{t4.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t4 = f"{t4.get('win_rate', 0.0):.1f}%" if t4.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t4)
            pf_label_t4 = f"{t4.get('profit_factor', 1.0):.2f}" if t4.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t4)
            st.metric("Active Trades", f"{t4.get('open_count', 0)} open", f"{t4.get('pending_count', 0)} pending")
            st.caption("🔇 Telegram: **Muted**")

    with sc5:
        with st.container(border=True):
            st.markdown("#### 🎯 Track 5: Algo 3")
            st.caption("Benchmark Velocity Sniper [Silent Benchmark]. GTT Pivot entry, 72h velocity kill.")
            st.metric("Total P&L", f"₹{t5.get('total_pnl_inr', 0.0):+,.0f}", f"{t5.get('total_pnl_pct', 0.0):+.2f}%")
            wr_label_t5 = f"{t5.get('win_rate', 0.0):.1f}%" if t5.get("closed_count", 0) > 0 else "— (0 Closed)"
            st.metric("Win Rate", wr_label_t5)
            pf_label_t5 = f"{t5.get('profit_factor', 1.0):.2f}" if t5.get("closed_count", 0) > 0 else "—"
            st.metric("Profit Factor", pf_label_t5)
            st.metric("Active Trades", f"{t5.get('open_count', 0)} open", f"{t5.get('pending_count', 0)} pending")
            st.caption("🔇 Telegram: **Muted**")

    st.divider()

    # Detailed 5-Way Strategy Track Drilldowns
    def render_track_details(trk_data: dict, is_gtt: bool = True, is_silent: bool = False):
        desc = trk_data.get("description", "")
        if desc:
            st.info(f"**Strategy Blueprint**: {desc}")
        
        m_c1, m_c2, m_c3, m_c4, m_c5 = st.columns(5)
        m_c1.metric("Available Cash", f"₹{trk_data.get('cash_free', 100000.0):,.2f}")
        m_c2.metric("Capital Deployed", f"₹{trk_data.get('capital_deployed', 0.0):,.2f}")
        m_c3.metric("Realized P&L", f"₹{trk_data.get('realized_pnl_inr', 0.0):+,.2f}")
        m_c4.metric("Floating MTM", f"₹{trk_data.get('floating_pnl_inr', 0.0):+,.2f}")
        m_c5.metric("ROC on Deployed", f"{trk_data.get('roc_deployed_pct', 0.0):+.2f}%")

        if is_silent:
            st.caption("🔇 *Silent Benchmark Mode: Live trades tracked on dashboard for empirical edge comparison. Telegram alerts are muted.*")
        else:
            st.caption("🔔 *Actionable Alpha Mode: Active GTT orders & fills dispatch real-time Telegram trade instructions.*")

        # Pending section
        if is_gtt:
            pends = trk_data.get("pending_triggers", [])
            if pends:
                st.markdown("##### ⏳ Pending GTT Buy-Stop Triggers (Awaiting Breakout):")
                df_pend = pd.DataFrame([
                    {
                        "Ticker": t["ticker"].replace(".NS", ""),
                        "Shortlisted": format_display_date(t.get("shortlist_date", t.get("log_date", ""))),
                        "Scan Px": f"₹{t.get('scan_price', 0.0):,.2f}",
                        "Trigger Px": f"₹{t['pivot_trigger']:,.2f}",
                        "Target": f"₹{t['target_price']:,.2f}",
                        "Stop": f"₹{t['stop_loss']:,.2f}",
                        "Comp RS": f"{t.get('composite_rs', 0.0):+.1f}%",
                        "Status": t.get("status", "PENDING_BREAKOUT_TRIGGER"),
                    }
                    for t in sorted(pends, key=lambda x: float(x.get("composite_rs", 0.0)), reverse=True)
                ])
                st.dataframe(df_pend, use_container_width=True)
        else:
            pends = trk_data.get("pending_confirmations", [])
            if pends:
                st.markdown("##### ⏳ Pending 9:20 AM Confirmations (Awaiting Open):")
                df_pend = pd.DataFrame([
                    {
                        "Ticker": t["ticker"].replace(".NS", ""),
                        "Shortlisted": format_display_date(t.get("shortlist_date", "")),
                        "Open Date": format_display_date(t.get("scheduled_date", "")),
                        "Scan Px": f"₹{t.get('scan_price', 0.0):,.2f}",
                        "Target (+12%)": f"₹{t['target_price']:,.2f}",
                        "Stop (-4%)": f"₹{t['stop_loss']:,.2f}",
                        "Status": t.get("status", "AWAITING_920_OPEN"),
                    }
                    for t in pends
                ])
                st.dataframe(df_pend, use_container_width=True)

        # Open trades section
        opens = trk_data.get("open_trades", [])
        if opens:
            st.markdown("##### ⚡ Triggered Active Positions (Bought during Market Hours):")
            df_open = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", t.get("log_date", t.get("entry_date", "")))),
                    "Bought On": format_display_date(t.get("fill_date", t.get("entry_date", ""))),
                    "Entry Px": f"₹{t['entry_price']:,.2f}",
                    "Cur Px": f"₹{t['current_price']:,.2f}",
                    "Target (+12%)": f"₹{t['target_price']:,.2f}",
                    "Trailed Stop": f"₹{t['stop_loss']:,.2f}",
                    "Days": t.get("days_held", 0),
                    "MTM %": f"{t['pnl_pct']:+.2f}%",
                    "P&L INR": f"₹{t['pnl_rupees']:+,.0f}",
                }
                for t in opens
            ])
            st.dataframe(df_open, use_container_width=True)
        else:
            st.info("No active open positions in this track.")

        # Aborted trades section
        aborts = trk_data.get("aborted_trades", [])
        if aborts:
            st.markdown("##### 🚫 Aborted Trades (Bad Gap-Downs or Runaway FOMO Gaps Avoided):")
            df_abort = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", "")),
                    "Abort Date": format_display_date(t.get("abort_date", "")),
                    "Abort Px": f"₹{t.get('open_price', t.get('abort_price', 0.0)):,.2f}",
                    "Reason": t.get("abort_reason", t.get("reason", "Capital preserved")),
                }
                for t in aborts
            ])
            st.dataframe(df_abort, use_container_width=True)

        # Closed trades section
        closed = trk_data.get("closed_trades", [])
        if closed:
            st.markdown("##### 🏁 Closed Trade History:")
            df_closed = pd.DataFrame([
                {
                    "Ticker": t["ticker"].replace(".NS", ""),
                    "Shortlisted": format_display_date(t.get("shortlist_date", "")),
                    "Bought On": format_display_date(t.get("fill_date", "")),
                    "Exit Date": format_display_date(t.get("exit_date", "")),
                    "Entry Px": f"₹{t['entry_price']:,.2f}",
                    "Exit Px": f"₹{t['exit_price']:,.2f}",
                    "Exit Reason": t.get("exit_reason", ""),
                    "Net P&L (INR)": f"₹{t.get('net_pnl_inr', 0.0):+,.2f}",
                    "Net P&L (%)": f"{t.get('net_pnl_pct', 0.0):+.2f}%",
                    "Friction (INR)": f"₹{t.get('friction_inr', 0.0):,.2f}",
                }
                for t in closed
            ])
            st.dataframe(df_closed, use_container_width=True)

    def render_ab_pair(b_data: dict, a_data: dict, is_gtt: bool = True, b_silent: bool = False):
        st.markdown("#### 🚀 Technique B: Upgraded Quant EDA Shortlist (`Composite RS + CLV + 45% Breadth`)")
        render_track_details(b_data, is_gtt=is_gtt, is_silent=b_silent)
        st.divider()
        with st.expander("📦 Technique A: Legacy Shortlist Twin (RVOL + FIFO | Telegram Muted)", expanded=False):
            render_track_details(a_data, is_gtt=is_gtt, is_silent=True)

    tab_trk6, tab_trk7, tab_trk8, tab_trk9, tab_trkc, tab_trk1, tab_trk2, tab_trk3, tab_trk4, tab_trk5 = st.tabs([
        "💎 Track 6: Apex 3-Slot (57.9%)",
        "🔥 Track 7: 2-Slot Conviction (53.5%)",
        "👑 Track 8: 1-Slot Apex Rocket (66.9%)",
        "🌊 Track 9: Active 1-2M Swing (25.6%)",
        "🧬 Group C: DNA & Day-10 (10–13)",
        "🥇 Track 1: Algo 4 (20-EMA Bounce)",
        "🚀 Track 2: Algo 1 (Morning Ignition)",
        "⚡ Track 3: Algo 5 (52W Breakaway Blast)",
        "🛡️ Track 4: Algo 2 (Minervini VCP Benchmark)",
        "🎯 Track 5: Algo 3 (Benchmark Sniper)",
    ])

    with tab_trk6:
        render_ab_pair(t6, t6_a, is_gtt=True, b_silent=False)
    with tab_trk7:
        render_ab_pair(t7, t7_a, is_gtt=True, b_silent=False)
    with tab_trk8:
        render_ab_pair(t8, t8_a, is_gtt=True, b_silent=False)
    with tab_trk9:
        render_ab_pair(t9, t9_a, is_gtt=True, b_silent=False)
    with tab_trkc:
        st.markdown("#### 🧬 Group C: Part-A Super-Mover DNA, Dip/Runaway GTT Hygiene & Day-10 Challengers")
        for c_title, c_d in [
            ("👑 Track 10: DNA 1-Slot EP + Day-10 Cut [56.3% CAGR | 45.8% WR]", t10),
            ("🔥 Track 11: EDA 2-Slot + Day-10 Cut [62.9% CAGR | -37% DD]", t11),
            ("🌊 Track 12: DNA Monthly Swing [21.1% CAGR | 38.8% WR]", t12),
            ("🎯 Track 13: DNA 2-Slot High-Win (T1+BE) [59.3% WR | 26.5% CAGR]", t13),
        ]:
            with st.expander(c_title, expanded=(c_title.startswith("👑") or c_title.startswith("🔥"))):
                render_track_details(c_d, is_gtt=True, is_silent=True)
    with tab_trk1:
        render_ab_pair(t1, t1_a, is_gtt=True, b_silent=False)
    with tab_trk2:
        render_ab_pair(t2, t2_a, is_gtt=True, b_silent=False)
    with tab_trk3:
        render_ab_pair(t3, t3_a, is_gtt=True, b_silent=False)
    with tab_trk4:
        render_ab_pair(t4, t4_a, is_gtt=False, b_silent=True)
    with tab_trk5:
        render_ab_pair(t5, t5_a, is_gtt=True, b_silent=True)


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
