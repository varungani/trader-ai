"""
engine/analytics/simulator.py

TraderAI Modular, Object-Oriented Portfolio Simulation Engine (v3.5.0)
=====================================================================
A clean, modular, typed portfolio backtester that guarantees:
  1. Strict Zero-Lookahead Bias: Screen on Close T -> Fill on Open T+1 with slippage.
  2. Real Statutory Indian Delivery Costs: STT (0.1%), GST (18%), Stamp Duty (0.015%), CDSL DP charges (₹15.93).
  3. Net Debt Accounting: Net Asset Value = Cash + Holdings Value - Borrowed Margin Debt.
  4. Multi-Stage Pyramiding & Dynamic Conviction Sizing.
  5. Institutional Trailing Stops: Weekly 10W EMA, Daily 20-EMA, Day 21 Stagnation Cutoff.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("PortfolioSimulator")


@dataclass
class SimulationConfig:
    """Configuration parameters for portfolio simulation."""
    starting_cash: float = 100000.0
    max_slots: int = 3
    slot_allocations: List[float] = field(default_factory=lambda: [0.40, 0.30, 0.30])
    slippage_pct: float = 0.0025          # 0.25% per leg
    base_risk_pct: float = 0.030          # 3.0% equity risk per trade
    hard_stop_loss_pct: float = 0.07      # -7.0% floor
    use_mtf_leverage: bool = False
    mtf_leverage: float = 1.0             # e.g., 2.0x MTF
    mtf_interest_annual: float = 0.10     # 10% p.a.
    enable_pyramiding: bool = True
    pyramid_trigger_gain: float = 0.25    # Add once up >= +25%
    pyramid_size_fraction: float = 0.35   # Add +35% shares
    use_weekly_10w_trail: bool = True
    use_day21_cutoff: bool = False        # Day 21 stagnation cutoff (< +3%)
    use_daily_20ema_trail: bool = False
    idle_cash_yield_annual: float = 0.065 # 6.5% LiquidBees / cash yield


@dataclass
class SimulationPosition:
    """Represents an active trade position during simulation."""
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    borrowed_capital: float = 0.0
    initial_stop: float = 0.0
    current_stop: float = 0.0
    days_held: int = 0
    highest_close: float = 0.0
    pyramid_stage: int = 0
    pending_pyramid: bool = False
    pending_exit: bool = False
    pending_exit_reason: str = ""


@dataclass
class SimulationTrade:
    """Immutable record of a closed trade."""
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: int
    capital_invested: float
    borrowed_capital: float
    gross_pnl_inr: float
    friction_inr: float
    net_pnl_inr: float
    net_pnl_pct: float
    days_held: int
    pyramids: int
    exit_reason: str
    is_oos: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2),
            "shares": self.shares,
            "capital_invested": round(self.capital_invested, 2),
            "net_pnl_inr": round(self.net_pnl_inr, 2),
            "net_pnl_pct": round(self.net_pnl_pct, 2),
            "friction_inr": round(self.friction_inr, 2),
            "days_held": self.days_held,
            "pyramids": self.pyramids,
            "exit_reason": self.exit_reason,
            "is_oos": self.is_oos,
        }


@dataclass
class SimulationResult:
    """Aggregated empirical results and risk analytics."""
    config: SimulationConfig
    initial_capital: float
    ending_capital: float
    net_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    profit_factor: float
    win_rate_pct: float
    total_trades: int
    total_friction_inr: float
    total_interest_inr: float
    peak_rolling_12m_pct: float
    yearly_returns: Dict[int, float]
    daily_equity_df: pd.DataFrame
    trades_df: pd.DataFrame

    def print_summary(self, label: str = "Simulation Result") -> None:
        """Prints a structured institutional audit summary."""
        print(f"\n{'='*75}")
        print(f"📊 {label.upper()}")
        print(f"{'='*75}")
        print(f" • Ending Capital     : ₹{self.ending_capital:,.2f} ({self.net_return_pct:+.2f}%)")
        print(f" • 5-Year CAGR        : {self.cagr_pct:+.2f}% per year")
        print(f" • Peak Rolling 12M   : +{self.peak_rolling_12m_pct:.2f}%")
        print(f" • Max Peak Drawdown  : {self.max_drawdown_pct:.2f}%")
        print(f" • Trades / Win Rate  : {self.total_trades} trades | Win Rate: {self.win_rate_pct:.1f}% | PF: {self.profit_factor:.2f}")
        print(f" • Statutory Friction : ₹{self.total_friction_inr:,.2f} | MTF Financing: ₹{self.total_interest_inr:,.2f}")
        yearly_str = " | ".join([f"{yr}: {ret:+.1f}%" for yr, ret in self.yearly_returns.items()])
        print(f" • Yearly Breakdown   : {yearly_str}")
        print(f"{'='*75}")


class PortfolioSimulator:
    """
    Object-oriented execution engine for multi-asset equity compounding.
    Strictly enforces zero lookahead and Indian delivery statutory taxes.
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or SimulationConfig()
        self.daily_yield = (1.0 + self.config.idle_cash_yield_annual) ** (1.0 / 252.0) - 1.0
        self.daily_mtf_interest = self.config.mtf_interest_annual / 365.0

    @staticmethod
    def compute_statutory_costs(val: float, is_buy: bool = False, dp_charge: float = 15.93) -> float:
        """Exact statutory Indian delivery transaction costs."""
        brokerage = min(20.0, val * 0.0003)
        stt = (val * 0.001) if not is_buy else 0.0
        turnover = val * 0.0000345
        stamp = (val * 0.00015) if is_buy else 0.0
        gst = (brokerage + turnover) * 0.18
        dp = 0.0 if is_buy else dp_charge
        return brokerage + stt + turnover + stamp + gst + dp

    def run(
        self,
        indicators: Dict[str, Dict[str, Any]],
        nifty: pd.DataFrame,
        market_breadth: pd.Series,
        weekly_emas: Dict[str, pd.DataFrame],
        vol_asym: Dict[str, pd.Series],
        df_r1m: pd.DataFrame,
        df_r3m: pd.DataFrame,
        df_r6m: pd.DataFrame,
        split_date: pd.Timestamp = pd.Timestamp("2024-04-01"),
        start_idx: int = 252,
    ) -> SimulationResult:
        """Executes a full multi-year simulation across trading dates."""
        trading_dates = list(nifty.index)
        active_dates = trading_dates[start_idx:]

        cash = self.config.starting_cash
        borrowed_total = 0.0
        positions: List[SimulationPosition] = []
        closed_trades: List[SimulationTrade] = []
        daily_equity_curve: List[Dict[str, Any]] = []
        total_friction = 0.0
        total_interest = 0.0
        peak_equity = self.config.starting_cash

        for d_idx in range(len(active_dates) - 1):
            today = active_dates[d_idx]
            next_day = active_dates[d_idx + 1]

            # Daily cash yield / MTF interest
            if cash > 1000.0 and borrowed_total == 0:
                cash += cash * self.daily_yield
            elif borrowed_total > 0:
                daily_int = borrowed_total * self.daily_mtf_interest
                cash -= daily_int
                total_interest += daily_int

            # -----------------------------------------------------------------
            # 1. EXECUTE PENDING ACTIONS AT TODAY'S OPEN (STRICT ZERO LOOKAHEAD)
            # -----------------------------------------------------------------
            surviving_positions: List[SimulationPosition] = []
            for pos in positions:
                sym = pos.symbol
                ind = indicators[sym]
                if today not in ind["dates"]:
                    surviving_positions.append(pos)
                    continue

                day_o = ind["o"].loc[today]

                if pos.pending_exit:
                    exit_fill = day_o * (1.0 - self.config.slippage_pct)
                    sell_val = pos.shares * exit_fill
                    friction = self.compute_statutory_costs(sell_val, is_buy=False)
                    total_friction += friction

                    if pos.borrowed_capital > 0:
                        borrowed_total = max(0.0, borrowed_total - pos.borrowed_capital)
                        cash += (sell_val - friction - pos.borrowed_capital)
                    else:
                        cash += (sell_val - friction)

                    net_pnl = (sell_val - friction) - pos.capital_invested
                    closed_trades.append(SimulationTrade(
                        symbol=sym, entry_date=pos.entry_date, exit_date=today,
                        entry_price=pos.entry_price, exit_price=exit_fill,
                        shares=pos.shares, capital_invested=pos.capital_invested,
                        borrowed_capital=pos.borrowed_capital,
                        gross_pnl_inr=(exit_fill - pos.entry_price) * pos.shares,
                        friction_inr=friction, net_pnl_inr=net_pnl,
                        net_pnl_pct=(net_pnl / pos.capital_invested) * 100.0,
                        days_held=pos.days_held, pyramids=pos.pyramid_stage,
                        exit_reason=pos.pending_exit_reason, is_oos=(pos.entry_date >= split_date)
                    ))
                    continue

                if pos.pending_pyramid:
                    add_shares = int(pos.shares * self.config.pyramid_size_fraction)
                    if add_shares > 0:
                        add_fill = day_o * (1.0 + self.config.slippage_pct)
                        add_cost = add_shares * add_fill
                        add_fric = self.compute_statutory_costs(add_cost, is_buy=True)

                        can_buy = False
                        add_borrow = 0.0
                        if cash >= add_cost + add_fric:
                            can_buy = True
                            cash -= (add_cost + add_fric)
                        elif self.config.use_mtf_leverage and self.config.mtf_leverage > 1.0:
                            needed = add_cost + add_fric
                            can_buy = True
                            add_borrow = max(0.0, needed - max(0.0, cash))
                            cash -= (needed - add_borrow)
                            borrowed_total += add_borrow
                            pos.borrowed_capital += add_borrow

                        if can_buy:
                            total_friction += add_fric
                            pos.capital_invested += add_cost
                            total_shares = pos.shares + add_shares
                            pos.entry_price = pos.capital_invested / total_shares
                            pos.shares = total_shares
                            pos.current_stop = max(pos.current_stop, pos.entry_price * 0.98)
                            pos.pyramid_stage += 1
                    pos.pending_pyramid = False

                surviving_positions.append(pos)
            positions = surviving_positions

            # -----------------------------------------------------------------
            # 2. INTRADAY STOPS (Day Low breaching Stop)
            # -----------------------------------------------------------------
            intraday_survivors: List[SimulationPosition] = []
            for pos in positions:
                sym = pos.symbol
                ind = indicators[sym]
                if today not in ind["dates"]:
                    intraday_survivors.append(pos)
                    continue

                day_o = ind["o"].loc[today]
                day_l = ind["l"].loc[today]
                day_c = ind["c"].loc[today]
                pos.days_held += 1
                if day_c > pos.highest_close: pos.highest_close = day_c

                exit_now = False
                exit_px = 0.0
                reason = ""

                if day_o <= pos.current_stop:
                    exit_now = True
                    exit_px = day_o * (1.0 - self.config.slippage_pct)
                    reason = "GAP_DOWN_STOP"
                elif day_l <= pos.current_stop:
                    exit_now = True
                    exit_px = pos.current_stop * (1.0 - self.config.slippage_pct)
                    reason = "INTRADAY_STOP"

                if exit_now:
                    sell_val = pos.shares * exit_px
                    friction = self.compute_statutory_costs(sell_val, is_buy=False)
                    total_friction += friction
                    if pos.borrowed_capital > 0:
                        borrowed_total = max(0.0, borrowed_total - pos.borrowed_capital)
                        cash += (sell_val - friction - pos.borrowed_capital)
                    else:
                        cash += (sell_val - friction)

                    net_pnl = (sell_val - friction) - pos.capital_invested
                    closed_trades.append(SimulationTrade(
                        symbol=sym, entry_date=pos.entry_date, exit_date=today,
                        entry_price=pos.entry_price, exit_price=exit_px,
                        shares=pos.shares, capital_invested=pos.capital_invested,
                        borrowed_capital=pos.borrowed_capital,
                        gross_pnl_inr=(exit_px - pos.entry_price) * pos.shares,
                        friction_inr=friction, net_pnl_inr=net_pnl,
                        net_pnl_pct=(net_pnl / pos.capital_invested) * 100.0,
                        days_held=pos.days_held, pyramids=pos.pyramid_stage,
                        exit_reason=reason, is_oos=(pos.entry_date >= split_date)
                    ))
                else:
                    intraday_survivors.append(pos)
            positions = intraday_survivors

            # -----------------------------------------------------------------
            # 3. MARK-TO-MARKET NET ASSET VALUE
            # -----------------------------------------------------------------
            holdings_val = 0.0
            for pos in positions:
                sym = pos.symbol
                ind = indicators[sym]
                px = ind["c"].loc[today] if today in ind["dates"] else pos.entry_price
                holdings_val += pos.shares * px

            net_equity = cash + holdings_val - borrowed_total
            if net_equity > peak_equity: peak_equity = net_equity
            portfolio_dd = (net_equity - peak_equity) / peak_equity
            daily_equity_curve.append({
                "date": today, "equity": net_equity, "drawdown": portfolio_dd,
                "cash": cash, "debt": borrowed_total, "positions": len(positions)
            })

            # -----------------------------------------------------------------
            # 4. END-OF-DAY SCREENING FOR TOMORROW'S OPEN (ZERO LOOKAHEAD)
            # -----------------------------------------------------------------
            is_friday = (today.weekday() == 4)
            for pos in positions:
                ind = indicators[pos.symbol]
                if today not in ind["dates"]: continue
                day_c = ind["c"].loc[today]
                gain_pct = (day_c / pos.entry_price - 1.0) * 100.0

                # Exit evaluations
                if self.config.use_weekly_10w_trail and is_friday and pos.days_held >= 5:
                    w_df = weekly_emas.get(pos.symbol)
                    if w_df is not None and today in w_df.index:
                        if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                            pos.pending_exit = True
                            pos.pending_exit_reason = "WEEKLY_10W_EMA_TRAIL"

                elif self.config.use_day21_cutoff and pos.days_held >= 21 and gain_pct < 3.0:
                    pos.pending_exit = True
                    pos.pending_exit_reason = "DAY21_STAGNATION_CUTOFF"

                elif self.config.use_daily_20ema_trail and pos.days_held >= 5 and gain_pct >= 3.0:
                    ema20 = ind["ema20"].loc[today]
                    if day_c < ema20:
                        pos.pending_exit = True
                        pos.pending_exit_reason = "DAILY_20EMA_TRAIL"

                # Pyramiding evaluation
                if self.config.enable_pyramiding and pos.pyramid_stage < 2 and pos.days_held >= 15 and not pos.pending_exit:
                    h20 = ind["high20"].loc[today]
                    rvol = ind["rvol"].loc[today]
                    if pos.pyramid_stage == 0 and gain_pct >= 25.0 and day_c > h20 and rvol >= 1.4:
                        pos.pending_pyramid = True
                    elif pos.pyramid_stage == 1 and gain_pct >= 55.0 and day_c > h20 and rvol >= 1.4:
                        pos.pending_pyramid = True

            # Entry evaluation
            breadth_val = market_breadth.get(today, 50.0)
            nifty_c = nifty["Close"].loc[today]
            nifty_ema50 = nifty["EMA50"].loc[today]

            if breadth_val < 45.0 or nifty_c < nifty_ema50:
                continue

            active_count = len([p for p in positions if not p.pending_exit])
            open_slots = self.config.max_slots - active_count
            if open_slots <= 0: continue

            # Dynamic risk sizing
            if breadth_val >= 65.0:
                slot_risk = self.config.base_risk_pct * 1.40
                eff_leverage = self.config.mtf_leverage if self.config.use_mtf_leverage else 1.0
            elif breadth_val >= 55.0:
                slot_risk = self.config.base_risk_pct
                eff_leverage = 1.0
            else:
                slot_risk = self.config.base_risk_pct * 0.50
                eff_leverage = 1.0

            if portfolio_dd < -0.10:
                slot_risk *= 0.70
                eff_leverage = 1.0

            existing_syms = {p.symbol for p in positions}
            candidates = []
            for sym, ind in indicators.items():
                if sym in existing_syms: continue
                if today not in ind["dates"]: continue

                c_today = ind["c"].loc[today]
                h50 = ind["high50"].loc[today]
                ema50 = ind["ema50"].loc[today]
                ema20 = ind["ema20"].loc[today]
                ema200 = ind["ema200"].loc[today]
                rvol_today = ind["rvol"].loc[today]
                atr = ind["atr14"].loc[today]

                if c_today > h50 and c_today > ema50 and c_today > ema20 and rvol_today >= 1.5:
                    if (c_today / (ema200 + 1e-9) - 1.0) < 0.20: continue
                    sym_asym = vol_asym.get(sym, {}).get(today, 1.0)
                    if pd.isna(sym_asym) or sym_asym < 2.0: continue

                    r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                    r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                    r6m = df_r6m.loc[today, sym] if (today in df_r6m.index and sym in df_r6m.columns) else -999.0
                    if pd.isna(r1m) or pd.isna(r3m) or pd.isna(r6m): continue
                    if r6m > 0 and r1m < 0: continue

                    composite_rs = (0.50 * r1m) + (0.30 * r3m) + (0.20 * r6m)
                    candidates.append((sym, composite_rs, atr))

            if not candidates: continue
            candidates.sort(key=lambda x: x[1], reverse=True)
            chosen = candidates[:open_slots]

            allocs = self.config.slot_allocations
            for rank_idx, (sym, rs_val, atr_val) in enumerate(chosen):
                ind = indicators[sym]
                if next_day not in ind["dates"]: continue

                day0_c = ind["c"].loc[today]
                next_o = ind["o"].loc[next_day]
                if (next_o / day0_c - 1.0) > 0.025: continue

                entry_fill = next_o * (1.0 + self.config.slippage_pct)
                stop_dist = max(entry_fill * self.config.hard_stop_loss_pct, 2.0 * atr_val)
                initial_stop = entry_fill - stop_dist

                target_risk_inr = net_equity * slot_risk
                risk_per_share = entry_fill - initial_stop
                if risk_per_share <= 0: continue

                slot_idx = active_count + rank_idx
                cap_mult = allocs[slot_idx] if slot_idx < len(allocs) else (1.0 / self.config.max_slots)
                max_cap = net_equity * cap_mult * eff_leverage

                shares = min(int(target_risk_inr / risk_per_share), int(max_cap / entry_fill))
                if shares <= 0: continue

                position_cost = shares * entry_fill
                buy_friction = self.compute_statutory_costs(position_cost, is_buy=True)

                borrowed_part = 0.0
                if eff_leverage > 1.0 and position_cost > (net_equity * cap_mult):
                    borrowed_part = position_cost - (net_equity * cap_mult)
                    borrowed_total += borrowed_part

                cash -= (position_cost - borrowed_part + buy_friction)
                total_friction += buy_friction

                positions.append(SimulationPosition(
                    symbol=sym, entry_date=next_day, entry_price=entry_fill,
                    shares=shares, capital_invested=position_cost,
                    borrowed_capital=borrowed_part, initial_stop=initial_stop,
                    current_stop=initial_stop, days_held=0, highest_close=entry_fill
                ))

        # Final Day Liquidation
        final_equity = cash
        last_day = active_dates[-1]
        for pos in positions:
            sym = pos.symbol
            ind = indicators[sym]
            exit_px = ind["c"].loc[last_day] if last_day in ind["dates"] else pos.entry_price
            sell_val = pos.shares * exit_px * (1.0 - self.config.slippage_pct)
            friction = self.compute_statutory_costs(sell_val, is_buy=False)
            total_friction += friction
            final_equity += (sell_val - friction - pos.borrowed_capital)

        # Build Results DataFrame
        df_eq = pd.DataFrame(daily_equity_curve)
        df_trades = pd.DataFrame([t.to_dict() for t in closed_trades]) if closed_trades else pd.DataFrame()

        # Compute Metrics
        eq_series = df_eq["equity"]
        n_years = len(eq_series) / 252.0
        tot_ret = (final_equity / self.config.starting_cash - 1.0) * 100.0
        cagr = ((final_equity / self.config.starting_cash) ** (1.0 / n_years) - 1.0) * 100.0
        running_max = eq_series.cummax()
        max_dd = float(((eq_series - running_max) / running_max).min() * 100.0)

        rolling_252 = eq_series.pct_change(periods=252) * 100.0
        peak_12m = float(rolling_252.max()) if not rolling_252.isna().all() else 0.0

        wins = df_trades[df_trades["net_pnl_inr"] > 0]["net_pnl_inr"] if not df_trades.empty else pd.Series(dtype=float)
        losses = df_trades[df_trades["net_pnl_inr"] <= 0]["net_pnl_inr"] if not df_trades.empty else pd.Series(dtype=float)
        win_rate = (len(wins) / len(df_trades) * 100.0) if not df_trades.empty else 0.0
        pf = (wins.sum() / (abs(losses.sum()) + 1e-9)) if not df_trades.empty else 0.0

        # Yearly breakdown
        df_eq["year"] = pd.to_datetime(df_eq["date"]).dt.year
        yearly_dict = {}
        for y, g in df_eq.groupby("year"):
            y_ret = (g["equity"].iloc[-1] / g["equity"].iloc[0] - 1.0) * 100.0
            yearly_dict[int(y)] = round(y_ret, 2)

        return SimulationResult(
            config=self.config,
            initial_capital=self.config.starting_cash,
            ending_capital=round(final_equity, 2),
            net_return_pct=round(tot_ret, 2),
            cagr_pct=round(cagr, 2),
            max_drawdown_pct=round(max_dd, 2),
            profit_factor=round(pf, 2),
            win_rate_pct=round(win_rate, 2),
            total_trades=len(df_trades),
            total_friction_inr=round(total_friction, 2),
            total_interest_inr=round(total_interest, 2),
            peak_rolling_12m_pct=round(peak_12m, 2),
            yearly_returns=yearly_dict,
            daily_equity_df=df_eq,
            trades_df=df_trades,
        )
