"""
TraderAI - Realistic Indian Statutory Cost Calculator (NSE Cash Delivery)
Calculates exact statutory taxes and exchange friction as per Indian regulatory schedules:
  1. Securities Transaction Tax (STT): 0.1% Buy, 0.1% Sell
  2. Stamp Duty: 0.015% on Buy turnover
  3. Exchange Transaction Charges (NSE): 0.00345% of turnover
  4. SEBI Turnover Fee: 0.0001% of turnover
  5. Brokerage: Default ₹0 (Kotak Neo Trade Free / Delivery Plan) or configurable bps
  6. GST (18%): Applied on (Brokerage + Exchange Txn Charges + SEBI Fee)
  7. Depository Participant (DP) Charge: Flat ₹15.93 per stock per sell day (CDSL)
"""
from __future__ import annotations

from dataclasses import dataclass

# Regulatory tax rates (NSE Delivery CNC)
STT_BUY_RATE = 0.001       # 0.1%
STT_SELL_RATE = 0.001      # 0.1%
STAMP_DUTY_BUY_RATE = 0.00015  # 0.015%
NSE_TXN_RATE = 0.0000345   # 0.00345%
SEBI_TURNOVER_RATE = 0.000001  # 0.0001%
GST_RATE = 0.18            # 18%
CDSL_DP_CHARGE = 15.93     # ₹13.50 CDSL + 18% GST per scrip per sell day
STCG_TAX_RATE = 0.20       # 20% Short-Term Capital Gains Tax (Section 111A, Finance Act 2024)
DEFAULT_SLIPPAGE_RATE = 0.0005  # 0.05% (5 bps) market order execution slippage


@dataclass
class TradeFrictionBreakdown:
    gross_pnl_rupees: float
    gross_pnl_pct: float
    net_pnl_rupees: float
    net_pnl_pct: float
    total_friction_rupees: float
    friction_pct_of_capital: float
    stt_rupees: float
    stamp_duty_rupees: float
    exchange_charges_rupees: float
    sebi_charges_rupees: float
    brokerage_rupees: float
    gst_rupees: float
    dp_charges_rupees: float
    stcg_tax_rupees: float = 0.0
    net_post_tax_pnl_rupees: float = 0.0
    net_post_tax_pnl_pct: float = 0.0
    slippage_rupees: float = 0.0


