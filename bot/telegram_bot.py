"""
TraderAI - Interactive Telegram Bot & Real-Time Portfolio Monitor
Monitors portfolio gains, losses, trailing stop-losses, and delivers buy/sell recommendations.
Provides interactive commands for mobile tracking without needing a laptop open.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    ALERT_CHECK_INTERVAL_MINS,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
    RISK_CONFIG,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TIMEFRAMES,
)
from data.market_data import fetch_live_quote
from portfolio.manager import load_portfolio, portfolio_summary

logger = logging.getLogger(__name__)


def send_message(text: str, chat_id: Optional[str] = None) -> bool:
    """Send HTML message via Telegram Bot API."""
    token = TELEGRAM_BOT_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID
    if not token or not cid:
        logger.warning("Telegram token or chat ID missing.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def get_portfolio_alerts() -> list[str]:
    """
    Check all active holdings against live market prices and generate actionable alerts:
    - Target achieved (profit booking)
    - Trailing stop-loss triggers
    - Stop-loss warnings
    - Tax-smart holding period advisory
    """
    port = load_portfolio()
    holdings = port.get("holdings", [])
    if not holdings:
        return []

    alerts = []
    today = datetime.now().date()

    for h in holdings:
        sym = h.get("symbol", "")
        qty = int(h.get("quantity") or 0)
        avg = float(h.get("avg_price") or 0)
        tf = h.get("timeframe") or "mid_term"
        p_date_str = h.get("purchase_date")

        if not sym or qty <= 0 or avg <= 0:
            continue

        # Fetch live quote
        quote = fetch_live_quote(sym)
        cur_px = float(quote.get("price") or h.get("current_price") or avg)
        pnl = (cur_px - avg) * qty
        pnl_pct = ((cur_px - avg) / avg * 100) if avg > 0 else 0.0

        # Horizon default targets and stops
        stop_loss_pct = RISK_CONFIG.get("default_stop_loss_pct", 0.05) * 100
        target_pct = RISK_CONFIG.get("default_target_pct", 0.12) * 100

        # 1. Target Reached Alert
        if pnl_pct >= target_pct:
            alerts.append(
                f"🎯 <b>TARGET REACHED: {sym}</b>\n"
                f"Gain: <b>+{pnl_pct:.2f}%</b> (+₹{pnl:,.0f})\n"
                f"Price: ₹{cur_px:,.2f} (Bought at ₹{avg:,.2f})\n"
                f"Bucket: {TIMEFRAMES.get(tf, {}).get('label', tf)}\n"
                f"<i>Advice: Book partial profits (50%) or trail stop to lock gains.</i>"
            )
        # 2. Trailing Stop Alert (Gained > 8%, trail stop to breakeven)
        elif pnl_pct >= 8.0:
            alerts.append(
                f"📈 <b>PROFIT TRAILING ALERT: {sym}</b>\n"
                f"Gain: <b>+{pnl_pct:.2f}%</b> (+₹{pnl:,.0f})\n"
                f"<i>Advice: Move stop-loss up to breakeven (₹{avg:.2f}) to guarantee zero risk.</i>"
            )
        # 3. Stop-Loss Breached Alert
        elif pnl_pct <= -stop_loss_pct:
            alerts.append(
                f"🚨 <b>STOP LOSS BREACHED: {sym}</b>\n"
                f"Loss: <b>{pnl_pct:.2f}%</b> (-₹{abs(pnl):,.0f})\n"
                f"Price: ₹{cur_px:,.2f} (Bought at ₹{avg:,.2f})\n"
                f"Bucket: {TIMEFRAMES.get(tf, {}).get('label', tf)}\n"
                f"<i>Advice: Consider exiting delivery position to preserve capital.</i>"
            )
        # 4. Approaching Stop-Loss
        elif pnl_pct <= -(stop_loss_pct - 2.0):
            alerts.append(
                f"⚠️ <b>NEAR STOP LOSS: {sym}</b>\n"
                f"Loss: <b>{pnl_pct:.2f}%</b> (-₹{abs(pnl):,.0f})\n"
                f"<i>Current price is within 2% of the stop-loss limit.</i>"
            )

        # 5. Tax-Smart Advisory (Indian LTCG vs STCG)
        if p_date_str:
            try:
                p_date = datetime.strptime(p_date_str[:10], "%Y-%m-%d").date()
                days_held = (today - p_date).days
                if 335 <= days_held < 365 and pnl > 0:
                    days_left = 365 - days_held
                    alerts.append(
                        f"⏳ <b>TAX SMART ADVISORY: {sym}</b>\n"
                        f"Held for {days_held} days with unrealized profit of ₹{pnl:,.0f}.\n"
                        f"<i>Waiting <b>{days_left} more days</b> qualifies for 12.5% LTCG instead of 20% STCG, saving 7.5% in tax!</i>"
                    )
            except Exception:
                pass

    # Check Active Paper Trades for real-time swing alerts
    try:
        from data.db import get_connection, get_open_paper_trades
        conn = get_connection()
        try:
            open_paper = get_open_paper_trades(conn)
        finally:
            conn.close()

        for p in open_paper:
            sym = p.get("ticker", "")
            entry = float(p.get("entry_price") or 0)
            stop = float(p.get("stop_loss") or 0)
            target = float(p.get("target_price") or 0)
            qty = int(p.get("quantity") or 1)
            if not sym or entry <= 0:
                continue
            q = fetch_live_quote(sym)
            cur = float(q.get("price") or entry)
            gain_pct = ((cur - entry) / entry * 100.0) if entry else 0.0
            pnl = (cur - entry) * qty

            if cur >= target:
                alerts.append(f"🎯 <b>PAPER TARGET HIT: {sym}</b>\nGain: <b>+{gain_pct:.2f}%</b> (+₹{pnl:,.2f})\nTarget: ₹{target:,.2f} | LTP: ₹{cur:,.2f}")
            elif gain_pct >= 7.0:
                alerts.append(f"💰 <b>PARTIAL PROFIT (+7%): {sym}</b>\nGain: <b>+{gain_pct:.2f}%</b> (+₹{pnl:,.2f})\n<i>Tiered take-profit active: Lock 50% & trail stop!</i>")
            elif cur <= stop:
                alerts.append(f"🛑 <b>PAPER STOP HIT: {sym}</b>\nLoss: <b>{gain_pct:.2f}%</b> (-₹{abs(pnl):,.2f})\nStop: ₹{stop:,.2f} | LTP: ₹{cur:,.2f}")
            elif cur <= stop * 1.015:
                alerts.append(f"⚠️ <b>NEAR STOP LOSS: {sym}</b>\nLTP: ₹{cur:,.2f} is within 1.5% of stop ₹{stop:,.2f} ({gain_pct:+.2f}%)")
    except Exception as e:
        logger.error(f"Error checking paper trade alerts: {e}")

    return alerts


def format_portfolio_status() -> str:
    """Format overall portfolio metrics for Telegram."""
    port = portfolio_summary()
    count = port.get("holdings_count", 0)
    if count == 0:
        return "📁 <b>Portfolio is currently empty.</b>\nAdd holdings or sync Kotak Neo."

    inv = port.get("total_invested", 0)
    cur = port.get("total_current_value", 0)
    pnl = port.get("total_pnl", 0)
    pnl_pct = port.get("total_pnl_percent", 0)
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"

    tf_vals = port.get("timeframe_values") or {}
    tf_wts = port.get("timeframe_weights") or {}

    msg = [
        "📊 <b>PORTFOLIO STATUS</b>",
        f"Invested: ₹{inv:,.0f}",
        f"Current Value: ₹{cur:,.0f}",
        f"Total P&L: {pnl_emoji} <b>₹{pnl:+,.0f} ({pnl_pct:+.2f}%)</b>",
        "",
        "⏳ <b>Horizon Distribution:</b>",
        f"• Long Term (3+ Yrs): ₹{tf_vals.get('long_term', 0):,.0f} ({tf_wts.get('long_term', 0)}%)",
        f"• Mid Term (1-3 Yrs): ₹{tf_vals.get('mid_term', 0):,.0f} ({tf_wts.get('mid_term', 0)}%)",
        f"• Short Term (Days-Mos): ₹{tf_vals.get('short_term', 0):,.0f} ({tf_wts.get('short_term', 0)}%)",
        "",
        "<b>Holdings:</b>",
    ]

    for h in port.get("holdings", []):
        sym = h.get("symbol")
        qty = h.get("quantity")
        cur_px = h.get("current_price", h.get("avg_price", 0))
        h_pnl_pct = h.get("pnl_percent", 0)
        emoji = "🟢" if h_pnl_pct >= 0 else "🔴"
        tf_label = TIMEFRAMES.get(h.get("timeframe", "mid_term"), {}).get("label", "")
        msg.append(f"{emoji} <b>{sym}</b>: {qty} shares @ ₹{cur_px:,.1f} ({h_pnl_pct:+.1f}%) | {tf_label}")

    return "\n".join(msg)


def format_top_picks() -> str:
    """Format top buy recommendations for Telegram."""
    from engine.pipeline import run_pipeline

    brief = run_pipeline(max_watchlist=8, persist=False, sync_broker=False)
    picks = brief.get("top_picks") or []
    if not picks:
        return "ℹ️ No clear BUY picks clearing risk & reward filters today."

    msg = ["🔥 <b>TOP RECOMMENDED PICKS</b>", ""]
    for p in picks[:5]:
        sym = p.get("ticker")
        action = p.get("action")
        score = p.get("final_score")
        price = p.get("current_price", 0)
        stop = p.get("stop_loss", 0)
        target = p.get("target_price", 0)
        rr = p.get("reward_risk", 0)
        tf = TIMEFRAMES.get(p.get("preferred_timeframe", "mid_term"), {}).get("label", "")

        msg.append(
            f"⚡ <b>{action} {sym}</b> (Score: {score})\n"
            f"• Price: ₹{price:,.1f} | Horizon: {tf}\n"
            f"• Stop: ₹{stop:,.1f} | Target: ₹{target:,.1f} (R:R {rr}:1)\n"
        )

    return "\n".join(msg)


def format_single_scan(ticker: str) -> str:
    """Deep analysis of a single stock."""
    from engine.scorer import score_stock
    from engine.recommender import build_recommendation

    ticker = ticker.strip().upper()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    try:
        score = score_stock(ticker)
        rec = build_recommendation(score)
        action = rec.get("action")
        final = rec.get("final_score")
        px = rec.get("current_price", 0)
        stop = rec.get("stop_loss", 0)
        target = rec.get("target_price", 0)
        rr = rec.get("reward_risk", 0)
        stab = rec.get("stability_score", 0)

        return (
            f"🔍 <b>ANALYSIS: {ticker}</b>\n\n"
            f"Action: <b>{action}</b> (Score: {final}/100)\n"
            f"Current Price: ₹{px:,.2f}\n"
            f"Suggested Stop: ₹{stop:,.2f} | Target: ₹{target:,.2f}\n"
            f"Reward/Risk: {rr}:1 | Stability: {stab}/100\n"
            f"Technical: {rec.get('technical_score')} | Fundamental: {rec.get('fundamental_score')}\n"
            f"News Sentiment: {rec.get('sentiment_score')} | Macro: {rec.get('macro_score')}\n\n"
            f"<i>{rec.get('action_rationale') or rec.get('reasoning')}</i>"
        )
    except Exception as e:
        return f"❌ Failed scanning {ticker}: {e}"


def format_paper_trades_status() -> str:
    """Format open paper trades and live mark-to-market P&L for Telegram."""
    from engine.paper_week import mark_to_market
    from data.db import get_connection, get_open_paper_trades

    mtm_data = mark_to_market()
    marks_map = {m["trade_id"]: m for m in (mtm_data.get("marks") or [])}

    conn = get_connection()
    try:
        open_trades = get_open_paper_trades(conn)
    finally:
        conn.close()

    if not open_trades:
        return "📁 <b>No open paper trades currently active.</b>"

    tot_unrealized = sum(float(marks_map.get(t["id"], {}).get("unrealized_pnl", 0)) for t in open_trades)
    tot_invested = sum(float(t.get("entry_price", 0)) * int(t.get("quantity", 1)) for t in open_trades)
    tot_pct = (tot_unrealized / tot_invested * 100.0) if tot_invested > 0 else 0.0
    pnl_emoji = "🟢" if tot_unrealized >= 0 else "🔴"

    lines = [
        "🛡️ <b>ACTIVE PAPER TRADES SCORECARD</b>",
        f"Open Positions: <b>{len(open_trades)} stocks</b>",
        f"Total Floating P&L: {pnl_emoji} <b>₹{tot_unrealized:+,.2f} ({tot_pct:+.2f}%)</b>",
        "",
        "<b>Current Positions:</b>",
    ]

    for t in open_trades:
        m = marks_map.get(t["id"]) or {}
        entry_px = float(t.get("entry_price") or 0)
        cur_px = float(m.get("last") or entry_px)
        qty = int(t.get("quantity") or 1)
        pnl_val = float(m.get("unrealized_pnl") or ((cur_px - entry_px) * qty))
        pnl_pct = ((cur_px - entry_px) / entry_px * 100) if entry_px else 0.0
        stop_px = float(t.get("stop_loss") or 0)
        tp_px = float(t.get("target_price") or 0)
        sym = t.get("ticker", "").replace(".NS", "")

        sym_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        trailing_tag = " 🛡️(Breakeven)" if abs(stop_px - entry_px) < 1.0 and stop_px >= entry_px else ""

        lines.append(
            f"{sym_emoji} <b>{sym}</b> ({qty} shs)\n"
            f"• Entry: ₹{entry_px:,.2f} | LTP: ₹{cur_px:,.2f}\n"
            f"• P&L: <b>₹{pnl_val:+,.2f} ({pnl_pct:+.2f}%)</b>\n"
            f"• Stop: ₹{stop_px:,.2f}{trailing_tag} | Target: ₹{tp_px:,.2f}\n"
        )

    return "\n".join(lines)


def format_tournament_status() -> str:
    """Format strategy tournament summary for Telegram."""
    from engine.strategy_tournament import simulate_tournament

    tourney = simulate_tournament(corpus=20000.0, top_n_candidates=15)
    if "error" in tourney:
        return f"⚠️ {tourney['error']}"

    strats = tourney.get("strategies", {})
    st_top3 = strats.get("top3", {})
    st_top5 = strats.get("top5", {})
    st_all = strats.get("all_buys", {})
    winner = tourney.get("best_strategy", "")

    lines = [
        "🏆 <b>MULTI-STRATEGY TOURNAMENT (₹20k)</b>",
        f"Winning Style: <b>{winner}</b>",
        "",
        f"👑 <b>Strategy A (Top 3 Concentrated)</b>:\n"
        f"• Net P&L: <b>₹{st_top3.get('net_pnl', 0):+,.2f} ({st_top3.get('net_return_pct', 0):+.2f}%)</b>\n"
        f"• Win Rate: {st_top3.get('win_rate', 0)}% | Drag: ₹{st_top3.get('friction', 0):,.2f}\n",
        f"⚖️ <b>Strategy B (Top 5 Balanced)</b>:\n"
        f"• Net P&L: <b>₹{st_top5.get('net_pnl', 0):+,.2f} ({st_top5.get('net_return_pct', 0):+.2f}%)</b>\n"
        f"• Win Rate: {st_top5.get('win_rate', 0)}% | Drag: ₹{st_top5.get('friction', 0):,.2f}\n",
        f"🌐 <b>Strategy C (All BUYs Basket)</b>:\n"
        f"• Net P&L: <b>₹{st_all.get('net_pnl', 0):+,.2f} ({st_all.get('net_return_pct', 0):+.2f}%)</b>\n"
        f"• Win Rate: {st_all.get('win_rate', 0)}% | Drag: ₹{st_all.get('friction', 0):,.2f}\n",
    ]
    return "\n".join(lines)


def handle_command(text: str, chat_id: str):
    """Process incoming commands from Telegram."""
    cmd = text.strip()
    if cmd in ("/start", "/help"):
        help_msg = (
            "🤖 <b>TraderAI Active Portfolio Bot</b>\n\n"
            "Commands:\n"
            "• /paper - Live Open Paper Trades & MTM P&L\n"
            "• /tourney - Multi-Strategy Tournament Results (₹20k)\n"
            "• /picks - Top BUY recommendations clearing gates\n"
            "• /alerts - Check trailing stop, profit & loss warnings\n"
            "• /scan TICKER - Deep analysis of any stock (e.g. <code>/scan RELIANCE</code>)\n"
            "• /portfolio - View Demat portfolio & P&L\n"
            "• /market - Current regime, Nifty trend, and holidays"
        )
        send_message(help_msg, chat_id=chat_id)
    elif cmd in ("/paper", "/trades"):
        send_message(format_paper_trades_status(), chat_id=chat_id)
    elif cmd in ("/tourney", "/tournament"):
        send_message("🏆 Calculating multi-strategy tournament across all BUYs...", chat_id=chat_id)
        send_message(format_tournament_status(), chat_id=chat_id)
    elif cmd in ("/portfolio", "/status"):
        send_message(format_portfolio_status(), chat_id=chat_id)
    elif cmd in ("/alerts", "/warnings"):
        alerts = get_portfolio_alerts()
        if alerts:
            for a in alerts:
                send_message(a, chat_id=chat_id)
        else:
            send_message("✅ <b>All holdings are healthy.</b>\nNo stop-loss breaches or trailing triggers.", chat_id=chat_id)
    elif cmd in ("/picks", "/buy"):
        send_message("🔍 Scanning market and deep-scoring candidates...", chat_id=chat_id)
        send_message(format_top_picks(), chat_id=chat_id)
    elif cmd.startswith("/scan "):
        sym = cmd.replace("/scan ", "").strip()
        send_message(f"Analyzing {sym}...", chat_id=chat_id)
        send_message(format_single_scan(sym), chat_id=chat_id)
    elif cmd in ("/market", "/timing", "/calendar"):
        from data.market_calendar import get_market_status, get_upcoming_holidays
        from analysis.macro import compute_macro_score
        s = get_market_status()
        hols = get_upcoming_holidays(limit=3)
        h_text = "\n".join([f"• <b>{h['formatted']}</b> ({h['day_name']}): {h['name']} ({h['countdown']})" for h in hols])
        m = compute_macro_score()
        obs = "\n• ".join(m.get("observations", []))
        msg = (
            f"🕒 <b>NSE/BSE STATUS: {s['badge']}</b>\n"
            f"• <i>{s['detail']}</i>\n"
            f"• <b>Current IST:</b> {s['current_time_str']}\n\n"
            f"🌐 <b>MACRO REGIME: {m.get('regime')}</b> ({m.get('score')}/100)\n• {obs}\n\n"
            f"📅 <b>Upcoming Holidays:</b>\n{h_text}"
        )
        send_message(msg, chat_id=chat_id)
    else:
        send_message("Type /help to see available commands.", chat_id=chat_id)


def run_bot_service():
    """
    Main background runner:
    1. Listens for user commands via getUpdates.
    2. Runs periodic portfolio alert checks every ALERT_CHECK_INTERVAL_MINS minutes during market hours.
    """
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not configured. Set it in .env.")
        print("Please configure TELEGRAM_BOT_TOKEN in .env.")
        return

    print("[TraderAI] Telegram Bot service started. Listening for commands...")
    last_update_id = 0
    last_alert_check = 0

    from data.market_calendar import get_market_status

    while True:
        try:
            # 1. Check for incoming user commands
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=5"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message") or {}
                    text = msg.get("text", "")
                    sender_chat_id = str((msg.get("chat") or {}).get("id") or "")
                    if text and sender_chat_id:
                        handle_command(text, sender_chat_id)

            # 2. Periodic Portfolio Alert Check (only during active market hours)
            now = time.time()
            if now - last_alert_check >= (ALERT_CHECK_INTERVAL_MINS * 60):
                last_alert_check = now
                m_stat = get_market_status()
                if m_stat.get("is_open"):
                    alerts = get_portfolio_alerts()
                    for a in alerts:
                        send_message(a)

            time.sleep(2)
        except KeyboardInterrupt:
            print("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error in bot loop: {e}")
            time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_bot_service()
