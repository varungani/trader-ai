import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import fetch_stock_history
from analysis.technical import compute_technical_score

tickers = ['AXISBANK.NS', 'MPHASIS.NS', 'KOTAKBANK.NS', 'MOTHERSON.NS', 'NESTLEIND.NS', 'COFORGE.NS', 'DIVISLAB.NS', 'SUPREMEIND.NS', 'MON100.NS']

data_by_ticker = {t: fetch_stock_history(t, period='2y') for t in tickers}
data_by_ticker = {t: df for t, df in data_by_ticker.items() if not df.empty and len(df) >= 60}
all_dates = sorted(list(set.union(*[set(df.index.strftime("%Y-%m-%d")) for df in data_by_ticker.values()])))

def run_test(label, trail_fn):
    cash = 100000.0
    portfolio_value = 100000.0
    trades = []
    open_positions = {}
    
    for date_str in all_dates:
        to_close = []
        for sym, pos in open_positions.items():
            df = data_by_ticker.get(sym)
            day_rows = df[df.index.strftime("%Y-%m-%d") == date_str]
            if day_rows.empty:
                continue
            high = float(day_rows["High"].iloc[0])
            low = float(day_rows["Low"].iloc[0])
            close = float(day_rows["Close"].iloc[0])
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), high)
            
            trail_fn(pos)
                
            exit_reason = None
            exit_px = close
            if low <= pos["stop_loss"]:
                exit_reason = "TRAILING_STOP" if pos["stop_loss"] > pos["entry_price"] else "STOP_LOSS"
                exit_px = pos["stop_loss"]
            elif high >= pos["target"]:
                exit_reason = "TARGET"
                exit_px = pos["target"]
                
            if exit_reason:
                pnl = (exit_px - pos["entry_price"]) * pos["qty"]
                cash += exit_px * pos["qty"]
                trades.append({"pnl": pnl, "reason": exit_reason})
                to_close.append(sym)
        for sym in to_close:
            del open_positions[sym]
            
        for sym, df in data_by_ticker.items():
            if sym in open_positions or len(open_positions) >= 15:
                continue
            sub_df = df[df.index.strftime("%Y-%m-%d") <= date_str]
            if len(sub_df) < 50:
                continue
            close_px = float(sub_df["Close"].iloc[-1])
            sma_50 = sub_df["Close"].rolling(50).mean().iloc[-1]
            if close_px < sma_50:
                continue
            tech = compute_technical_score(sub_df.tail(100), ticker=sym)
            if float(tech.get("score", 50)) >= 65:
                alloc = min(cash, (portfolio_value or cash) * 0.25)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= qty * close_px:
                    cash -= qty * close_px
                    open_positions[sym] = {
                        "entry_price": close_px,
                        "qty": qty,
                        "stop_loss": round(close_px * 0.93, 2),
                        "target": round(close_px * 1.15, 2),
                        "peak_price": close_px,
                    }
        holdings_value = sum(float(data_by_ticker[s][data_by_ticker[s].index.strftime("%Y-%m-%d") <= date_str]["Close"].iloc[-1]) * p["qty"] for s, p in open_positions.items() if not data_by_ticker[s][data_by_ticker[s].index.strftime("%Y-%m-%d") <= date_str].empty)
        portfolio_value = cash + holdings_value
    
    ret = (portfolio_value - 100000.0) / 1000.0
    wins = [t for t in trades if t["pnl"] > 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    print(f"{label}: Return = {ret:+.2f}% | WinRate = {wr:.1f}% | Trades = {len(trades)}")

def trail_old(pos):
    g = (pos["peak_price"] - pos["entry_price"]) / pos["entry_price"]
    if g >= 0.10:
        pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.06, 2))
    elif g >= 0.06:
        pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.015, 2))

def trail_none(pos):
    pass

def trail_smart(pos):
    g = (pos["peak_price"] - pos["entry_price"]) / pos["entry_price"]
    if g >= 0.11:
        pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.06, 2))

run_test("1. Old Trailing Stop (User run)", trail_old)
run_test("2. No Trailing Stop (Pure 2:1 R:R)", trail_none)
run_test("3. Smart Trailing Stop (Only at +11% lock +6%)", trail_smart)
