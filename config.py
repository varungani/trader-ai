"""
TraderAI - Central Configuration
Loads environment variables and defines all constants.
Open-source stack: yfinance, RSS news, VADER, ta, SQLite, Streamlit.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys (Cloud LLMs & data fallbacks) ─────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# ─── Kotak Neo Broker (read-only) ─────────────────────────────
KOTAK_CONSUMER_KEY = os.getenv("KOTAK_CONSUMER_KEY", "")
KOTAK_CONSUMER_SECRET = os.getenv("KOTAK_CONSUMER_SECRET", "")
KOTAK_MOBILE = os.getenv("KOTAK_MOBILE", "")
KOTAK_UCC = os.getenv("KOTAK_UCC", "")
KOTAK_MPIN = os.getenv("KOTAK_MPIN", "")
# Base32 secret from authenticator app — preferred for non-interactive sync
KOTAK_TOTP_SECRET = os.getenv("KOTAK_TOTP_SECRET", "")

# ─── Telegram Interactive Bot & Real-Time Alerts ─────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ALERT_CHECK_INTERVAL_MINS = int(os.getenv("ALERT_CHECK_INTERVAL_MINS", "15"))

# ─── Mutual Fund Scheme Codes (AMFI) ─────────────────────────
MF_SCHEME_CODES = [
    code.strip()
    for code in os.getenv("MF_SCHEME_CODES", "").split(",")
    if code.strip()
]

# ─── Timeframe Definitions (Pure Swing Trading Focus - Max 1 Month) ────────
DEFAULT_TIMEFRAME = "short_term"

TIMEFRAMES = {
    "short_term": {
        "label": "⚡ Swing Trading (Max 1 Month)",
        "horizon": "3 to 21 trading sessions (Max 1 Month)",
        "min_days": 1,
        "max_days": 21,
        "description": "Quick momentum breakouts, 52W high proximity, RSI sweet spot (60-75), volume surges, and catalyst swings",
        "weights": {
            "technical": 0.45,   # Core driver: Price action, RVOL volume shock, Stage-2 trend, VCP contraction
            "sentiment": 0.20,   # 3-tier NLP catalyst scoring
            "event_risk": 0.15,  # Earnings and corporate event safety gate
            "macro": 0.10,       # Market regime and sector relative velocity
            "fundamental": 0.10, # Solvency baseline
        },
    },
    "mid_term": {
        "label": "⚡ Swing Trading (Max 1 Month)",
        "horizon": "3 to 21 trading sessions (Max 1 Month)",
        "min_days": 1,
        "max_days": 21,
        "description": "Quick momentum breakouts, 52W high proximity, RSI sweet spot (60-75), volume surges, and catalyst swings",
        "weights": {
            "technical": 0.40,
            "sentiment": 0.20,
            "event_risk": 0.15,
            "macro": 0.15,
            "fundamental": 0.10,
        },
    },
    "long_term": {
        "label": "⚡ Swing Trading (Max 1 Month)",
        "horizon": "3 to 21 trading sessions (Max 1 Month)",
        "min_days": 1,
        "max_days": 21,
        "description": "Quick momentum breakouts, 52W high proximity, RSI sweet spot (60-75), volume surges, and catalyst swings",
        "weights": {
            "technical": 0.40,
            "sentiment": 0.20,
            "event_risk": 0.15,
            "macro": 0.15,
            "fundamental": 0.10,
        },
    },
}

# ─── Risk Management (Pure Swing & 1-Month Max Hold Architecture) ───────────────
RISK_CONFIG = {
    "max_position_pct": 0.25,      # 25% concentrated allocation into top 4 apex leaders
    "max_sector_pct": 0.50,
    "default_stop_loss_pct": 0.07, # 7.0% Daily Close stop loss (gives swing room to breathe, prevents intraday wick sweep)
    "default_target_pct": 0.20,    # Explosive +20% 1-Month profit target
    "risk_per_trade_pct": 0.02,
    "max_open_positions": 4,       # High-conviction focus on top 4 apex names
    "min_position_size_rupees": 5000.0, # Minimum ticket size to prevent friction bleed
    "min_score_to_buy": 65,        # Fortress Buy Threshold (65+ required for BUY with strict trend/sector gates)
    "max_score_to_sell": 40,
    "hold_band_low": 40,
    "hold_band_high": 65,
    "max_portfolio_heat": 0.10,    # sum of open risk ≤ 10% of capital
    "max_holding_sessions": 21,    # Strict 1-Month Ceiling (21 market sessions / ~30 calendar days)
    "max_holding_calendar_days": 30, # 30 calendar days maximum holding period
    "stop_loss_basis": "daily_close", # Daily close basis prevents getting wicked out by intraday volatility
}

# ─── Sector Relative Strength Dynamic Capital Allocation Multipliers ─────────
# Deploys more capital into stocks belonging to sectors leading Nifty 50.
SECTOR_ALLOCATION_MULTIPLIERS = {
    "LEADING": 1.35,        # +35% capital boost for sectors leading Nifty (> +2.0% RS)
    "OUTPERFORMING": 1.15, # +15% boost for outperforming sectors (+0.75% to +2.0% RS)
    "NEUTRAL": 1.00,        # Standard baseline equal weight (-0.75% to +0.75% RS)
    "LAGGING": 0.75,        # -25% reduced capital allocation (-1.75% to -0.75% RS)
    "SEVERE_DRAG": 0.50,    # -50% defensive allocation for severe drag (< -1.75% RS)
}
MIN_DELIVERY_TICKET_RUPEES = 3500.0  # Floor to keep flat ₹15.93 CDSL DP fee <= 0.45% of position

# ─── Portfolio balance targets (Pure Swing Trading Focus) ─────
ALLOCATION_PROFILES = {
    "balanced": {
        "label": "Balanced Swing (Recommended)",
        "description": "5 focused swing picks, max 20% capital per stock, 2:1 R:R target",
        "cash_pct": 0.10,
        "stability_pct": 0.30,   # defensive large-cap swings
        "growth_pct": 0.40,      # high-momentum breakouts
        "opportunistic_pct": 0.20,  # catalyst & earnings swing plays
        "timeframe_targets": {
            "short_term": 1.0,
            "mid_term": 0.0,
            "long_term": 0.0,
        },
        "max_high_risk_pct": 0.20,
        "min_low_risk_pct": 0.30,
    },
    "conservative": {
        "label": "Defensive Swing (Capital Preservation)",
        "description": "Lower-volatility large-cap swing setups, tighter stops, 20% cash cushion",
        "cash_pct": 0.20,
        "stability_pct": 0.50,
        "growth_pct": 0.25,
        "opportunistic_pct": 0.05,
        "timeframe_targets": {
            "short_term": 1.0,
            "mid_term": 0.0,
            "long_term": 0.0,
        },
        "max_high_risk_pct": 0.10,
        "min_low_risk_pct": 0.50,
    },
    "growth": {
        "label": "Aggressive Swing (High Momentum)",
        "description": "Maximum momentum breakout runners and high-beta sector leaders",
        "cash_pct": 0.05,
        "stability_pct": 0.15,
        "growth_pct": 0.50,
        "opportunistic_pct": 0.30,
        "timeframe_targets": {
            "short_term": 1.0,
            "mid_term": 0.0,
            "long_term": 0.0,
        },
        "max_high_risk_pct": 0.35,
        "min_low_risk_pct": 0.15,
    },
    "apex_3slot": {
        "label": "⚡ Apex High-Velocity (3 Slots - 33.3% Each)",
        "description": "Ultra-concentrated momentum compounding: 3 slots (33.3% capital each), strict 1-month ceiling (21 sessions), +20% to +25% profit target, daily-close 7% stop.",
        "cash_pct": 0.00,
        "stability_pct": 0.00,
        "growth_pct": 0.70,
        "opportunistic_pct": 0.30,
        "timeframe_targets": {
            "short_term": 1.0,
            "mid_term": 0.0,
            "long_term": 0.0,
        },
        "max_high_risk_pct": 0.50,
        "min_low_risk_pct": 0.00,
        "max_open_positions": 3,
        "max_position_pct": 0.333,
    },
}

DEFAULT_ALLOCATION_PROFILE = "balanced"

# ─── Monthly capital (stocks + MF SIP) ────────────────────────
# Change via .env when income grows — defaults match your 10k + 10k plan.
MONTHLY_STOCK_BUDGET = float(os.getenv("MONTHLY_STOCK_BUDGET", "10000"))
MONTHLY_MF_BUDGET = float(os.getenv("MONTHLY_MF_BUDGET", "10000"))

# Small-capital aware defaults (₹10k/mo stocks -> 3 concentrated high-conviction positions)
SMALL_CAPITAL_CONFIG = {
    "max_new_stock_names_per_month": int(os.getenv("MAX_NEW_STOCKS_PER_MONTH", "3")),
    "min_stock_ticket": float(os.getenv("MIN_STOCK_TICKET", "2000")),
    "max_pct_per_name": float(os.getenv("MAX_PCT_PER_NAME_MONTHLY", "0.35")),
    "max_concurrent_positions": int(os.getenv("MAX_CONCURRENT_POSITIONS", "3")),
}

# Screener defaults
DEFAULT_UNIVERSE_PRESET = os.getenv("UNIVERSE_PRESET", "nifty500")  # nifty50|nifty100|nifty500|midcap|extended|all
SCREEN_TOP_N = int(os.getenv("SCREEN_TOP_N", "20"))

# ─── Stock universes (Yahoo .NS) — not limited to Nifty 50 ────
NIFTY50_STOCKS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    "SUNPHARMA.NS", "BAJFINANCE.NS", "NESTLEIND.NS", "ULTRACEMCO.NS",
    "HCLTECH.NS", "NTPC.NS", "POWERGRID.NS", "M&M.NS", "TRENT.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "TECHM.NS", "BAJAJFINSV.NS", "TATASTEEL.NS",
    "ONGC.NS", "JSWSTEEL.NS", "COALINDIA.NS", "BPCL.NS", "DRREDDY.NS",
    "DIVISLAB.NS", "BRITANNIA.NS", "CIPLA.NS", "EICHERMOT.NS", "APOLLOHOSP.NS",
    "HEROMOTOCO.NS", "INDUSINDBK.NS", "GRASIM.NS", "SBILIFE.NS", "HDFCLIFE.NS",
    "BAJAJ-AUTO.NS", "TATACONSUM.NS", "HINDALCO.NS", "UPL.NS", "WIPRO.NS",
    "BEL.NS",
]

# Nifty Next 50-style liquid large/mid names (approx; for scanning breadth)
NIFTY_NEXT50_STOCKS = [
    "ABB.NS", "AMBUJACEM.NS", "BANKBARODA.NS", "BOSCHLTD.NS", "CANBK.NS",
    "CHOLAFIN.NS", "COLPAL.NS", "DABUR.NS", "DLF.NS", "GAIL.NS",
    "GODREJCP.NS", "HAVELLS.NS", "HAL.NS", "ICICIGI.NS", "ICICIPRULI.NS",
    "INDIGO.NS", "NAUKRI.NS", "IOC.NS", "IRCTC.NS", "JINDALSTEL.NS",
    "KPITTECH.NS", "LUPIN.NS", "MFSL.NS", "NHPC.NS", "NMDC.NS",
    "OFSS.NS", "PAGEIND.NS", "PERSISTENT.NS", "PIDILITIND.NS", "POLYCAB.NS",
    "PFC.NS", "PNB.NS", "RECLTD.NS", "SAIL.NS", "SIEMENS.NS",
    "SRF.NS", "SHREECEM.NS", "TORNTPHARM.NS", "BHARATFORG.NS", "TVSMOTOR.NS",
    "UNITDSPR.NS", "VBL.NS", "VEDL.NS", "POLICYBZR.NS", "ZYDUSLIFE.NS",
    "ATGL.NS", "AUBANK.NS", "BERGEPAINT.NS", "CONCOR.NS", "CUMMINSIND.NS",
]

# Liquid mid/small-ish set for opportunity sleeve (still reasonably tradeable)
MIDCAP_LIQUID_STOCKS = [
    "DIXON.NS", "KALYANKJIL.NS", "MAXHEALTH.NS", "SOLARINDS.NS", "SUZLON.NS",
    "TATAPOWER.NS", "TIINDIA.NS", "VOLTAS.NS", "ASHOKLEY.NS", "AUROPHARMA.NS",
    "BALKRISIND.NS", "BHEL.NS", "BIOCON.NS", "COFORGE.NS", "CROMPTON.NS",
    "CAMPUS.NS", "DELHIVERY.NS", "FEDERALBNK.NS", "FORTIS.NS", "GLENMARK.NS",
    "HDFCAMC.NS", "IDEA.NS", "INDHOTEL.NS", "JSWENERGY.NS", "LICI.NS",
    "MOTHERSON.NS", "MPHASIS.NS", "MUTHOOTFIN.NS", "NYKAA.NS", "OBEROIRLTY.NS",
    "PAYTM.NS", "POLICYBZR.NS", "PRESTIGE.NS", "SJVN.NS", "SONACOMS.NS",
    "SUPREMEIND.NS", "SYNGENE.NS", "TATAELXSI.NS", "UNIONBANK.NS", "YESBANK.NS",
]

# Dedicated Small-Cap Momentum Rockets (< ₹15,000 Cr Market Cap & High Growth Potential)
SMALLCAP_ROCKETS_STOCKS = [
    "COCHINSHIP.NS", "GRSE.NS", "IREDA.NS", "HUDCO.NS", "NBCC.NS", 
    "IRFC.NS", "RVNL.NS", "RAILTEL.NS", "TITAGARH.NS", "JWL.NS", 
    "TEJASNET.NS", "NETWEB.NS", "DATAPATTNS.NS", "MOTISONS.NS", "TARC.NS", 
    "ANANDRATHI.NS", "POONAWALLA.NS", "APARINDS.NS", "KEC.NS", "INOXWIND.NS",
    "SJVN.NS", "BBOX.NS", "KAYNES.NS", "CAMPUS.NS", "KALYANKJIL.NS"
]

# High-Velocity Momentum & Monster Runner Universe (Expanded Top 80+ Indian Leaders)
HIGH_BETA_APEX_STOCKS = [
    "TRENT.NS", "DIXON.NS", "KAYNES.NS", "BSE.NS", "CDSL.NS", 
    "ANGELONE.NS", "MAZDOCK.NS", "HAL.NS", "BEL.NS", "COFORGE.NS", 
    "PERSISTENT.NS", "POLYCAB.NS", "SOLARINDS.NS", "SUZLON.NS", "BHARTIARTL.NS", 
    "BAJAJ-AUTO.NS", "INDHOTEL.NS", "MCX.NS", "VOLTAS.NS", "MOTILALOFS.NS", 
    "KPITTECH.NS", "OFSS.NS", "BBOX.NS", "BHARATFORG.NS", "JSWENERGY.NS", 
    "TATAELXSI.NS", "TATAPOWER.NS", "TIINDIA.NS", "PRESTIGE.NS", "MAXHEALTH.NS", 
    "KALYANKJIL.NS", "HDFCAMC.NS", "MPHASIS.NS", "AUROPHARMA.NS", "GLENMARK.NS", 
    "FORTIS.NS", "FEDERALBNK.NS", "CAMPUS.NS", "DELHIVERY.NS", "ASHOKLEY.NS", 
    "BALKRISIND.NS", "BHEL.NS", "BIOCON.NS", "CROMPTON.NS", "LICI.NS", 
    "MUTHOOTFIN.NS", "NYKAA.NS", "OBEROIRLTY.NS", "PAYTM.NS", "POLICYBZR.NS", 
    "SJVN.NS", "SONACOMS.NS", "SUPREMEIND.NS", "SYNGENE.NS", "UNIONBANK.NS", 
    "YESBANK.NS", "TECHM.NS", "HCLTECH.NS", "RECLTD.NS", "PFC.NS", 
    "NHPC.NS", "NMDC.NS", "CUMMINSIND.NS", "DLF.NS", "LUPIN.NS", 
    "TORNTPHARM.NS", "ABB.NS", "SIEMENS.NS", "HAVELLS.NS", "CANBK.NS", 
    "BANKBARODA.NS", "PNB.NS", "CHOLAFIN.NS", "JINDALSTEL.NS", "VEDL.NS", 
    "SAIL.NS", "IRCTC.NS", "NAUKRI.NS", "COCHINSHIP.NS", "GRSE.NS", 
    "IREDA.NS", "HUDCO.NS", "RVNL.NS", "NETWEB.NS", "TITAGARH.NS", "INOXWIND.NS"
]

HIGH_VELOCITY_STOCKS = HIGH_BETA_APEX_STOCKS
HIGH_BETA_ROCKETS = HIGH_BETA_APEX_STOCKS

# Liquid Index, Commodity & Sector ETFs (ideal for cash stability, zero day-trading delivery)
ETF_COMMODITY_STOCKS = [
    "GOLDBEES.NS",    # Nippon India Gold ETF (physical gold)
    "SILVERBEES.NS",  # Nippon India Silver ETF (physical silver)
    "NIFTYBEES.NS",   # Nippon India Nifty 50 ETF
    "JUNIORBEES.NS",  # Nippon India Nifty Next 50 ETF
    "BANKBEES.NS",    # Nippon India Bank ETF
    "ITBEES.NS",      # Nippon India IT ETF
    "PHARMABEES.NS",  # Nippon India Pharma ETF
    "AUTOBEES.NS",    # Nippon India Auto ETF
    "CPSEETF.NS",     # CPSE PSU ETF
    "MON100.NS",      # Motilal Oswal Nasdaq 100 ETF (global tech)
    "MID150BEES.NS",  # Nippon India Nifty Midcap 150 ETF
]

# Load official NSE Nifty 500 constituents from cached JSON
_NIFTY500_JSON = os.path.join(os.path.dirname(__file__), "data", "nifty500_symbols.json")
NIFTY500_STOCKS = []
if os.path.exists(_NIFTY500_JSON):
    try:
        import json
        with open(_NIFTY500_JSON, "r", encoding="utf-8") as _f:
            NIFTY500_STOCKS = json.load(_f).get("symbols", [])
    except Exception:
        NIFTY500_STOCKS = []

UNIVERSE_PRESETS = {
    "high_beta_apex": HIGH_BETA_APEX_STOCKS,
    "high_beta_rockets": HIGH_BETA_APEX_STOCKS,
    "smallcap_rockets": SMALLCAP_ROCKETS_STOCKS,
    "nifty500": NIFTY500_STOCKS if NIFTY500_STOCKS else list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS + MIDCAP_LIQUID_STOCKS)),
    "nifty50": NIFTY50_STOCKS,
    "nifty100": list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS)),
    "midcap": MIDCAP_LIQUID_STOCKS,
    "etfs": ETF_COMMODITY_STOCKS,
    "extended": list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS + MIDCAP_LIQUID_STOCKS + ETF_COMMODITY_STOCKS)),
    "all": NIFTY500_STOCKS if NIFTY500_STOCKS else list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS + MIDCAP_LIQUID_STOCKS + ETF_COMMODITY_STOCKS)),
}

# ─── Commodity Tickers (yfinance) ─────────────────────────────
COMMODITIES = {
    "gold": "GC=F",
    "silver": "SI=F",
    "crude_oil": "CL=F",
    "natural_gas": "NG=F",
}

# ─── Index Tickers ────────────────────────────────────────────
INDICES = {
    "nifty50": "^NSEI",
    "sensex": "^BSESN",
    "nifty_bank": "^NSEBANK",
    "nifty_it": "^CNXIT",
    "nifty_pharma": "^CNXPHARMA",
}

# ─── Sector Mapping ──────────────────────────────────────────
SECTOR_MAP = {
    "IT": [
        "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
        "COFORGE.NS", "MPHASIS.NS", "PERSISTENT.NS", "LTIM.NS", "TATAELXSI.NS",
        "KPITTECH.NS", "OFSS.NS", "BBOX.NS"
    ],
    "Banking": [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS", "INDUSINDBK.NS",
        "FEDERALBNK.NS", "KARURVYSYA.NS", "AUBANK.NS", "BANDHANBNK.NS", "IDFCFIRSTB.NS",
        "PNB.NS", "BANKBARODA.NS", "CANBK.NS", "UNIONBANK.NS"
    ],
    "Pharma": [
        "SUNPHARMA.NS", "DRREDDY.NS", "DIVISLAB.NS", "CIPLA.NS", "APOLLOHOSP.NS",
        "LUPIN.NS", "AUROPHARMA.NS", "GLENMARK.NS", "TORNTPHARM.NS", "ZYDUSLIFE.NS", "BIOCON.NS"
    ],
    "Auto": [
        "MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "HEROMOTOCO.NS",
        "TVSMOTOR.NS", "ASHOKLEY.NS", "BHARATFORG.NS", "BALKRISIND.NS", "MOTHERSON.NS", "SONACOMS.NS"
    ],
    "Energy": [
        "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "NTPC.NS", "POWERGRID.NS", "COALINDIA.NS",
        "PETRONET.NS", "PTCIL.NS", "TATAPOWER.NS", "JSWENERGY.NS", "GAIL.NS", "IOC.NS", "SUZLON.NS"
    ],
    "FMCG": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS", "DABUR.NS", "COLPAL.NS", "VBL.NS", "GODREJCP.NS"],
    "Metals": ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "JINDALSTEL.NS", "SAIL.NS", "NMDC.NS", "VEDL.NS"],
    "Infra": ["LT.NS", "ADANIENT.NS", "ADANIPORTS.NS", "GRASIM.NS", "ULTRACEMCO.NS", "BEL.NS", "HAL.NS", "DLF.NS", "OBEROIRLTY.NS", "PRESTIGE.NS"],
    "Finance": ["BAJFINANCE.NS", "BAJAJFINSV.NS", "SBILIFE.NS", "HDFCLIFE.NS", "PNBHOUSING.NS", "CHOLAFIN.NS", "MUTHOOTFIN.NS", "RECLTD.NS", "PFC.NS"],
    "Consumer": ["TITAN.NS", "ASIANPAINT.NS", "CUPID.NS", "CPPLUS.NS", "HAVELLS.NS", "POLYCAB.NS", "DIXON.NS", "VOLTAS.NS"],
}

# Reverse lookup: ticker -> sector
TICKER_TO_SECTOR = {
    ticker: sector
    for sector, tickers in SECTOR_MAP.items()
    for ticker in tickers
}

# ─── Open-source RSS news feeds ───────────────────────────────
RSS_FEEDS = {
    "market": [
        "https://www.moneycontrol.com/rss/latestnews.xml",
        "https://www.moneycontrol.com/rss/business.xml",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.livemint.com/rss/markets",
        "https://news.google.com/rss/search?q=NSE+BSE+Nifty+stock+market+India&hl=en-IN&gl=IN&ceid=IN:en",
    ],
    "policy": [
        "https://economictimes.indiatimes.com/news/economy/policy/rssfeeds/6871117.cms",
        "https://www.livemint.com/rss/economy",
        "https://news.google.com/rss/search?q=RBI+policy+interest+rate+SEBI+regulation+India&hl=en-IN&gl=IN&ceid=IN:en",
    ],
    "geopolitics": [
        "https://www.thehindu.com/news/international/feeder/default.rss",
        "https://economictimes.indiatimes.com/news/defence/rssfeeds/66269871.cms",
        "https://news.google.com/rss/search?q=geopolitics+tariff+sanctions+trade+war+India&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=crude+oil+OPEC+supply+chain+defence+India&hl=en-IN&gl=IN&ceid=IN:en",
    ],
    "google_news_india_markets": [
        "https://news.google.com/rss/search?q=India+stock+market+OR+NSE+OR+BSE&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=RBI+OR+SEBI+OR+FDI+OR+budget+India&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=sanctions+OR+geopolitics+OR+tariff+India&hl=en-IN&gl=IN&ceid=IN:en",
    ],
}

# Event keyword taxonomy for open-source event-risk scoring
EVENT_KEYWORDS = {
    "sanctions": {
        "weight": -25,
        "terms": [
            "sanction", "sanctions", "ofac", "embargo", "blacklist", "export ban",
            "trade ban", "secondary sanctions",
        ],
    },
    "regulation": {
        "weight": -12,
        "terms": [
            "sebi probe", "sebi order", "penalty", "fine", "raid", "investigation",
            "regulatory action", "compliance failure", "showcause", "show-cause",
            "ban on", "trading ban",
        ],
    },
    "positive_regulation": {
        "weight": 10,
        "terms": [
            "cleared", "approval", "approves", "licence", "license granted",
            "policy boost", "incentive", "pli scheme", "tax cut",
        ],
    },
    "government_investment": {
        "weight": 12,
        "terms": [
            "capex", "infrastructure push", "government award", "order win",
            "mou signed", "fdi inflow", "sovereign fund", "psu investment",
        ],
    },
    "leadership": {
        "weight": -8,
        "terms": [
            "ceo resigns", "ceo quits", "md resigns", "promoter exit",
            "management change", "sudden resignation", "keyman risk",
        ],
    },
    "positive_leadership": {
        "weight": 8,
        "terms": [
            "new ceo", "appoints ceo", "leadership overhaul", "turnaround plan",
            "strategic hire",
        ],
    },
    "stability": {
        "weight": -15,
        "terms": [
            "default", "insolvency", "bankruptcy", "debt restructuring",
            "liquidity crunch", "going concern", "fraud", "accounting irregular",
            "downgrade",
        ],
    },
    "investor_flow": {
        "weight": 10,
        "terms": [
            "fii buy", "fpi buy", "institutional buying", "stake hike",
            "promoter buying", "buyback", "special dividend",
        ],
    },
    "negative_investor_flow": {
        "weight": -10,
        "terms": [
            "fii sell", "fpi sell", "institutional selling", "stake sale",
            "promoter selling", "pledged shares", "block deal sell",
        ],
    },
    "geopolitics": {
        "weight": -10,
        "terms": [
            "war", "conflict", "missile", "border tension", "tariff",
            "trade war", "blockade", "shipping disruption", "strait",
        ],
    },
    "geopolitics_defence_tailwind": {
        "weight": 18,
        "terms": [
            "defence order", "defense export", "indigenisation", "make in india",
            "strategic alliance", "missile deal", "navy contract", "drdo",
            "hal contract", "defence acquisition", "procurement clearance",
            "warship order", "ammunition order", "defence budget",
        ],
    },
    "global_supply_chain": {
        "weight": 14,
        "terms": [
            "china plus one", "global supply chain", "semiconductor mission",
            "export surge", "free trade agreement", "fta", "us deal", "europe contract",
            "friendshoring", "multinational tieup", "global expansion",
        ],
    },
    "energy_capex": {
        "weight": 14,
        "terms": [
            "green hydrogen", "renewable capex", "solar mission", "ev subsidy",
            "battery manufacturing", "power grid expansion", "nuclear energy",
            "transmission capex",
        ],
    },
    "commodity_margin_tailwind": {
        "weight": 12,
        "terms": [
            "crude fall", "crude drops", "oil slump", "raw material softening",
            "input cost reduction", "margin expansion", "freight rates drop",
        ],
    },
}

# ─── Database / Portfolio Paths ───────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "trader_ai.db")
PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "portfolio", "portfolio.json")
PAPER_WEEK_PATH = os.path.join(os.path.dirname(__file__), "portfolio", "paper_week.json")

# ─── Daily Run Settings ──────────────────────────────────────
DAILY_TOP_PICKS = 10
MARKET_OPEN_TIME = "09:15"
MARKET_CLOSE_TIME = "15:30"
DAILY_RUN_TIME = "08:00"

# User-Agent for RSS fetches
HTTP_USER_AGENT = (
    "TraderAI/1.0 (+https://github.com/local/trader-ai; research; open-source)"
)

# ─── LLM (analyst + separate judge) ───────────────────────────
# backend: ollama | gemini | auto
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
# Separate models — judge should be a different model than analyst when possible
LLM_ANALYST_MODEL = os.getenv("LLM_ANALYST_MODEL", "llama3.2")
LLM_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", "mistral")
LLM_JUDGE_MIN_SCORE = float(os.getenv("LLM_JUDGE_MIN_SCORE", "55"))
LLM_JUDGE_BLOCK_ON_FAIL = os.getenv("LLM_JUDGE_BLOCK_ON_FAIL", "true").lower() in (
    "1", "true", "yes",
)
LLM_MAX_REVIEW = int(os.getenv("LLM_MAX_REVIEW", "6"))

# ─── Paper week (mandatory shadow test before real money) ─────
REAL_MONEY_ENABLED = os.getenv("REAL_MONEY_ENABLED", "false").lower() in ("1", "true", "yes")
PAPER_WEEK_DAYS = int(os.getenv("PAPER_WEEK_DAYS", "7"))
PAPER_WEEK_MIN_TRUST = float(os.getenv("PAPER_WEEK_MIN_TRUST", "60"))
PAPER_WEEK_MIN_TRADES = int(os.getenv("PAPER_WEEK_MIN_TRADES", "3"))

