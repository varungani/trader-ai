# TraderAI — System Technical Report & Forward-Testing Audit
**Version:** 3.5.1-Production  
**Date of Audit:** 22 November 2026  
**Repository:** [github.com/varungani/trader-ai](https://github.com/varungani/trader-ai)  
**Branches Synchronized:** `develop`, `master`, `production`  
**Automated Test Suite Status:** 32/32 Passing (100% Green)

---

## 1. Executive Summary & Forward-Testing Status

TraderAI is an autonomous, quantitative swing-trading engine engineered specifically for **pure Indian Cash Equity (NSE Delivery / CNC)** with zero leverage, zero F&O derivatives, and zero shorting.

To determine the mathematically superior execution model under real-world conditions, the engine executes a **3-Way Side-by-Side Parallel Tournament** forward-testing on live NSE tick data with full statutory friction deductions (STT, GST, Stamp Duty, Exchange Fees, SEBI turnover, DP charges) and an explicit 0.25% execution slippage model.

### 📊 Forward-Testing Performance (Simulated ₹1,00,000 Pure Cash Per Track)

> **Statistical Note on Sample Size:**  
> The tournament currently has **0 closed trades**. All figures below represent **unrealized mark-to-market (MTM)** drift. In accordance with strict quantitative discipline, **no strategy can be declared superior or graduated until a sample of 50 to 100 closed trades is accumulated** with a lower confidence bound strictly above zero.

| Tournament Track | Execution Model | Active Slots (Max 5) | Capital Deployed | Free Cash | Realized P&L | Floating MTM (INR) | Return on ₹100k | Return on Deployed (ROC) | Closed Win Rate |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Track A: Option 2** | **9:20 AM Open Confirmation** | **3 / 5** | ₹59,641.24 | ₹40,358.76 | ₹0.00 | **₹+313.96** | **+0.31%** | **+0.53%** | 0.0% (0 Closed) |
| **Track B: Option 3** | **GTT Buy-Stop Breakout Trigger** | **5 / 5** | ₹98,172.17 | ₹1,827.83 | ₹0.00 | **₹-1,003.87** | **-1.00%** | **-1.02%** | 0.0% (0 Closed) |
| **Track C: Benchmark** | **High-RS Velocity Sniper** | **3 / 5** | ₹59,245.50 | ₹40,754.50 | ₹0.00 | **₹-599.80** | **-0.60%** | **-1.01%** | 0.0% (0 Closed) |

*Audit Timestamp: 2026-11-22 10:50:00 IST. Pending Breakout Triggers Queued: 7 scrips awaiting slot capacity in Track B.*

---

## 2. End-to-End System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                TRADERAI SYSTEM ARCHITECTURE                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

       [ 4:30 PM Post-Market ]                         [ 09:10 AM - 03:35 PM IST ]
   ┌─────────────────────────────┐               ┌──────────────────────────────────────┐
   │    Apex Engine Screener     │               │    2-Relay GitHub Actions Cloud      │
   │   (Contraction & RS Scan)   │               │   (market_session_hawk.yml - 20s)    │
   └──────────────┬──────────────┘               └──────────────────┬───────────────────┘
                  │                                                 │
                  ▼                                                 │ Relay 1: 09:10 - 12:30 IST
   ┌─────────────────────────────┐                                  │ Relay 2: 12:30 - 15:35 IST
   │    data/dual_tracker.json   │◄─────────────────────────────────┤ (Zero 6-Hour Timeout Kills)
   │ (Max 5 Slots / ₹20k Each)   │                                  │
   └──────────────┬──────────────┘                                  ▼
                  │                              ┌──────────────────────────────────────┐
                  │ Event Dispatched             │       Live NSE Tick Evaluation       │
                  ▼                              │  (0.25% Slippage, +0.6% Lock, Stops) │
   ┌─────────────────────────────┐               └──────────────────┬───────────────────┘
   │  Telegram Notifier Engine   │                                  │
   │ (bot/telegram_notifier.py)  ├──────────────────────────────────┤ Dispatches Exact Step-by-Step
   └─────────────────────────────┘                                  │ Order Checklists
                  ▲                                                 ▼
                  │                              ┌──────────────────────────────────────┐
                  │ Git Push                     │    User Mobile Telegram Alerts       │
   ┌──────────────┴──────────────┐               │   (Zerodha / Groww / Kotak Neo)      │
   │  Streamlit Cloud Dashboard  │               └──────────────────────────────────────┘
   │   (production branch live)  │
   └─────────────────────────────┘
```

---

## 3. Core Quantitative Trading Mechanics & Unified Risk Parameters

To eliminate parameter contradictions across the engine, dashboard, and paper tracker, all execution parameters are anchored to canonical configuration constants in `config.py` (`TOURNAMENT_CONFIG`):

```
   [ TARGET: +12.0% ]   ▲
                        │  +12.0% Velocity Liquidation (Freed Capital for Next Setup)
                        │
   [ BREAKEVEN: +5.0% ] ── When +5.0% Gain Touched ➔ Stop Trailed to Entry + 0.6%
                        │  (0.6% Buffer = 0.34% Friction + 0.25% Slippage Cushion)
                        │
   [ ENTRY PIVOT ]     ── 0.0% Breakout Execution (+0.25% Slippage Modeled)
                        │
   [ STOP LOSS: -4.0% ] ▼ -4.0% Base Hard Floor (-0.8% Total Portfolio Risk per Trade)
```

### 3.1. Strict 5-Slot Zero-Leverage Architecture
- **Corpus Limit**: Exactly ₹1,00,000 simulated capital per track.
- **Position Sizing**: Strictly capped at **5 slots $\times$ ₹20,000 (20.0% capital per position)**.
- **Slot Capacity Guard**: If 5 slots are already occupied, any newly triggered setup **cannot fill**. It is placed in `PENDING_SLOT_CAPACITY` status until an active position exits via Target, Stop Loss, or 72H Velocity Kill.
- **No Margin Borrowing**: `capital_deployed` cannot exceed `capital` under any circumstance.

### 3.2. Asymmetric Risk-Reward Mechanics
1. **+5.0% Breakeven Arming**: When CMP or Day High touches $+5.0\%$ above the fill price, the stop loss is automatically trailed to `Entry Price * 1.006` (+0.6%). The $+0.6\%$ buffer covers round-trip statutory friction (~0.34%) plus exit slippage (~0.25%).
2. **Overnight Gap Reality**: The system explicitly acknowledges that a trailing stop does not guarantee zero loss in the event of an overnight gap-down past the stop level.
3. **+12.0% Target Velocity Exit**: Liquidates the position into institutional breakout strength, locking gains and recycling cash.
4. **-4.0% Base Capital Defense Floor**: Caps maximum trade risk at $4.0\%$ ($0.8\%$ total portfolio risk on a 5-slot architecture).
5. **72H Velocity Kill**: If a position fails to gain $>+1.5\%$ within 3 trading sessions (72 market hours), it is flagged as **Dead Money** and liquidated at CMP to reallocate cash.
6. **7-Session Time Horizon**: Hard time-stop after 7 trading days to enforce rotational compounding.

### 3.3. Exchange Realism & Fill Modeling
- **Slippage Assumption**: An explicit **0.25% slippage buffer** is deducted on every breakout entry and stop exit.
- **Market Hours Enforcement**: Orders can **only** execute between 09:15 AM and 03:30 PM IST on official NSE trading days.
- **Evening Scans Locked**: Setups shortlisted at 04:30 PM sit in `PENDING_BREAKOUT_TRIGGER` state and **cannot execute until the next day's live session**.
- **Chasing Ceilings**: If a stock gaps up $>+2.5\%$ above the pivot trigger at open, it is marked `ABORTED_EXTENDED_GAP` to prevent buying extended tops.
- **Gap-Down Shields**: If a stock opens $<-1.5\%$ lower on Track A, it is aborted (`ABORTED_GAP_DOWN`) to preserve 100% of capital.

---

## 4. Statutory Indian Delivery Friction Cost Modeling

Every simulated trade in the system deducts statutory Indian delivery charges via `data/costs.py`:

| Friction Component | Rate / Charge | Application |
| :--- | :--- | :--- |
| **STT (Securities Transaction Tax)** | 0.10% | Both Buy & Sell sides on Delivery Turnover |
| **Exchange Turnover Fee (NSE)** | 0.00325% | Both Buy & Sell sides |
| **SEBI Turnover Charges** | ₹10 per Crore (0.0001%) | Both Buy & Sell sides |
| **Stamp Duty** | 0.015% (₹1,500 per Crore) | Buy side only |
| **GST (Goods & Services Tax)** | 18.0% | Applied on (Brokerage + Exchange Fees + SEBI Fees) |
| **DP Charges (Depository Participant)** | ₹15.93 flat per scrip | Sell side only (CDSL/NSDL) |
| **Brokerage** | ₹0.00 (Zero for Cash Delivery) | Zerodha / AngelOne / Kotak Neo standard |
| **Execution Slippage** | 0.25% modeled | Entry and Exit price execution |

---

## 5. Live Paper Trading Portfolio Audit

### 🟢 Track A: Option 2 (9:20 AM Open Confirmation)
- **Deployed Capital**: ₹59,641.24 (3/5 Slots Used) | **Cash Free**: ₹40,358.76
- **Floating MTM P&L**: **₹+313.96 (+0.31% on ₹100k, +0.53% on deployed)** | **Closed Trades**: 0

| Ticker | Entry Date | Buy Price | CMP | Target (+12%) | Stop (-4%) | Shares | Capital (INR) | MTM (%) | Net MTM (INR) | Status | Days Held |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BANKINDIA** | 18-Nov-2026 | ₹158.50 | ₹159.28 | ₹177.52 | ₹152.16 | 126 | ₹19,971.00 | +0.49% | ₹+98.28 | Active | 2 days |
| **MAHABANK** | 18-Nov-2026 | ₹95.93 | ₹95.99 | ₹107.44 | ₹92.09 | 208 | ₹19,953.44 | +0.06% | ₹+12.48 | Active | 2 days |
| **LICHSGFIN** | 18-Nov-2026 | ₹616.15 | ₹622.50 | ₹690.09 | ₹591.50 | 32 | ₹19,716.80 | +1.03% | ₹+203.20 | Active | 2 days |

---

### 🔵 Track B: Option 3 (GTT Buy-Stop Breakout Trigger)
- **Deployed Capital**: ₹98,172.17 (5/5 Slots Used - 100% Capacity) | **Cash Free**: ₹1,827.83
- **Floating MTM P&L**: **₹-1,003.87 (-1.00% on ₹100k, -1.02% on deployed)** | **Closed Trades**: 0

| Ticker | Sector | Entry Date | Entry Px | CMP | Target (+12%) | Stop (-4%) | Shares | Capital (INR) | MTM (%) | Net MTM (INR) | Pattern |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **HONASA** | FMCG | 18-Nov 15:30 | ₹524.00 | ₹517.80 | ₹586.88 | ₹503.04 | 38 | ₹19,912.00 | -1.18% | ₹-235.60 | `INSTITUTIONAL_BLAST` |
| **SIGNATURE** | Infra | 18-Nov 15:30 | ₹844.00 | ₹835.60 | ₹945.28 | ₹810.24 | 23 | ₹19,412.00 | -1.00% | ₹-193.20 | `INSTITUTIONAL_BLAST` |
| **GMRAIRPORT**| Infra | 18-Nov 15:30 | ₹105.26 | ₹104.50 | ₹117.89 | ₹101.05 | 190 | ₹19,999.40 | -0.72% | ₹-144.40 | `INSTITUTIONAL_IGNITION` |
| **DEEPAKFERT**| Chem | 18-Nov 15:30 | ₹1,460.00 | ₹1,443.70 | ₹1,635.20 | ₹1,401.60 | 13 | ₹18,980.00 | -1.12% | ₹-211.90 | `INSTITUTIONAL_IGNITION` |
| **PNB** | Banking | 18-Nov 15:30 | ₹151.67 | ₹150.00 | ₹169.87 | ₹145.60 | 131 | ₹19,868.77 | -1.10% | ₹-218.77 | `MONSTER_BREAKOUT` |

**Pending GTT Triggers Queued for Slot Capacity (Waiting for Active Trade Exit):**
1. `IDFCFIRSTB.NS` (Pivot: ₹83.71) — Queued
2. `UNIONBANK.NS` (Pivot: ₹209.70) — Queued
3. `CANBK.NS` (Pivot: ₹136.80) — Queued
4. `OBEROIRLTY.NS` (Pivot: ₹1,835.00) — Queued
5. `DELHIVERY.NS` (Pivot: ₹465.80) — Awaiting Breakout
6. `TATAINVEST.NS` (Pivot: ₹618.35) — Awaiting Breakout
7. `GRASIM.NS` (Pivot: ₹3,239.00) — Awaiting Breakout

---

### ⚡ Track C: Benchmark Velocity Sniper
- **Deployed Capital**: ₹59,245.50 (3/5 Slots Used) | **Cash Free**: ₹40,754.50
- **Floating MTM P&L**: **₹-599.80 (-0.60% on ₹100k, -1.01% on deployed)** | **Closed Trades**: 0

| Ticker | Entry Date | Buy Price | CMP | Target (+12%) | Stop (-4%) | Shares | Capital (INR) | MTM (%) | Net MTM (INR) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **HONASA** | 18-Nov 15:30 | ₹524.00 | ₹517.80 | ₹586.88 | ₹503.04 | 38 | ₹19,912.00 | -1.18% | ₹-235.60 |
| **SIGNATURE** | 18-Nov 15:30 | ₹844.00 | ₹835.60 | ₹945.28 | ₹810.24 | 23 | ₹19,412.00 | -1.00% | ₹-193.20 |
| **UNIONBANK** | 19-Nov (Intraday) | ₹209.70 | ₹207.90 | ₹234.86 | ₹201.31 | 95 | ₹19,921.50 | -0.86% | ₹-171.00 |

---

## 6. Real-Time Cloud Infrastructure & Automation

### 6.1. 2-Relay GitHub Actions Cloud Architecture
To prevent unexpected termination by GitHub's **360-minute hard platform timeout**, the cloud runner workflow (`.github/workflows/market_session_hawk.yml`) operates across two scheduled relays:
- **Relay 1 (Morning Session)**: Boots at **03:40 UTC (09:10 AM IST)**. Runs continuous 20-second tick surveillance through 12:30 PM IST (runtime: 3 hours 20 mins, well below the 360-min cap). Commits midday checkpoint to Git.
- **Relay 2 (Afternoon Session)**: Boots at **07:00 UTC (12:30 PM IST)**. Pulls latest data and runs until 03:35 PM IST (runtime: 3 hours 05 mins). Performs 03:30 PM closing audit, dispatches Telegram Daily Recap, and pushes updated tracker data to `master` and `production`.

### 6.2. Telegram Notification Engine
- **Module**: `bot/telegram_notifier.py`
- **Native Telegram Bot API**: Direct HTTPS endpoint (`https://api.telegram.org/bot<TOKEN>/sendMessage`). Zero third-party gateway dependencies.
- **Actionable Execution Plan**: Every fill alert dispatches specific step-by-step instructions for Zerodha, Groww, and Kotak Neo (CNC Delivery order type, Limit buffer, quantity, target GTT, stop loss).

---

## 7. Verification & Automated Test Suite Audit

The engine is validated with an automated test suite enforcing risk consistency, slot limits, zero leverage, slippage, and calendar rules. **32 out of 32 tests pass cleanly (100% Green)**:

```
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-8.4.1, pluggy-1.6.0
collected 32 items

tests/test_apex_engine.py::test_apex_universe_contains_high_beta_leaders PASSED [  3%]
tests/test_apex_engine.py::test_ticker_to_sector_mapping PASSED          [  6%]
tests/test_apex_engine.py::test_apex_3slot_position_sizing PASSED        [  9%]
tests/test_apex_engine.py::test_apex_5slot_position_sizing PASSED        [ 12%]
tests/test_apex_engine.py::test_leading_sectors_returns_valid_list PASSED [ 15%]
tests/test_dashboard_integrity.py::test_config_loads_properly PASSED     [ 18%]
tests/test_dashboard_integrity.py::test_app_syntax_compiles PASSED       [ 21%]
tests/test_dashboard_integrity.py::test_market_calendar_status PASSED    [ 25%]
tests/test_dashboard_integrity.py::test_broker_configuration_check PASSED [ 28%]
tests/test_dashboard_integrity.py::test_format_display_date_behavior PASSED [ 31%]
tests/test_dual_tracker.py::test_tracker_structure PASSED                [ 34%]
tests/test_dual_tracker.py::test_compute_dual_summary_empty PASSED       [ 37%]
tests/test_dual_tracker.py::test_compute_dual_summary_with_closed_trades PASSED [ 40%]
tests/test_dual_tracker.py::test_can_trigger_breakout_market_rules PASSED [ 43%]
tests/test_dual_tracker.py::test_log_today_picks_sets_shortlist_and_fill_dates PASSED [ 46%]
tests/test_dual_tracker.py::test_option_3_target_and_stop_anchored_to_pivot_trigger PASSED [ 50%]
tests/test_dual_tracker.py::test_days_held_uses_trading_days PASSED      [ 53%]
tests/test_dual_tracker.py::test_max_slots_and_capital_enforcement_prevents_leverage PASSED [ 56%]
tests/test_dual_tracker.py::test_slippage_applied_on_entry_and_breakeven_lock_buffer PASSED [ 59%]
tests/test_indian_friction_costs.py::test_profitable_trade_friction PASSED [ 62%]
tests/test_indian_friction_costs.py::test_losing_trade_friction PASSED   [ 65%]
tests/test_indian_friction_costs.py::test_zero_quantity_or_flat_trade PASSED [ 68%]
tests/test_portfolio_manager.py::test_upsert_and_remove_holding PASSED   [ 71%]
tests/test_portfolio_manager.py::test_portfolio_summary_structure PASSED [ 75%]
tests/test_telegram_notifier.py::test_telegram_notifier_not_configured PASSED [ 78%]
tests/test_telegram_notifier.py::test_telegram_notifier_send_message_success PASSED [ 81%]
tests/test_telegram_notifier.py::test_telegram_notifier_notify_breakout_fill PASSED [ 84%]
tests/test_telegram_notifier.py::test_telegram_notifier_notify_breakeven_lock PASSED [ 87%]
tests/test_telegram_notifier.py::test_telegram_notifier_notify_target_hit PASSED [ 90%]
tests/test_telegram_notifier.py::test_telegram_notifier_notify_stop_loss_hit PASSED [ 93%]
tests/test_telegram_notifier.py::test_telegram_notifier_notify_velocity_kill PASSED [ 96%]
tests/test_telegram_notifier.py::test_telegram_notifier_notify_live_buy_signal PASSED [100%]

======================= 32 passed, 1 warning in 10.09s ========================
```

---

## 8. Regulatory Disclosure & Operational Guidelines

- **Personal Quantitative Research Only**: TraderAI is a personal automated software framework designed for educational and algorithmic research purposes.
- **SEBI Regulations**: The system does not offer public investment advice, research analyst reports (SEBI RA Regulations, 2014), or portfolio management services (SEBI PMS Regulations). If trade alerts or shortlists are ever shared externally with third parties, appropriate SEBI registrations and disclaimers are legally mandatory.
- **Capital Risk**: Equities and market instruments carry market risk. Past backtested or paper performance does not guarantee future live returns.
