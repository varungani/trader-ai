"""
TraderAI - Indian Stock Market Calendar & Trading Hours Engine
Tracks NSE/BSE trading sessions, live market status, working days, weekends, and official holidays.
Timezone: Asia/Kolkata (IST - UTC+5:30)
Market Hours: 09:15 AM to 03:30 PM IST (Mon-Fri)
"""
from __future__ import annotations

import logging
from datetime import datetime, date, time as dtime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# NSE/BSE Standard Session Timings
PRE_OPEN_START = dtime(9, 0)      # 09:00 AM IST
PRE_OPEN_END = dtime(9, 15)       # 09:15 AM IST
NORMAL_MARKET_OPEN = dtime(9, 15) # 09:15 AM IST
NORMAL_MARKET_CLOSE = dtime(15, 30) # 03:30 PM IST
POST_MARKET_START = dtime(15, 40) # 03:40 PM IST
POST_MARKET_END = dtime(16, 0)    # 04:00 PM IST

# Official NSE / BSE Trading Holidays (2025 & 2026)
# Format: 'YYYY-MM-DD': 'Holiday Name'
NSE_HOLIDAYS: dict[str, str] = {
    # 2025
    "2025-01-26": "Republic Day",
    "2025-02-26": "Mahashivratri",
    "2025-03-14": "Holi",
    "2025-03-31": "Id-Ul-Fitr (Ramzan Id)",
    "2025-04-10": "Mahavir Jayanti",
    "2025-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2025-04-18": "Good Friday",
    "2025-05-01": "Maharashtra Day",
    "2025-06-07": "Bakri Id (Id-Ul-Zuha)",
    "2025-08-15": "Independence Day",
    "2025-08-27": "Ganesh Chaturthi",
    "2025-10-02": "Mahatma Gandhi Jayanti",
    "2025-10-21": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2025-10-22": "Diwali Balipratipada",
    "2025-11-05": "Guru Nanak Jayanti",
    "2025-12-25": "Christmas",

    # 2026
    "2026-01-26": "Republic Day",
    "2026-02-15": "Mahashivratri",
    "2026-03-03": "Holi",
    "2026-03-20": "Id-Ul-Fitr (Ramzan Id)",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-27": "Bakri Id (Eid-Ul-Adha)",
    "2026-08-15": "Independence Day",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}


def get_ist_now() -> datetime:
    """Returns current datetime in Indian Standard Time (Asia/Kolkata)."""
    return datetime.now(IST)


def is_trading_holiday(dt: Optional[datetime | date] = None) -> tuple[bool, Optional[str]]:
    """
    Checks if a given date is an official NSE trading holiday.
    Returns: (is_holiday, holiday_name)
    """
    if dt is None:
        dt = get_ist_now().date()
    elif isinstance(dt, datetime):
        dt = dt.astimezone(IST).date()

    date_str = dt.strftime("%Y-%m-%d")
    if date_str in NSE_HOLIDAYS:
        return True, NSE_HOLIDAYS[date_str]
    return False, None


def is_trading_day(dt: Optional[datetime | date] = None) -> tuple[bool, str]:
    """
    Checks if a given date is a working trading day (Monday to Friday, not a holiday).
    Returns: (is_trading_day, reason_or_status)
    """
    if dt is None:
        dt = get_ist_now().date()
    elif isinstance(dt, datetime):
        dt = dt.astimezone(IST).date()

    weekday = dt.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
    if weekday == 5:
        return False, "Saturday (Weekend Closed)"
    if weekday == 6:
        return False, "Sunday (Weekend Closed)"

    is_holiday, name = is_trading_holiday(dt)
    if is_holiday:
        return False, f"NSE Holiday: {name}"

    return True, "Trading Day"


def get_next_trading_day(from_date: Optional[date] = None) -> tuple[date, str]:
    """Finds the next upcoming working trading day."""
    cur = from_date or get_ist_now().date()
    cur += timedelta(days=1)
    while True:
        is_td, reason = is_trading_day(cur)
        if is_td:
            return cur, cur.strftime("%A, %d %b %Y")
        cur += timedelta(days=1)


