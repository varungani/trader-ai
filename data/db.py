"""
TraderAI - Database Layer
SQLite persistence for recommendations, paper trades, backtest results, and daily scores.
"""
import sqlite3
import json
from datetime import datetime
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Get SQLite database connection, creating tables if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    """Create all required tables if they don't exist."""
    cursor = conn.cursor()

    # Daily stock scores and recommendations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            technical_score REAL,
            fundamental_score REAL,
            sentiment_score REAL,
            macro_score REAL,
            event_risk_score REAL,
            final_score REAL,
            action TEXT,
            reasoning TEXT,
            risk_level TEXT,
            stop_loss REAL,
            target_price REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, ticker, timeframe)
        )
    """)

    # Paper trades
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            action TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_date TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            stop_loss REAL,
            target_price REAL,
            exit_price REAL,
            exit_date TEXT,
            exit_reason TEXT,
            pnl REAL,
            pnl_percent REAL,
            status TEXT DEFAULT 'OPEN',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Backtest results
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            initial_capital REAL,
            final_capital REAL,
            total_return REAL,
            sharpe_ratio REAL,
            max_drawdown REAL,
            win_rate REAL,
            total_trades INTEGER,
            avg_return_per_trade REAL,
            results_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Daily market briefs (LLM-generated)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            market_summary TEXT,
            top_picks_json TEXT,
            portfolio_actions_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Live Forward Validation and Statistical Audit Log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forward_test_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            action TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_price REAL NOT NULL,
            final_score REAL,
            technical_score REAL,
            fundamental_score REAL,
            sentiment_score REAL,
            macro_score REAL,
            event_risk_score REAL,
            judge_verdict TEXT,
            nifty_entry_price REAL,
            current_price REAL,
            current_pnl_pct REAL,
            nifty_current_price REAL,
            nifty_pnl_pct REAL,
            alpha_pct REAL,
            status TEXT DEFAULT 'OPEN',
            exit_price REAL,
            exit_date TEXT,
            exit_reason TEXT,
            exit_pnl_pct REAL,
            exit_alpha_pct REAL,
            days_held INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, ticker, timeframe)
        )
    """)

    # Crypto Paper Trades (Shadow Tracking Bucket)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_crypto_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name TEXT,
            strategy_mode TEXT NOT NULL,
            entry_price_usd REAL NOT NULL,
            entry_price_inr REAL NOT NULL,
            quantity_tokens REAL NOT NULL,
            allocated_inr REAL NOT NULL,
            entry_date TEXT NOT NULL,
            stop_loss_usd REAL NOT NULL,
            target_price_usd REAL NOT NULL,
            trailing_ema_usd REAL,
            exit_price_usd REAL,
            exit_price_inr REAL,
            exit_date TEXT,
            exit_reason TEXT,
            pnl_inr REAL,
            pnl_pct REAL,
            tds_inr REAL,
            status TEXT DEFAULT 'OPEN',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # Lightweight migrations for existing DBs
    try:
        cursor.execute("ALTER TABLE daily_scores ADD COLUMN event_risk_score REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass


# ─── Daily Scores CRUD ─────────────────────────────────────────

def save_daily_score(conn: sqlite3.Connection, score: dict):
    """Save or update a daily stock score."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO daily_scores 
        (date, ticker, timeframe, technical_score, fundamental_score,
         sentiment_score, macro_score, event_risk_score, final_score, action, reasoning,
         risk_level, stop_loss, target_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        score.get("date", datetime.now().strftime("%Y-%m-%d")),
        score["ticker"],
        score["timeframe"],
        score.get("technical_score"),
        score.get("fundamental_score"),
        score.get("sentiment_score"),
        score.get("macro_score"),
        score.get("event_risk_score"),
        score.get("final_score"),
        score.get("action"),
        score.get("reasoning"),
        score.get("risk_level"),
        score.get("stop_loss"),
        score.get("target_price"),
    ))
    conn.commit()


def get_daily_scores(conn: sqlite3.Connection, date: str = None, timeframe: str = None) -> list[dict]:
    """Fetch daily scores, optionally filtered by date and timeframe."""
    query = "SELECT * FROM daily_scores WHERE 1=1"
    params = []

    if date:
        query += " AND date = ?"
        params.append(date)
    if timeframe:
        query += " AND timeframe = ?"
        params.append(timeframe)

    query += " ORDER BY final_score DESC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_score_history(conn: sqlite3.Connection, ticker: str, days: int = 30) -> list[dict]:
    """Fetch score history for a specific stock over N days."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM daily_scores 
        WHERE ticker = ? 
        ORDER BY date DESC LIMIT ?
    """, (ticker, days))
    return [dict(row) for row in cursor.fetchall()]


# ─── Paper Trades CRUD ──────────────────────────────────────────

def create_paper_trade(conn: sqlite3.Connection, trade: dict) -> int:
    """Create a new paper trade. Returns the trade ID."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO paper_trades 
        (ticker, timeframe, action, entry_price, entry_date, quantity,
         stop_loss, target_price, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade["ticker"],
        trade["timeframe"],
        trade["action"],
        trade["entry_price"],
        trade.get("entry_date", datetime.now().strftime("%Y-%m-%d")),
        trade["quantity"],
        trade.get("stop_loss"),
        trade.get("target_price"),
        trade.get("notes", ""),
    ))
    conn.commit()
    return cursor.lastrowid


