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

    def notify_t1_harvest(
        self,
        ticker: str,
        entry_price: float,
        harvest_price: float,
        sold_shares: int,
        rem_shares: int,
        realized_pnl: float,
        new_stop: float,
        strategy_track: str = "Track B (Algo 1)",
    ) -> bool:
        """Dispatches an alert when a position hits +5.0% and banks 50% partial profit."""
        clean_ticker = ticker.replace(".NS", "")
        msg = (
            f"💰 *[T1 PROFIT BANKED: 50% POSITION SOLD]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Stock:* `{clean_ticker}` hit *+5.0%* T1 Target!\n"
            f"⚡ *Track:* {strategy_track}\n"
            f"💵 *Harvest Price:* ₹{harvest_price:,.2f} (Entry: ₹{entry_price:,.2f})\n"
            f"📦 *Shares Sold:* {sold_shares:,} shares | *Remaining:* {rem_shares:,} shares\n"
            f"💸 *Realized Cash Profit:* *+₹{realized_pnl:+,.2f}* (Banked immediately)\n"
            f"🛡️ *New Trailed Stop:* `₹{new_stop:,.2f}` *(Breakeven + 0.6% friction cushion)*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 *EXACT ACTION IN YOUR BROKER:*\n"
            f"1️⃣ Go to **Positions** ➔ Sell `{sold_shares}` shares of `{clean_ticker}` at market/limit.\n"
            f"2️⃣ Go to **GTT Orders** ➔ Modify Stop-Loss trigger on remaining `{rem_shares}` shares to `₹{new_stop:,.2f}`.\n"
            f"✨ *Capital is 100% protected. The remaining position is now a risk-free free-roll toward +12%!*"
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
        strategy_track: str = "",
    ) -> bool:
        """Dispatches an alert when a position hits its target price."""
        clean_ticker = ticker.replace(".NS", "")
        track_line = f"⚡ *Track:* {strategy_track}\n" if strategy_track else ""
        msg = (
            f"🚀 *[TARGET HIT: +12% PROFIT BOOKED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 *Stock:* `{clean_ticker}`\n"
            f"{track_line}"
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
        strategy_track: str = "",
    ) -> bool:
        """Dispatches an alert when a stop-loss is hit."""
        clean_ticker = ticker.replace(".NS", "")
        track_line = f"⚡ *Track:* {strategy_track}\n" if strategy_track else ""
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
            f"{track_line}"
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
        strategy_track: str = "",
    ) -> bool:
        """Dispatches an alert when a trade is closed after 72 hours of dead money."""
        clean_ticker = ticker.replace(".NS", "")
        track_line = f"⚡ *Track:* {strategy_track}\n" if strategy_track else ""
        msg = (
            f"⏳ *[72H VELOCITY KILL: DEAD MONEY EXITED]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ *Stock:* `{clean_ticker}` held for {days_held} sessions\n"
            f"{track_line}"
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
        """Dispatches an end-of-day trading recap to Telegram across all 9 tournament tracks."""
        t1 = summary.get("track_algo4", summary.get("track_1", {}))
        t2 = summary.get("option_3", summary.get("track_2", {}))
        t3 = summary.get("track_algo5", summary.get("track_3", {}))
        t4 = summary.get("option_2", summary.get("track_4", {}))
        t5 = summary.get("track_c", summary.get("track_5", {}))
        t6 = summary.get("track_apex_compounder", summary.get("track_6", {}))
        t7 = summary.get("track_conviction_2slot", summary.get("track_7", {}))
        t8 = summary.get("track_apex_1slot", summary.get("track_8", {}))
        t9 = summary.get("track_monthly_swing", summary.get("track_9", {}))

        def _line(badge: str, label: str, d: dict, detail: bool = True) -> str:
            s = f"{badge} *{label}:* ₹{d.get('total_pnl_inr', 0.0):+,.0f} ({d.get('total_pnl_pct', 0.0):+.2f}%)\n"
            if detail:
                s += f"   • Open: {d.get('open_count', 0)} | Closed: {d.get('closed_count', 0)} | Pend: {d.get('pending_count', 0)} | WR: {d.get('win_rate', 0.0):.1f}%\n"
            return s

        msg = (
            f"📊 *[NSE MARKET CLOSE: 9-WAY PERFORMANCE RECAP]*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Leader:* {summary.get('winner', 'Evaluating')}\n\n"
            + _line("💎", "Track 6 (Apex 3-Slot)", t6)
            + _line("🔥", "Track 7 (2-Slot Conviction)", t7)
            + _line("👑", "Track 8 (1-Slot Rocket)", t8)
            + _line("🌊", "Track 9 (Active Swing)", t9)
            + _line("🥇", "Track 1 (Algo 4: 20-EMA)", t1)
            + _line("🚀", "Track 2 (Algo 1: Ignition)", t2)
            + _line("⚡", "Track 3 (Algo 5: 52W Blast)", t3)
            + _line("🛡️", "Track 4 (Algo 2: VCP Bench)", t4, detail=False)
            + _line("🎯", "Track 5 (Algo 3: Sniper Bench)", t5, detail=False)
            + f"━━━━━━━━━━━━━━━━━━━\n"
            f"✨ _Session closed. State saved & synced across all 9 tracks._"
        )
        return self.send_message(msg)


# Global default instance
default_telegram_notifier = TelegramNotifier()