def get_market_status(dt: Optional[datetime] = None) -> dict:
    """
    Comprehensive real-time status of Indian Stock Market (NSE/BSE).
    Returns status code, is_open flag, human-readable messages, badges, and countdowns.
    """
    now = dt or get_ist_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    today = now.date()
    cur_time = now.time()

    is_td, day_reason = is_trading_day(today)

    if not is_td:
        # Weekend or Holiday
        next_date, next_date_str = get_next_trading_day(today)
        next_open_dt = datetime.combine(next_date, NORMAL_MARKET_OPEN, tzinfo=IST)
        diff = next_open_dt - now
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        badge_type = "🟡 HOLIDAY" if "Holiday" in day_reason else "🔴 WEEKEND"
        return {
            "status": "HOLIDAY" if "Holiday" in day_reason else "WEEKEND",
            "is_open": False,
            "badge": f"{badge_type} · {day_reason}",
            "color": "warning" if "Holiday" in day_reason else "secondary",
            "message": f"Market Closed ({day_reason})",
            "detail": f"Next trading session opens on {next_date_str} at 09:15 AM IST (in {hours}h {minutes}m).",
            "current_time_str": now.strftime("%I:%M:%S %p IST, %a %d %b %Y"),
            "next_open_str": f"{next_date_str} at 09:15 AM IST",
            "countdown": f"{hours}h {minutes}m",
            "trading_day": False,
        }

    # Today is a regular trading day (Monday - Friday)
    if cur_time < PRE_OPEN_START:
        # Before 09:00 AM
        open_dt = datetime.combine(today, NORMAL_MARKET_OPEN, tzinfo=IST)
        diff = open_dt - now
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        return {
            "status": "PRE_SESSION",
            "is_open": False,
            "badge": "⏳ MARKET CLOSED",
            "color": "secondary",
            "message": "Market Closed (Pre-Session)",
            "detail": f"Pre-open begins at 09:00 AM. Normal trading opens at 09:15 AM IST (in {hours}h {minutes}m).",
            "current_time_str": now.strftime("%I:%M:%S %p IST, %a %d %b %Y"),
            "next_open_str": "Today at 09:15 AM IST",
            "countdown": f"{hours}h {minutes}m",
            "trading_day": True,
        }

    elif PRE_OPEN_START <= cur_time < PRE_OPEN_END:
        # 09:00 AM to 09:15 AM
        open_dt = datetime.combine(today, NORMAL_MARKET_OPEN, tzinfo=IST)
        diff = open_dt - now
        minutes = int(diff.total_seconds() // 60)
        return {
            "status": "PRE_MARKET",
            "is_open": False,
            "badge": "🟠 PRE-MARKET OPEN",
            "color": "warning",
            "message": "Pre-Market Session Active (09:00 - 09:15 AM)",
            "detail": f"Order accumulation & price discovery. Normal trading begins in {minutes} minutes.",
            "current_time_str": now.strftime("%I:%M:%S %p IST, %a %d %b %Y"),
            "next_open_str": "Today at 09:15 AM IST",
            "countdown": f"{minutes}m",
            "trading_day": True,
        }

    elif NORMAL_MARKET_OPEN <= cur_time < NORMAL_MARKET_CLOSE:
        # 09:15 AM to 03:30 PM (LIVE MARKET)
        close_dt = datetime.combine(today, NORMAL_MARKET_CLOSE, tzinfo=IST)
        diff = close_dt - now
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        return {
            "status": "OPEN",
            "is_open": True,
            "badge": "🟢 LIVE MARKET OPEN",
            "color": "success",
            "message": "Indian Market (NSE/BSE) is LIVE",
            "detail": f"Continuous trading session active. Market closes at 03:30 PM IST ({hours}h {minutes}m remaining).",
            "current_time_str": now.strftime("%I:%M:%S %p IST, %a %d %b %Y"),
            "next_close_str": "Today at 03:30 PM IST",
            "countdown": f"{hours}h {minutes}m left",
            "trading_day": True,
        }

    elif NORMAL_MARKET_CLOSE <= cur_time < POST_MARKET_END:
        # 03:30 PM to 04:00 PM
        return {
            "status": "POST_MARKET",
            "is_open": False,
            "badge": "🟣 POST-MARKET CLOSING",
            "color": "secondary",
            "message": "Market Closed (Post-Market Session)",
            "detail": "Normal trading has ended for today. Closing prices settling.",
            "current_time_str": now.strftime("%I:%M:%S %p IST, %a %d %b %Y"),
            "next_open_str": "Tomorrow at 09:15 AM IST",
            "countdown": "Closed",
            "trading_day": True,
        }

    else:
        # After 04:00 PM
        next_date, next_date_str = get_next_trading_day(today)
        next_open_dt = datetime.combine(next_date, NORMAL_MARKET_OPEN, tzinfo=IST)
        diff = next_open_dt - now
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        return {
            "status": "CLOSED",
            "is_open": False,
            "badge": "🔴 MARKET CLOSED",
            "color": "secondary",
            "message": "Market Closed for the Day",
            "detail": f"Next trading session opens on {next_date_str} at 09:15 AM IST (in {hours}h {minutes}m).",
            "current_time_str": now.strftime("%I:%M:%S %p IST, %a %d %b %Y"),
            "next_open_str": f"{next_date_str} at 09:15 AM IST",
            "countdown": f"{hours}h {minutes}m",
            "trading_day": True,
        }


def get_upcoming_holidays(limit: int = 8) -> list[dict]:
    """Returns a list of upcoming official NSE holidays relative to today."""
    today = get_ist_now().date()
    upcoming = []
    for dt_str, name in sorted(NSE_HOLIDAYS.items()):
        h_date = datetime.strptime(dt_str, "%Y-%m-%d").date()
        if h_date >= today:
            days_away = (h_date - today).days
            upcoming.append({
                "date": dt_str,
                "name": name,
                "day_name": h_date.strftime("%A"),
                "formatted": h_date.strftime("%d %b %Y"),
                "days_away": days_away,
                "countdown": "Today" if days_away == 0 else f"In {days_away} days",
            })
            if len(upcoming) >= limit:
                break
    return upcoming


def get_all_holidays(year: Optional[int] = None) -> list[dict]:
    """Returns all NSE holidays for a specific year (default: current year)."""
    target_year = year or get_ist_now().year
    out = []
    for dt_str, name in sorted(NSE_HOLIDAYS.items()):
        if dt_str.startswith(str(target_year)):
            h_date = datetime.strptime(dt_str, "%Y-%m-%d").date()
            out.append({
                "date": dt_str,
                "name": name,
                "day_name": h_date.strftime("%A"),
                "formatted": h_date.strftime("%d %b %Y"),
            })
    return out