def close_paper_trade(conn: sqlite3.Connection, trade_id: int,
                      exit_price: float, exit_reason: str = "Manual"):
    """Close an open paper trade with exit price."""
    cursor = conn.cursor()

    # Get the trade to calculate P&L
    cursor.execute("SELECT * FROM paper_trades WHERE id = ?", (trade_id,))
    trade = cursor.fetchone()
    if not trade:
        return

    trade = dict(trade)
    entry_price = trade["entry_price"]
    quantity = trade["quantity"]

    if trade["action"] == "BUY":
        pnl = (exit_price - entry_price) * quantity
    else:
        pnl = (entry_price - exit_price) * quantity

    pnl_percent = (pnl / (entry_price * quantity)) * 100

    cursor.execute("""
        UPDATE paper_trades 
        SET exit_price = ?, exit_date = ?, exit_reason = ?,
            pnl = ?, pnl_percent = ?, status = 'CLOSED'
        WHERE id = ?
    """, (exit_price, datetime.now().strftime("%Y-%m-%d"),
          exit_reason, round(pnl, 2), round(pnl_percent, 2), trade_id))
    conn.commit()


def get_open_paper_trades(conn: sqlite3.Connection) -> list[dict]:
    """Fetch all open paper trades."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM paper_trades WHERE status = 'OPEN' ORDER BY entry_date DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def update_paper_trade_stop(conn: sqlite3.Connection, trade_id: int, new_stop: float) -> None:
    """Update stop-loss for an open paper trade (trailing stop / breakeven)."""
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE paper_trades SET stop_loss = ? WHERE id = ?",
        (round(new_stop, 2), trade_id)
    )
    conn.commit()


def partial_close_paper_trade(
    conn: sqlite3.Connection,
    trade_id: int,
    exit_price: float,
    closed_qty: int,
    exit_reason: str = "PARTIAL_PROFIT_T1 (+7%)",
) -> int:
    """
    Book partial profit:
    1. Reduces the open trade's quantity by closed_qty.
    2. Inserts a separate CLOSED trade row for the booked portion with its realized P&L.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM paper_trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    if not row:
        return 0
    t = dict(row)
    remaining_qty = t["quantity"] - closed_qty
    if remaining_qty <= 0:
        close_paper_trade(conn, trade_id, exit_price, exit_reason)
        return trade_id

    # Update original trade with remaining quantity
    cursor.execute(
        "UPDATE paper_trades SET quantity = ? WHERE id = ?",
        (remaining_qty, trade_id),
    )

    # Insert a closed row for the realized portion
    entry_price = t["entry_price"]
    pnl = (exit_price - entry_price) * closed_qty
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0

    cursor.execute("""
        INSERT INTO paper_trades
        (ticker, timeframe, action, entry_price, entry_date, quantity,
         stop_loss, target_price, exit_price, exit_date, exit_reason, pnl, pnl_percent, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', ?)
    """, (
        t["ticker"],
        t["timeframe"],
        t["action"],
        entry_price,
        t["entry_date"],
        closed_qty,
        t["stop_loss"],
        t["target_price"],
        exit_price,
        datetime.now().strftime("%Y-%m-%d"),
        exit_reason,
        round(pnl, 2),
        round(pnl_pct, 2),
        f"Partial booking from trade #{trade_id}",
    ))
    conn.commit()
    return cursor.lastrowid




def get_paper_trade_history(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Fetch paper trade history (closed trades)."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM paper_trades 
        WHERE status = 'CLOSED' 
        ORDER BY exit_date DESC LIMIT ?
    """, (limit,))
    return [dict(row) for row in cursor.fetchall()]


def get_paper_trade_stats(conn: sqlite3.Connection) -> dict:
    """Calculate overall paper trading performance stats."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM paper_trades WHERE status = 'CLOSED'")
    trades = [dict(row) for row in cursor.fetchall()]

    if not trades:
        return {"total_trades": 0}

    wins = [t for t in trades if t["pnl"] and t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] and t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades if t["pnl"])

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / len(trades), 2) if trades else 0,
        "best_trade": max((t["pnl"] for t in trades if t["pnl"]), default=0),
        "worst_trade": min((t["pnl"] for t in trades if t["pnl"]), default=0),
    }


