"""
TraderAI - Telegram Real-Time Notification Engine
Dispatches real-time trading alerts directly to user's Telegram via official Bot API:
  - GTT Breakout Triggers Filled
  - Breakeven Locks (+5% Gain -> Stop trailed to entry)
  - Targets Hit (+12% Velocity Exit)
  - Stop Losses Exited
  - 72H Velocity Kills (Dead money liquidated)

Privacy & Security:
  - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are strictly server-side environment variables.
  - Never rendered in HTML/DOM, Streamlit session state, or client-side JavaScript.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
import json
from typing import Optional

logger = logging.getLogger(__name__)

# Telegram Bot API Endpoint
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Dispatches trade lifecycle events to Telegram via official Bot API."""

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

    # ─── Specialized Trading Alerts ──────────────────────────────────────────

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
            f"🎯 *[GTT BREAKOUT EXECUTED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Stock:* `{clean_ticker}` ({sector})\n"
            f"⚡ *Track:* {strategy_track}\n"
            f"💵 *Fill Price:* ₹{fill_price:,.2f}\n"
            f"📦 *Position:* {shares:,} shares (~₹{allocated_inr:,.0f})\n"
            f"🎯 *Target (+12%):* ₹{target_price:,.2f}\n"
            f"🛑 *Stop Loss (-4%):* ₹{stop_loss:,.2f}\n"
            f"🔍 *Pattern:* `{pattern}`\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ _Delivery/CNC Cash Equity - Zero Leverage_"
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
            f"🛡️ *[BREAKEVEN STOP LOCKED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Stock:* `{clean_ticker}`\n"
            f"🚀 *Gain Touched:* +{pnl_pct:.2f}%\n"
            f"💵 *Entry:* ₹{entry_price:,.2f} ➔ *Cur:* ₹{current_price:,.2f}\n"
            f"🔒 *New Stop Loss:* ₹{new_stop_loss:,.2f} *(Entry + 0.3% friction)*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"✨ _Risk is now ELIMINATED. Guaranteed zero-loss runner._"
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
            f"🚀 *[TARGET HIT - PROFIT BOOKED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 *Stock:* `{clean_ticker}`\n"
            f"💰 *Net Profit:* +₹{pnl_rupees:+,.2f} (+{pnl_pct:+.2f}%)\n"
            f"💵 *Entry:* ₹{entry_price:,.2f} ➔ *Exit:* ₹{exit_price:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Capital freed for the next high-velocity setup._"
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
            headline = "🔒 *[BREAKEVEN EXIT - CAPITAL PROTECTED]*"
            subtext = "Capital safely preserved with zero loss."
        else:
            headline = "🛑 *[STOP LOSS EXECUTED]*"
            subtext = "Disciplined capital preservation exit."

        msg = (
            f"{headline}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📉 *Stock:* `{clean_ticker}`\n"
            f"💵 *Entry:* ₹{entry_price:,.2f} ➔ *Exit:* ₹{exit_price:,.2f}\n"
            f"📊 *Net Result:* ₹{loss_inr:+,.2f} ({loss_pct:+.2f}%)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
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
            f"⏳ *[72H VELOCITY KILL - DEAD MONEY EXITED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ *Stock:* `{clean_ticker}` held for {days_held} sessions\n"
            f"📊 *Performance:* {pnl_pct:+.2f}% (Below velocity threshold +1.5%)\n"
            f"💵 *Exit Price:* ₹{exit_price:,.2f}\n"
            f"🔓 *Freed Capital:* ~₹{freed_capital_inr:,.0f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Reallocating capital to active explosive breakouts._"
        )
        return self.send_message(msg)


# Global default instance
default_telegram_notifier = TelegramNotifier()