def compute_indian_delivery_costs(
    buy_price: float,
    sell_price: float,
    quantity: int = 1,
    brokerage_pct: float = 0.0,  # 0.0% for Kotak Neo Delivery CNC Free Plan
    slippage_pct: float = DEFAULT_SLIPPAGE_RATE,
    apply_stcg: bool = True,
) -> TradeFrictionBreakdown:
    """
    Computes exact Indian statutory taxes, exchange fees, slippage, and net post-tax P&L.
    Taxes adhere to Finance Act 2024:
      - 20% STCG on positive net equity gains held < 12 months
      - STT 0.1% buy + 0.1% sell
      - Stamp Duty 0.015% buy
      - NSE Txn 0.00345% + SEBI 0.0001%
      - GST 18% on (brokerage + exchange + SEBI)
      - CDSL DP Charge ₹15.93 flat per scrip sell day
    """
    buy_turnover = float(buy_price) * int(quantity)
    sell_turnover = float(sell_price) * int(quantity)
    total_turnover = buy_turnover + sell_turnover

    if buy_turnover <= 0:
        return TradeFrictionBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    # 1. STT
    stt_buy = round(buy_turnover * STT_BUY_RATE, 2)
    stt_sell = round(sell_turnover * STT_SELL_RATE, 2)
    total_stt = stt_buy + stt_sell

    # 2. Stamp Duty (Buy side only)
    stamp_duty = round(buy_turnover * STAMP_DUTY_BUY_RATE, 2)

    # 3. Exchange Charges
    exchange_charges = round(total_turnover * NSE_TXN_RATE, 2)

    # 4. SEBI Turnover Fee
    sebi_charges = round(total_turnover * SEBI_TURNOVER_RATE, 2)

    # 5. Brokerage
    brokerage = round(total_turnover * (brokerage_pct / 100.0), 2)

    # 6. GST (18% on Brokerage + Exchange + SEBI)
    gst = round((brokerage + exchange_charges + sebi_charges) * GST_RATE, 2)

    # 7. DP Charges (Sell side only)
    dp_charges = CDSL_DP_CHARGE

    # 8. Execution Slippage
    slippage_rupees = round(total_turnover * slippage_pct, 2) if slippage_pct > 0 else 0.0

    total_friction = round(total_stt + stamp_duty + exchange_charges + sebi_charges + brokerage + gst + dp_charges + slippage_rupees, 2)
    friction_pct = round((total_friction / buy_turnover) * 100.0, 2)

    # Gross P&L
    gross_pnl = round(sell_turnover - buy_turnover, 2)
    gross_pnl_pct = round(((sell_price - buy_price) / buy_price) * 100.0, 2)

    # Net P&L (pre-tax, after-friction)
    net_pnl = round(gross_pnl - total_friction, 2)
    net_pnl_pct = round((net_pnl / buy_turnover) * 100.0, 2)

    # Note on STCG: Real Indian STCG (Section 111A) is levied annually on net aggregate gains,
    # with short-term capital losses allowed to set off gains under Section 70.
    # Evaluating strategies per-trade should always be done on net pre-tax P&L to avoid over-taxing.
    stcg_tax = round(net_pnl * STCG_TAX_RATE, 2) if (net_pnl > 0 and apply_stcg) else 0.0
    net_post_tax_pnl = round(net_pnl - stcg_tax, 2)
    net_post_tax_pct = round((net_post_tax_pnl / buy_turnover) * 100.0, 2)

    return TradeFrictionBreakdown(
        gross_pnl_rupees=gross_pnl,
        gross_pnl_pct=gross_pnl_pct,
        net_pnl_rupees=net_pnl,
        net_pnl_pct=net_pnl_pct,
        total_friction_rupees=total_friction,
        friction_pct_of_capital=friction_pct,
        stt_rupees=total_stt,
        stamp_duty_rupees=stamp_duty,
        exchange_charges_rupees=exchange_charges,
        sebi_charges_rupees=sebi_charges,
        brokerage_rupees=brokerage,
        gst_rupees=gst,
        dp_charges_rupees=dp_charges,
        stcg_tax_rupees=stcg_tax,
        net_post_tax_pnl_rupees=net_post_tax_pnl,
        net_post_tax_pnl_pct=net_post_tax_pct,
        slippage_rupees=slippage_rupees,
    )


def compute_annual_portfolio_stcg(trades: list[dict]) -> dict:
    """
    Computes statutory 20% STCG under Section 111A with Section 70 loss set-offs:
    Aggregates net pre-tax gains by financial year, sets off losses against gains,
    and applies 20% STCG tax only to net positive annual capital gains.
    """
    if not trades:
        return {"net_pretax_pnl": 0.0, "total_stcg_tax": 0.0, "net_post_tax_pnl": 0.0, "annual_breakdown": {}}
    
    import pandas as pd
    df = pd.DataFrame(trades)
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    # Indian Financial Year: April 1 to March 31
    df["fy"] = df["exit_date"].apply(lambda d: f"FY{d.year if d.month >= 4 else d.year-1}-{str(d.year+1 if d.month >= 4 else d.year)[-2:]}")
    
    annual_summary = {}
    total_tax = 0.0
    for fy, group in df.groupby("fy"):
        net_pretax = float(group["net_pnl"].sum() if "net_pnl" in group else group["pnl"].sum())
        tax = round(net_pretax * STCG_TAX_RATE, 2) if net_pretax > 0 else 0.0
        total_tax += tax
        annual_summary[fy] = {
            "net_pretax_pnl": round(net_pretax, 2),
            "stcg_tax": tax,
            "net_post_tax_pnl": round(net_pretax - tax, 2)
        }
        
    total_pretax = sum(s["net_pretax_pnl"] for s in annual_summary.values())
    return {
        "net_pretax_pnl": round(total_pretax, 2),
        "total_stcg_tax": round(total_tax, 2),
        "net_post_tax_pnl": round(total_pretax - total_tax, 2),
        "annual_breakdown": annual_summary
    }