# ─── Backtest Results ───────────────────────────────────────────

def save_backtest_result(conn: sqlite3.Connection, result: dict):
    """Save a backtest run result."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO backtest_results 
        (strategy_name, start_date, end_date, initial_capital, final_capital,
         total_return, sharpe_ratio, max_drawdown, win_rate, total_trades,
         avg_return_per_trade, results_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result["strategy_name"],
        result["start_date"],
        result["end_date"],
        result.get("initial_capital", 100000),
        result.get("final_capital"),
        result.get("total_return"),
        result.get("sharpe_ratio"),
        result.get("max_drawdown"),
        result.get("win_rate"),
        result.get("total_trades"),
        result.get("avg_return_per_trade"),
        json.dumps(result.get("detailed_results", {})),
    ))
    conn.commit()


# ─── Daily Briefs ───────────────────────────────────────────────

def save_daily_brief(conn: sqlite3.Connection, date: str, brief: dict):
    """Save the daily market brief."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO daily_briefs 
        (date, market_summary, top_picks_json, portfolio_actions_json)
        VALUES (?, ?, ?, ?)
    """, (
        date,
        brief.get("market_summary", ""),
        json.dumps(brief.get("top_picks", [])),
        json.dumps(brief.get("portfolio_actions", [])),
    ))
    conn.commit()


def get_daily_brief(conn: sqlite3.Connection, date: str = None) -> dict:
    """Get the daily brief for a specific date (defaults to today)."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_briefs WHERE date = ?", (date,))
    row = cursor.fetchone()
    if row:
        result = dict(row)
        result["top_picks"] = json.loads(result.get("top_picks_json", "[]"))
        result["portfolio_actions"] = json.loads(result.get("portfolio_actions_json", "[]"))
        return result
    return {}


# ─── Live Forward Validation Log ───────────────────────────────

def log_forward_trade(conn: sqlite3.Connection, trade: dict) -> int:
    """Log an unalterable forward recommendation snapshot (preserves morning print)."""
    cursor = conn.cursor()
    trade_date = trade.get("date", datetime.now().strftime("%Y-%m-%d"))
    timeframe = trade.get("timeframe", "mid_term")
    ticker = trade["ticker"]

    # If already logged today, preserve original morning entry snapshot
    cursor.execute(
        "SELECT id FROM forward_test_log WHERE date = ? AND ticker = ? AND timeframe = ?",
        (trade_date, ticker, timeframe),
    )
    existing = cursor.fetchone()
    if existing:
        return existing[0]

    cursor.execute("""
        INSERT INTO forward_test_log
        (timestamp, date, ticker, timeframe, action, entry_price, stop_loss, target_price,
         final_score, technical_score, fundamental_score, sentiment_score, macro_score,
         event_risk_score, judge_verdict, nifty_entry_price, current_price, current_pnl_pct,
         nifty_current_price, nifty_pnl_pct, alpha_pct, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.get("timestamp", datetime.now().isoformat()),
        trade_date,
        ticker,
        timeframe,
        trade.get("action", "BUY"),
        trade["entry_price"],
        trade["stop_loss"],
        trade["target_price"],
        trade.get("final_score"),
        trade.get("technical_score"),
        trade.get("fundamental_score"),
        trade.get("sentiment_score"),
        trade.get("macro_score"),
        trade.get("event_risk_score"),
        trade.get("judge_verdict", "PASS"),
        trade.get("nifty_entry_price", 0.0),
        trade.get("entry_price"),
        0.0,
        trade.get("nifty_entry_price", 0.0),
        0.0,
        0.0,
        "OPEN",
    ))
    conn.commit()
    return cursor.lastrowid



def get_open_forward_trades(conn: sqlite3.Connection) -> list[dict]:
    """Fetch all active open forward test trades."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM forward_test_log WHERE status = 'OPEN' ORDER BY date DESC")
    return [dict(row) for row in cursor.fetchall()]


def update_forward_trade_mtm(conn: sqlite3.Connection, trade_id: int, updates: dict):
    """Update mark-to-market prices, alpha, and days held for open forward trade."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE forward_test_log
        SET current_price = ?, current_pnl_pct = ?, nifty_current_price = ?,
            nifty_pnl_pct = ?, alpha_pct = ?, days_held = ?
        WHERE id = ?
    """, (
        updates["current_price"],
        updates["current_pnl_pct"],
        updates.get("nifty_current_price"),
        updates.get("nifty_pnl_pct", 0.0),
        updates.get("alpha_pct", 0.0),
        updates.get("days_held", 0),
        trade_id,
    ))
    conn.commit()


