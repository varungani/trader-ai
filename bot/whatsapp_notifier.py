"""
TraderAI - WhatsApp Real-Time Notification Engine
Delivers real-time execution alerts (Buy fills, Breakeven locks, Target hits, Stop exits, and 72H velocity kills)
to your personal WhatsApp via open-source friendly community gateways (CallMeBot), self-hosted webhooks (Evolution API/Baileys), or Twilio.
"""
from __future__ import annotations

import logging
import os
import sys
import urllib.parse
from typing import Optional, Dict, Any
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    WHATSAPP_ENABLED,
    WHATSAPP_PROVIDER,
    WHATSAPP_PHONE,
    WHATSAPP_APIKEY,
    WHATSAPP_WEBHOOK_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
)

logger = logging.getLogger("WhatsAppNotifier")


class WhatsAppNotifier:
    """
    Modular WhatsApp notification service supporting:
      1. CallMeBot (100% Free Open-Source Community Gateway)
      2. Self-Hosted Webhook (Evolution API, Baileys, WPPConnect)
      3. Twilio Cloud API
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        provider: Optional[str] = None,
        phone: Optional[str] = None,
        apikey: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ):
        self.enabled = enabled if enabled is not None else WHATSAPP_ENABLED
        self.provider = (provider or WHATSAPP_PROVIDER or "callmebot").lower()
        self.phone = phone or WHATSAPP_PHONE
        self.apikey = apikey or WHATSAPP_APIKEY
        self.webhook_url = webhook_url or WHATSAPP_WEBHOOK_URL

    def _normalize_phone(self, phone_str: str) -> str:
        """Strip spaces, dashes, parentheses and ensure country code format."""
        digits = "".join(ch for ch in str(phone_str) if ch.isdigit() or ch == "+")
        if not digits.startswith("+") and len(digits) == 10:
            digits = "+91" + digits  # Default Indian mobile prefix if 10 digits
        return digits

    def send_message(self, text: str) -> bool:
        """
        Send a plain-text or emoji-formatted message to WhatsApp.
        Returns True if successfully dispatched, False otherwise.
        """
        if not self.enabled:
            logger.debug("WhatsApp notifications disabled in config.")
            return False

        if not text:
            return False

        try:
            if self.provider == "callmebot":
                return self._send_callmebot(text)
            elif self.provider in ("webhook", "evolution", "baileys"):
                return self._send_webhook(text)
            elif self.provider == "twilio":
                return self._send_twilio(text)
            else:
                logger.warning(f"Unknown WhatsApp provider: {self.provider}. Defaulting to callmebot.")
                return self._send_callmebot(text)
        except Exception as e:
            logger.error(f"Failed to send WhatsApp alert: {e}")
            return False

    def _send_callmebot(self, text: str) -> bool:
        """
        CallMeBot free community gateway:
        GET https://api.callmebot.com/whatsapp.php?phone=[phone]&text=[text]&apikey=[apikey]
        """
        if not self.phone or not self.apikey:
            logger.warning("CallMeBot phone number or apikey missing. Set WHATSAPP_PHONE and WHATSAPP_APIKEY.")
            return False

        clean_phone = self._normalize_phone(self.phone)
        encoded_text = urllib.parse.quote_plus(text)
        url = f"https://api.callmebot.com/whatsapp.php?phone={clean_phone}&text={encoded_text}&apikey={self.apikey}"

        resp = requests.get(url, timeout=12)
        if resp.status_code == 200 and "error" not in resp.text.lower():
            logger.info("✅ WhatsApp alert sent successfully via CallMeBot.")
            return True
        else:
            logger.warning(f"CallMeBot dispatch responded with code {resp.status_code}: {resp.text[:120]}")
            return False

    def _send_webhook(self, text: str) -> bool:
        """
        Self-hosted open source gateway (Evolution API, Baileys Docker, etc.):
        POST to WHATSAPP_WEBHOOK_URL with JSON payload.
        """
        if not self.webhook_url:
            logger.warning("WhatsApp webhook URL missing. Set WHATSAPP_WEBHOOK_URL.")
            return False

        clean_phone = self._normalize_phone(self.phone)
        payload = {
            "number": clean_phone,
            "recipient": clean_phone,
            "text": text,
            "message": text,
        }
        resp = requests.post(self.webhook_url, json=payload, timeout=10)
        return resp.status_code in (200, 201)

    def _send_twilio(self, text: str) -> bool:
        """Official Twilio WhatsApp Sandbox REST API."""
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            logger.warning("Twilio credentials missing. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
            return False

        clean_phone = self._normalize_phone(self.phone)
        to_number = f"whatsapp:{clean_phone}" if not clean_phone.startswith("whatsapp:") else clean_phone
        from_number = TWILIO_WHATSAPP_NUMBER

        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
        data = {
            "From": from_number,
            "To": to_number,
            "Body": text,
        }
        resp = requests.post(url, data=data, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=12)
        return resp.status_code in (200, 201)

    # ─────────────────────────────────────────────────────────────────────────
    # Actionable Trading Event Alert Formatters
    # ─────────────────────────────────────────────────────────────────────────

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
        """Alert triggered when a GTT buy-stop order fires during live market hours."""
        clean_tick = ticker.replace(".NS", "")
        allocated_inr = fill_price * shares
        msg = (
            f"🚨 *TRADER-AI EXECUTION ALERT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Action*: BOUGHT (CNC Delivery)\n"
            f"🎯 *Stock*: {clean_tick} ({sector})\n"
            f"⚡ *Strategy*: {strategy_track}\n"
            f"💵 *Fill Price*: ₹{fill_price:,.2f}\n"
            f"📦 *Quantity*: {shares} shares (₹{allocated_inr:,.0f})\n"
            f"🎯 *Target (+12%)*: ₹{target_price:,.2f}\n"
            f"🛑 *Base Stop (-4%)*: ₹{stop_loss:,.2f}\n"
            f"📊 *Pattern*: {pattern}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Next*: Place Sell OCO GTT on Zerodha/Kotak with Target & Stop above."
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
        """Alert when position hits +5.0% and stop is trailed to entry to eliminate risk."""
        clean_tick = ticker.replace(".NS", "")
        msg = (
            f"🛡️ *BREAKEVEN LOCK ENGAGED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 *Stock*: {clean_tick} is up *{pnl_pct:+.2f}%*!\n"
            f"💵 *Entry Px*: ₹{entry_price:,.2f} ➔ *Current*: ₹{current_price:,.2f}\n"
            f"🔒 *New Stop Loss*: ₹{new_stop_loss:,.2f} (Entry + 0.3% friction lock)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎉 *Downside Risk Slashed to ZERO!*\n"
            f"Worst case: exit flat with ₹0 loss. Upside open to +12.0% target."
        )
        return self.send_message(msg)

    def notify_partial_profit(
        self,
        ticker: str,
        entry_price: float,
        current_price: float,
        shares_sold: int,
        booked_inr: float,
        remaining_shares: int,
    ) -> bool:
        """Alert when twin-bullet 50% profit is taken at +6.0%."""
        clean_tick = ticker.replace(".NS", "")
        gain_pct = ((current_price - entry_price) / entry_price) * 100.0
        msg = (
            f"💰 *PARTIAL PROFIT BOOKED (Twin-Bullet)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Stock*: {clean_tick} gained *{gain_pct:+.2f}%*\n"
            f"🏦 *Action*: Sold 50% ({shares_sold} shares) @ ₹{current_price:,.2f}\n"
            f"💵 *Realized Cash Banked*: +₹{booked_inr:,.0f}\n"
            f"🏃 *Remaining Position*: {remaining_shares} shares riding to +12.0% target!\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Recycled capital is ready for the next breakout trigger."
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
        """Alert when +12.0% velocity target is hit."""
        clean_tick = ticker.replace(".NS", "")
        msg = (
            f"🎯 *TARGET HIT — TRADE COMPLETED!*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Stock*: {clean_tick}\n"
            f"💵 *Entry*: ₹{entry_price:,.2f} ➔ *Exit*: ₹{exit_price:,.2f}\n"
            f"🚀 *Net Gain*: *{pnl_pct:+.2f}%*\n"
            f"💰 *Net Profit*: *+₹{pnl_rupees:,.0f}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Slot is freed up. Capital returned to cash balance for next runner."
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
        """Alert when stop loss or breakeven lock is triggered."""
        clean_tick = ticker.replace(".NS", "")
        status_label = "🛡️ Breakeven Protection Exit" if is_breakeven else "🛑 Capital Preservation Stop Hit"
        msg = (
            f"⚠️ *{status_label}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📉 *Stock*: {clean_tick}\n"
            f"💵 *Entry*: ₹{entry_price:,.2f} ➔ *Exit*: ₹{exit_price:,.2f}\n"
            f"📊 *Result*: {loss_pct:+.2f}% (₹{loss_inr:,.0f})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Discipline enforced. Capital protected for fresh opportunities."
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
        """Alert when a stock is killed after 3 sessions of dead money."""
        clean_tick = ticker.replace(".NS", "")
        msg = (
            f"⏱️ *72-HOUR VELOCITY GATE (Dead Money Kill)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🐌 *Stock*: {clean_tick} held for {days_held} sessions (PnL: {pnl_pct:+.2f}%)\n"
            f"⚡ *Action*: Exited flat @ ₹{exit_price:,.2f}\n"
            f"🔓 *Freed Capital*: ₹{freed_capital_inr:,.0f} released instantly\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Capital rotation active: Moving into high-momentum ignition candidates."
        )
        return self.send_message(msg)

    def notify_daily_summary(self, summary: Dict[str, Any]) -> bool:
        """Daily portfolio recap at 03:45 PM after market close."""
        o2 = summary.get("option_2", {})
        o3 = summary.get("option_3", {})
        msg = (
            f"📊 *TRADER-AI DAILY MARKET CLOSE SUMMARY*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Leader*: {summary.get('winner', 'Evaluating')}\n"
            f"\n"
            f"🔵 *Track B (GTT Breakouts)*:\n"
            f"  • P&L: ₹{o3.get('total_pnl_inr', 0):+,.0f} ({o3.get('total_pnl_pct', 0):+.2f}%)\n"
            f"  • Active Positions: {o3.get('open_count', 0)} open\n"
            f"  • Pending Triggers: {o3.get('pending_count', 0)} waiting\n"
            f"\n"
            f"🟢 *Track A (9:20 AM Confirmation)*:\n"
            f"  • P&L: ₹{o2.get('total_pnl_inr', 0):+,.0f} ({o2.get('total_pnl_pct', 0):+.2f}%)\n"
            f"  • Active Positions: {o2.get('open_count', 0)} open\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Next session orders queued for 09:15 AM open."
        )
        return self.send_message(msg)


# Global singleton instance
default_notifier = WhatsAppNotifier()
