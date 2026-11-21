"""
TraderAI - Telegram Real-Time Notification Engine
Dispatches real-time, actionable trading instructions directly to user's Telegram via official Bot API:
  - GTT Breakout Triggers Filled (with exact broker GTT instructions)
  - Breakeven Locks (+5% Gain -> Stop trailed to entry)
  - Targets Hit (+12% Velocity Exit instructions)
  - Stop Losses Exited (Disciplined capital preservation)
  - 72H Velocity Kills (Dead money liquidated)

Privacy & Security:
  - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are strictly server-side environment variables.
  - Never rendered in HTML/DOM, Streamlit session state, or client-side JavaScript.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Telegram Bot API Endpoint
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Dispatches actionable trade lifecycle events to Telegram via official Bot API."""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() in ("true", "1", "yes")

        self.bot_token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id or os.getenv("TELEGRAM_CHAT_ID", "")).strip()

    def is_configured(self) -> bool:
        """Returns True if Telegram alerts are enabled and credentials provided."""
        return bool(self.enabled and self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Sends a message to the configured Telegram chat.
        Returns True on success, False otherwise.
        """
        if not self.is_configured():
            logger.debug("Telegram alert skipped: notifier is not configured or disabled.")
            return False

        url = TELEGRAM_API_URL.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status_code = resp.getcode()
                if status_code == 200:
                    logger.info("✅ Telegram alert sent successfully.")
                    return True
                else:
                    logger.warning(f"⚠️ Telegram API returned status {status_code}")
                    return False
        except Exception as e:
            logger.warning(f"Failed to dispatch Telegram alert: {e}")
            return False

    # ─── Action-Packed Broker Alerts ─────────────────────────────────────────

    def notify_live_buy_signal(
        self,
        ticker: str,
        current_price: float,
        pivot_trigger: float,
        buy_ceiling: float,
        target_price: float,
        stop_loss: float,
        shares: int,
        sector: str = "General",
        pattern: str = "INSTITUTIONAL_IGNITION",
    ) -> bool:
        """Dispatches a real-time live buy signal when a fresh institutional breakout ignites."""
        clean_ticker = ticker.replace(".NS", "")
        allocated_inr = current_price * shares
        msg = (
            f"🚨 *[LIVE BUY SIGNAL: INTRADAY BREAKOUT]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Stock:* `{clean_ticker}` ({sector})\n"
            f"⚡ *Pattern:* `{pattern}`\n"
            f"💵 *Current Price (CMP):* ₹{current_price:,.2f}\n"
            f"🟢 *Max Buy Zone:* ₹{pivot_trigger:,.2f} ➔ ₹{buy_ceiling:,.2f}\n"
            f"⚠️ _Do NOT chase if price is above ₹{buy_ceiling:,.2f}_\n"
            f"📦 *Position Sizing:* {shares:,} shares (~₹{allocated_inr:,.0f})\n"
            f"🎯 *Target (+12%):* ₹{target_price:,.2f}\n"
            f"🛑 *Stop Loss (-4%):* ₹{stop_loss:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 *EXACT ACTION IN YOUR BROKER (Zerodha/Groww/Kotak):*\n"
            f"1️⃣ Open broker ➔ Search `{clean_ticker}` ➔ Tap **Buy**.\n"
            f"2️⃣ Product: **CNC (Delivery / Cash)** | Qty: `{shares}`.\n"
            f"3️⃣ Order: Limit at `₹{min(current_price * 1.003, buy_ceiling):,.2f}` (or Market).\n"
            f"4️⃣ Once bought, set **GTT OCO Exit** (Target: `₹{target_price:,.2f}`, Stop: `₹{stop_loss:,.2f}`)."
        )
        return self.send_message(msg)

    def notify_breakout_fill(
        self,
        ticker: str,
        fill_price: float,
        target_price: float,
        stop_loss: float,
        shares: int,
        strategy_track: str = "Track B (GTT Breakout)",
        sector: str = "General",
        pattern: str = "PIVOT_BREAKOUT",
    ) -> bool:
        """Dispatches an alert when a pending GTT breakout trigger fires during market hours."""
        clean_ticker = ticker.replace(".NS", "")
        allocated_inr = fill_price * shares
        msg = (
            f"🎯 *[GTT BREAKOUT EXECUTED: BUY CONFIRMED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Stock:* `{clean_ticker}` ({sector})\n"
            f"⚡ *Track:* {strategy_track}\n"
            f"💵 *Fill Price:* ₹{fill_price:,.2f}\n"
            f"📦 *Position Sizing:* {shares:,} shares (~₹{allocated_inr:,.0f})\n"
            f"🎯 *Target (+12%):* ₹{target_price:,.2f}\n"
            f"🛑 *Stop Loss (-4%):* ₹{stop_loss:,.2f}\n"
            f"🔍 *Pattern:* `{pattern}`\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 *EXACT ACTION IN YOUR BROKER (Zerodha/Groww/Kotak):*\n"
            f"1️⃣ Verify your Buy fill in **Order Book / Positions** under **CNC (Delivery)**.\n"
            f"2️⃣ Immediately place your **GTT OCO Exit Order**:\n"
            f"   • *Target:* Sell Limit at `₹{target_price:,.2f}`\n"
            f"   • *Stop Loss:* Sell Trigger at `₹{stop_loss:,.2f}` (Limit `₹{round(stop_loss * 0.995, 2):,.2f}`)\n"
            f"   • *Quantity:* `{shares}` shares\n"
            f"3️⃣ Tap **Submit GTT** — your exit is now 100% automated!"
        )
        return self.send_message(msg)

    def notify_breakeven_lock(
        self,
        ticker: str,
        entry_price: float,
        current_price: float,
        pnl_pct: float,
        new_stop_loss: float,
    ) -> bool:
        """Dispatches an alert when a trade touches +5.0% and stop is trailed to breakeven."""
        clean_ticker = ticker.replace(".NS", "")
        msg = (
            f"🛡️ *[BREAKEVEN STOP LOCKED: RISK ELIMINATED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Stock:* `{clean_ticker}` reached *+{pnl_pct:.2f}%* gain!\n"
            f"💵 *Entry:* ₹{entry_price:,.2f} ➔ *Current:* ₹{current_price:,.2f}\n"
            f"🔒 *New Trailed Stop:* `₹{new_stop_loss:,.2f}` *(Entry + 0.3% friction)*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 *EXACT ACTION IN YOUR BROKER:*\n"
            f"1️⃣ Open your broker app (Zerodha / Groww / Kotak).\n"
            f"2️⃣ Go to **GTT Orders** $\\rightarrow$ select `{clean_ticker}`.\n"
            f"3️⃣ Tap **Modify** $\\rightarrow$ change Stop-Loss trigger to `₹{new_stop_loss:,.2f}`.\n"
            f"4️⃣ Tap **Save**.\n"
            f"✨ *Capital is now 100% protected. This trade CANNOT lose money.*"
        )
        return self.send_message(msg)

    def notify_target_hit(
        self,
        ticker: str,
        entry_price: float,
        exit_price: float,
        pnl_rupees: float,
        pnl_pct: float,
    ) -> bool:
        """Dispatches an alert when a position hits its target price."""
        clean_ticker = ticker.replace(".NS", "")
        msg = (
            f"🚀 *[TARGET HIT: +12% PROFIT BOOKED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 *Stock:* `{clean_ticker}`\n"
            f"💰 *Net Profit:* *+₹{pnl_rupees:+,.2f}* (*{pnl_pct:+.2f}%*)\n"
            f"💵 *Entry:* ₹{entry_price:,.2f} ➔ *Exit:* ₹{exit_price:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 *EXACT ACTION IN YOUR BROKER:*\n"
            f"1️⃣ Check **Order Book** — your Target GTT should have executed.\n"
            f"2️⃣ If not auto-sold, tap `{clean_ticker}` $\\rightarrow$ **Sell CNC at Market**.\n"
            f"3️⃣ Cancel any remaining pending Stop-Loss GTT order.\n"
            f"⚡ *Cash is freed up for the next high-velocity setup!*"
        )
        return self.send_message(msg)

    def notify_stop_loss_hit(
        self,
        ticker: str,
        entry_price: float,
        exit_price: float,
        loss_inr: float,
        loss_pct: float,
        is_breakeven: bool = False,
    ) -> bool:
        """Dispatches an alert when a stop-loss is hit."""
        clean_ticker = ticker.replace(".NS", "")
        if is_breakeven:
            headline = "🔒 *[BREAKEVEN EXIT: ZERO LOSS ACCORDING TO PLAN]*"
            subtext = "Capital safely preserved with zero loss."
        else:
            headline = "🛑 *[STOP LOSS EXECUTED: CAPITAL DEFENDED]*"
            subtext = "Small disciplined cut to preserve dry powder."

        msg = (
            f"{headline}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📉 *Stock:* `{clean_ticker}`\n"
            f"💵 *Entry:* ₹{entry_price:,.2f} ➔ *Exit:* ₹{exit_price:,.2f}\n"
            f"📊 *Net Result:* ₹{loss_inr:+,.2f} ({loss_pct:+.2f}%)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 *EXACT ACTION IN YOUR BROKER:*\n"
            f"1️⃣ Confirm position is closed in **Holdings**.\n"
            f"2️⃣ Cancel any active Target GTT order for `{clean_ticker}`.\n"
            f"🛡️ _{subtext}_"
        )
        return self.send_message(msg)

    def notify_velocity_kill(
        self,
        ticker: str,
        entry_price: float,
        exit_price: float,
        days_held: int,
        pnl_pct: float,
        freed_capital_inr: float,
    ) -> bool:
        """Dispatches an alert when a trade is closed after 72 hours of dead money."""
        clean_ticker = ticker.replace(".NS", "")
        msg = (
            f"⏳ *[72H VELOCITY KILL: DEAD MONEY EXITED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ *Stock:* `{clean_ticker}` held for {days_held} sessions\n"
            f"📊 *Performance:* {pnl_pct:+.2f}% (Failed to gain > +1.5% momentum)\n"
            f"💵 *Exit Price:* ₹{exit_price:,.2f}\n"
            f"🔓 *Freed Capital:* ~₹{freed_capital_inr:,.0f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 *EXACT ACTION IN YOUR BROKER:*\n"
            f"1️⃣ Tap `{clean_ticker}` in **Holdings** $\\rightarrow$ **Sell CNC at Market**.\n"
            f"2️⃣ Cancel any pending GTT triggers for `{clean_ticker}`.\n"
            f"⚡ *Reallocating freed capital into active high-velocity leaders.*"
        )
        return self.send_message(msg)

    def notify_daily_recap(
        self,
        summary: dict,
    ) -> bool:
        """Dispatches an end-of-day trading recap to Telegram."""
        o2 = summary.get("option_2", {})
        o3 = summary.get("option_3", {})
        oc = summary.get("track_c", {})
        msg = (
            f"📊 *[NSE MARKET CLOSE: DAILY PERFORMANCE RECAP]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Tournament Leader:* {summary.get('winner', 'Evaluating')}\n\n"
            f"🟢 *Track A (9:20 Open):* ₹{o2.get('total_pnl_inr', 0.0):+,.0f} ({o2.get('total_pnl_pct', 0.0):+.2f}%)\n"
            f"   • Active: {o2.get('open_count', 0)} open | Win Rate: {o2.get('win_rate', 0.0):.1f}%\n"
            f"🔵 *Track B (GTT Option 3):* ₹{o3.get('total_pnl_inr', 0.0):+,.0f} ({o3.get('total_pnl_pct', 0.0):+.2f}%)\n"
            f"   • Active: {o3.get('open_count', 0)} open | Pending: {o3.get('pending_count', 0)}\n"
            f"⚡ *Track C (Benchmark):* ₹{oc.get('total_pnl_inr', 0.0):+,.0f} ({oc.get('total_pnl_pct', 0.0):+.2f}%)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"✨ _Session closed. State saved & synced to dashboard._"
        )
        return self.send_message(msg)


# Global default instance
default_telegram_notifier = TelegramNotifier()