def resolve_forward_trade(conn: sqlite3.Connection, trade_id: int, resolution: dict):
    """Resolve a forward trade upon hitting target, stop-loss, or expiry."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE forward_test_log
        SET exit_price = ?, exit_date = ?, exit_reason = ?, exit_pnl_pct = ?,
            exit_alpha_pct = ?, status = ?
        WHERE id = ?
    """, (
        resolution["exit_price"],
        resolution.get("exit_date", datetime.now().strftime("%Y-%m-%d")),
        resolution["exit_reason"],
        resolution["exit_pnl_pct"],
        resolution.get("exit_alpha_pct", 0.0),
        resolution.get("status", "RESOLVED"),
        trade_id,
    ))
    conn.commit()


def get_all_forward_trades(conn: sqlite3.Connection, limit: int = 150) -> list[dict]:
    """Get all forward test trades (both open and resolved)."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM forward_test_log ORDER BY date DESC, id DESC LIMIT ?", (limit,))
    return [dict(row) for row in cursor.fetchall()]


# ─── Crypto Paper Trades CRUD (Shadow Tracking) ───────────────────

def create_paper_crypto_trade(conn: sqlite3.Connection, trade: dict) -> int:
    """Create a new crypto paper trade in SQLite."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO paper_crypto_trades 
        (symbol, name, strategy_mode, entry_price_usd, entry_price_inr,
         quantity_tokens, allocated_inr, entry_date, stop_loss_usd,
         target_price_usd, trailing_ema_usd, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade["symbol"],
        trade.get("name", trade["symbol"]),
        trade.get("strategy_mode", "Parabolic Moonshot"),
        trade["entry_price_usd"],
        trade["entry_price_inr"],
        trade["quantity_tokens"],
        trade["allocated_inr"],
        trade.get("entry_date", datetime.now().strftime("%Y-%m-%d")),
        trade["stop_loss_usd"],
        trade["target_price_usd"],
        trade.get("trailing_ema_usd", trade["stop_loss_usd"]),
        trade.get("notes", ""),
    ))
    conn.commit()
    return cursor.lastrowid


def close_paper_crypto_trade(
    conn: sqlite3.Connection,
    trade_id: int,
    exit_price_usd: float,
    exit_reason: str = "MANUAL",
    exit_price_inr: float = 0.0,
    tds_inr: float = 0.0,
    pnl_inr: float = 0.0,
    pnl_pct: float = 0.0,
):
    """Close an open crypto paper trade with realized P&L and 1% TDS deducted."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE paper_crypto_trades
        SET exit_price_usd = ?, exit_price_inr = ?, exit_date = ?,
            exit_reason = ?, pnl_inr = ?, pnl_pct = ?, tds_inr = ?,
            status = 'CLOSED'
        WHERE id = ?
    """, (
        exit_price_usd,
        exit_price_inr,
        datetime.now().strftime("%Y-%m-%d"),
        exit_reason,
        round(pnl_inr, 2),
        round(pnl_pct, 2),
        round(tds_inr, 2),
        trade_id,
    ))
    conn.commit()


def get_open_crypto_paper_trades(conn: sqlite3.Connection) -> list[dict]:
    """Fetch all open crypto paper trades."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM paper_crypto_trades WHERE status = 'OPEN' ORDER BY entry_date DESC, id DESC")
    return [dict(row) for row in cursor.fetchall()]


def get_closed_crypto_paper_trades(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Fetch closed crypto paper trades for statistical audit."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM paper_crypto_trades WHERE status = 'CLOSED' ORDER BY exit_date DESC, id DESC LIMIT ?", (limit,))
    return [dict(row) for row in cursor.fetchall()]


def update_crypto_paper_trade_stop(
    conn: sqlite3.Connection,
    trade_id: int,
    new_stop_usd: float,
    new_trail_usd: float = 0.0
):
    """Update trailing stop-loss for open crypto paper trade."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE paper_crypto_trades
        SET stop_loss_usd = ?, trailing_ema_usd = ?
        WHERE id = ?
    """, (round(new_stop_usd, 4), round(new_trail_usd, 4), trade_id))
    conn.commit()


def delete_crypto_paper_trade(conn: sqlite3.Connection, trade_id: int):
    """Delete a paper trade (if entered by mistake)."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM paper_crypto_trades WHERE id = ?", (trade_id,))
    conn.commit()

