"""
TraderAI - Stock Market Academy & Beginner's Glossary
Interactive in-UI guide explaining key stock market terms, metrics, and investing concepts in plain English.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
from data.market_calendar import get_market_status, get_upcoming_holidays, get_all_holidays


GLOSSARY_ITEMS = [
    # 0. MARKET TIMINGS & SESSIONS
    {
        "term": "NSE Market Hours (09:15 AM to 03:30 PM IST)",
        "category": "⏰ Timings & Holidays",
        "short_def": "Official live trading hours for Indian stock exchanges (NSE and BSE) from Monday to Friday.",
        "detailed": """
**Standard Trading Session Schedule:**
- **09:00 AM – 09:08 AM:** Pre-open order entry & cancellation
- **09:08 AM – 09:15 AM:** Order matching & opening price discovery
- **09:15 AM – 03:30 PM:** Continuous Normal Market Trading (where all live orders match)
- **03:30 PM – 03:40 PM:** Closing price calculation (weighted average of last 30 minutes)
- **03:40 PM – 04:00 PM:** Post-market trading session
- **Weekends:** Saturday and Sunday are closed.
""",
        "analogy": "Like standard bank or office working hours: 09:15 AM to 03:30 PM is when the bazaar doors are wide open.",
    },
    {
        "term": "The 09:15 – 09:30 AM Rule (Avoid Opening Whiplash)",
        "category": "⏰ Timings & Holidays",
        "short_def": "Beginners should avoid placing market orders in the first 15 minutes of market open due to overnight gap volatility.",
        "detailed": """
When the market opens at 09:15 AM, institutional algorithms and overnight global news cause erratic price swings, wide bid-ask spreads, and emotional gaps.
- **Pro Rule:** Wait until **09:30 AM or 10:00 AM** before placing delivery or swing orders.
- By 10:00 AM, opening volatility settles down, institutional trends become clear, and price slippage is minimal.
""",
        "analogy": "Like entering a crowded train station right as the gates unlock: wait 15 minutes for the initial rush to clear so you can walk calmly without getting pushed.",
    },
    {
        "term": "NSE Trading Holidays & Muhurat Trading",
        "category": "⏰ Timings & Holidays",
        "short_def": "Official declared days when Indian stock exchanges are closed, plus the traditional 1-hour Diwali Muhurat session.",
        "detailed": """
The National Stock Exchange (NSE) and Bombay Stock Exchange (BSE) publish an official list of annual holidays (e.g. Republic Day, Holi, Good Friday, Independence Day, Gandhi Jayanti, Diwali, Christmas).
- On holidays, no equity or ETF trading takes place.
- **Diwali Muhurat Trading:** On Diwali evening (Laxmi Pujan), the exchange opens for a special 1-hour festive trading window where Indian investors buy token shares or Gold ETFs (`GOLDBEES`) for prosperity.
""",
        "analogy": "Like a national bank holiday: all digital bank clearing is paused until the next working day.",
    },

    # 1. BASICS & MARKET STRUCTURE
    {
        "term": "Delivery (CNC) vs Intraday",
        "category": "🔰 Market Basics",
        "short_def": "Buying shares with full cash to own them in your Demat account — zero margin risk, no mandatory same-day sale.",
        "detailed": """
**Delivery Investing (Cash 'n Carry / CNC):**
When you buy shares via Delivery, you pay 100% of the cost using your own cash. The shares are transferred into your permanent Demat locker. You can hold them for days, weeks, months, or decades. 
- **Key advantage:** Zero overnight liquidation risk, zero margin interest, and no pressure. If a fundamentally strong stock drops temporarily, you don't get forced to sell.

**Intraday Trading (MIS):**
Borrowing broker margin to buy and sell on the same day before 3:30 PM. 
- **The harsh reality:** SEBI's official data shows that over 90% of retail intraday & F&O traders lose money consistently.
- **TraderAI's rule:** TraderAI strictly focuses on **Delivery swing and positional investing**. Intraday leverage is strictly disallowed.
""",
        "analogy": "Delivery is like buying a piece of real estate you own outright. Intraday is like renting a room for 6 hours where you're kicked out at sunset whether you're ready or not.",
    },
    {
        "term": "Demat & Trading Account",
        "category": "🔰 Market Basics",
        "short_def": "Demat is your electronic vault holding your shares; Trading account is the vehicle used to buy/sell them.",
        "detailed": """
- **Demat Account (Dematerialized):** Maintained by central depositories (NSDL / CDSL in India). It safely holds your share certificates in electronic format.
- **Trading Account:** Provided by your broker (e.g. Kotak Neo, Zerodha, Groww) to place buy/sell orders on the National Stock Exchange (NSE).
- When you buy a stock in India, the trade follows a **T+1 settlement** cycle: the shares arrive in your Demat locker by the next trading day.
""",
        "analogy": "Trading account is like your debit card/ATM (initiates the transaction); Demat account is your secure locker at the bank where gold is stored.",
    },
    {
        "term": "ETF (Exchange Traded Fund)",
        "category": "🧺 ETFs & Assets",
        "short_def": "A basket of top companies or assets that trades live on the stock exchange like a single share.",
        "detailed": """
An ETF allows you to buy a diversified collection of assets in one simple click at ultra-low expense ratios:
- **NIFTYBEES.NS:** Tracks the Nifty 50 (India's top 50 corporate giants like Reliance, TCS, HDFC Bank). If one company stumbles, 49 others buffer you.
- **BANKBEES.NS:** Tracks India's top 12 banking institutions.
- **GOLDBEES.NS:** 100% backed by physical 24-karat gold bullion. Acts as an emergency shield when equities pull back.
- **MON100.NS:** Tracks the Nasdaq 100 index (top global tech giants: Apple, Microsoft, Nvidia, Google).

**Why Beginners Love ETFs:**
You don't need to guess which individual company will win. You own the entire economy or sector, practically eliminating the risk of a single company going bankrupt.
""",
        "analogy": "Buying an individual stock is like betting on a single cricket player to score a century. Buying an ETF is like betting on Team India to win the tournament.",
    },
    {
        "term": "SIP (Systematic Investment Plan)",
        "category": "🔰 Market Basics",
        "short_def": "Investing a fixed sum of money at regular intervals (e.g. ₹10,000 every month) regardless of market price.",
        "detailed": """
SIP removes emotional guesswork and timing anxiety through **Rupee Cost Averaging**:
- When the market is down, your fixed monthly budget buys **more shares** at a discount.
- When the market is up, your budget buys fewer shares at higher prices.
- Over 3 to 5 years, your average acquisition cost remains low, compounding smoothly through bull and bear cycles.
""",
        "analogy": "Like watering a tree with a steady bucket of water every Sunday instead of dumping a tank once a year.",
    },
    {
        "term": "Limit vs Market Orders",
        "category": "🔰 Market Basics",
        "short_def": "Limit order guarantees your maximum price or better; Market order executes instantly at whatever price is currently offered.",
        "detailed": """
When placing a BUY order on your broker app:
- **Limit Order (Recommended):** You specify the maximum price you will pay (e.g., if LTP is ₹998, you set Limit at ₹1,000). The exchange executes at ₹1,000 or cheaper. This protects you from sudden freak spikes.
- **Market Order:** You tell the exchange "Fill my order immediately at whatever price the seller wants." Great for fast execution in mega-cap ETFs (`NIFTYBEES`), but dangerous during high volatility or in less liquid mid-caps.
""",
        "analogy": "Market order is telling an auto driver 'Charge whatever you want, just take me now.' Limit order is saying 'I will pay ₹100 maximum, take it or leave it.'",
    },
    {
        "term": "GTT (Good-Till-Triggered) & OCO Orders",
        "category": "🛡️ Risk & Protection",
        "short_def": "An automated standing order valid for up to 1 year that triggers your planned stop-loss or profit target automatically.",
        "detailed": """
Non-day-traders cannot watch the screen every minute. **GTT is your automated execution tool:**
- Available in Kotak Neo, Zerodha, Groww, Angel One.
- You place a GTT order right after buying shares under Delivery (CNC).
- **OCO (One-Cancels-Other):** You specify two triggers:
  1. **Planned Stop-Loss Trigger:** -3.5% to -6.0% below your buy price (dynamic ATR-based).
  2. **Target Trigger:** +10% to +15% above your buy price.
- If the stock rallies to +12-15%, it automatically triggers a sell to lock in profit, and cancels the stop-loss.
- If the stock falls to your stop price, it triggers an exit order.
- **Critical Gap Reality:** GTT orders trigger when the threshold price is crossed. However, in an overnight gap-down or lower circuit freeze, execution occurs at the market/open price or when buyers appear. Hence, stops define your *planned loss*, not a guaranteed exit price.
""",
        "analogy": "Like setting a smart thermostat in your home: you don't adjust the knobs every hour; it automatically triggers cooling or heating whenever preset temperature levels are reached.",
    },
    {
        "term": "CDSL TPIN & e-DIS Authorization",
        "category": "🔰 Market Basics",
        "short_def": "A mandatory 6-digit security PIN required by depositories before you can sell delivery shares from your Demat account.",
        "detailed": """
In India, central depositories (CDSL / NSDL) safeguard investor shares so brokers cannot sell them without your explicit knowledge:
- When you tap **SELL** on a Delivery holding in your broker app, a prompt will ask to **Verify CDSL e-DIS**.
- You enter your 6-digit **CDSL TPIN** (sent to your registered mobile and email by CDSL) followed by an SMS OTP.
- **Validity:** Once authorized, it stays valid for the entire trading day across all your holdings.
- *Tip:* You can also enable **DDPI** (Demat Debit and Pledge Instruction) via your broker settings once to permanently bypass the daily TPIN requirement.
""",
        "analogy": "Like two-factor authentication (OTP) on your bank locker: the broker cannot touch or remove your shares without your personal authorization PIN.",
    },

    # 2. RISK MANAGEMENT & EXIT MATH
    {
        "term": "Stop-Loss (Planned Risk)",
        "category": "🛡️ Risk & Protection",
        "short_def": "A predefined safety exit price that defines your planned risk on a swing trade.",
        "detailed": """
A Stop-Loss is the cardinal rule of professional capital preservation.
- Example: You buy a stock at ₹1,000 with a dynamic ATR stop at ₹945 (-5.5%).
- If adverse price action hits ₹945, you exit immediately, cutting your loss at the planned level.
- **Why this is critical:** A -5% loss requires only a +5.3% gain to recover. But if you hold a bad stock down to -50%, you need a massive +100% gain just to get back to even!
- **Gap-Down Awareness:** Stop orders protect against intraday drift, but carrying positions overnight always carries gap risk if market-moving news breaks after market hours.
""",
        "analogy": "A Stop-Loss is like the seatbelt or airbag in your car. You don't plan to crash, but you never drive on the highway without it.",
    },
    {
        "term": "Trailing Stop-Loss & Breakeven Ratchet",
        "category": "🛡️ Risk & Protection",
        "short_def": "An adaptive stop-loss that ratchets upwards as the stock rises, locking in accrued profits.",
        "detailed": """
One of the most common swing trading mistakes is watching a +10% gain reverse into a painful loss.
**How TraderAI's Trailing Stop protects you:**
1. Initial trade: Entry at ₹100, Planned Stop at ₹95 (-5%).
2. At +1R Gain (₹105): Stop automatically ratchets to ₹100 (Breakeven). The trade is now free of downside capital risk.
3. Trail Behind Peak: As price rallies toward target, the trailing stop sits 1.5x ATR behind the peak price.
4. If the stock reverses after rallying, you exit with locked-in profit instead of a loss!
""",
        "analogy": "Like a ratchet gear or climbing anchor: it moves freely upward with you as you climb, but catches you immediately if you slip, preventing a fall.",
    },
    {
        "term": "Reward-to-Risk Ratio (R:R)",
        "category": "🛡️ Risk & Protection",
        "short_def": "The ratio of potential profit to potential loss. TraderAI requires at least 2.0:1 before recommending a trade.",
        "detailed": """
Reward-to-Risk dictates whether a strategy is mathematically profitable over hundreds of trades.
- If your Target is +15% and your Stop-Loss is -7%, your **R:R is ~2.14:1**.
- **The Math of Success:** With a 2:1 R:R, even if you are wrong 50% of the time:
  - 5 losing trades @ -₹700 = -₹3,500
  - 5 winning trades @ +₹1,500 = +₹7,500
  - **Net Profit = +₹4,000!**
You do not need to be a fortune teller; you just need asymmetric payouts.
""",
        "analogy": "A coin-toss game where heads pays you ₹200 and tails only costs you ₹100. Even with a 50/50 coin, you will walk away wealthy.",
    },
    {
        "term": "Portfolio Heat & Max Drawdown",
        "category": "🛡️ Risk & Protection",
        "short_def": "Portfolio Heat is total capital at open risk across all positions; Max Drawdown is the deepest dip from peak portfolio value.",
        "detailed": """
- **Portfolio Heat:** If all your active trades hit their stop-losses on the exact same day, what is the maximum percentage of your total account that could be lost? TraderAI caps portfolio heat strictly at **8%**.
- **Max Drawdown:** The largest percentage drop from a historical peak to a subsequent trough. Low drawdown (<10-12%) allows steady compounding without emotional panic.
""",
        "analogy": "Portfolio heat is like the temperature of an engine. Keep it cool and it runs for 300,000 miles; overheat it and the engine blows.",
    },
    {
        "term": "Win Rate vs Expectancy",
        "category": "🛡️ Risk & Protection",
        "short_def": "Win Rate is the percentage of winning trades; Expectancy is the average amount earned per rupee risked.",
        "detailed": """
Beginners often obsess over having a 90% Win Rate. In reality:
- A strategy with 90% win rate can go bankrupt if the 10% losses are massive (-40% bagholding).
- A strategy with **50-55% win rate** combined with strict 2:1 R:R and trailing stops produces consistent, explosive wealth over time.
- TraderAI pairs a ~50-60% win rate with positive expectancy and trailing stops.
""",
        "analogy": "In baseball, a batter who hits home runs half the time beats someone who gets soft base hits 90% of the time but strikes out with the bases loaded.",
    },

    # 3. TECHNICAL ANALYSIS & CHART SIGNALS
    {
        "term": "50-Day SMA (Simple Moving Average)",
        "category": "📊 Technical Signals",
        "short_def": "The average closing price over the last 50 trading days, acting as a trend filter.",
        "detailed": """
The 50 SMA represents the medium-term consensus of institutional buyers:
- **Price > 50 SMA:** The stock is in an uptrend. Buyers are in control. TraderAI only enters long positions when price is above this line.
- **Price < 50 SMA:** The stock is in a downtrend. Buying here is 'catching a falling knife'. TraderAI avoids or trims these names.
""",
        "analogy": "Like checking which way the river is flowing before launching a boat. Always row downstream with the current, never fight the waterfall.",
    },
    {
        "term": "RSI (Relative Strength Index)",
        "category": "📊 Technical Signals",
        "short_def": "A momentum speedometer oscillating between 0 and 100 measuring buying vs selling velocity.",
        "detailed": """
- **Below 30-35 (Oversold):** Sellers are exhausted. Strong companies often stage sharp relief rallies from here.
- **Above 70 (Overbought):** Buyers pushed price up aggressively. High probability of a cooling-off consolidation.
- **45 to 65 (Sweet Spot):** Indicates a healthy, sustainable uptrend where momentum is positive without being over-extended.
""",
        "analogy": "Like the speedometer of a car. Cruising at 50 km/h is steady and sustainable; redlining at 120 km/h means you'll need to hit the brakes soon.",
    },
    {
        "term": "Relative Strength (RS vs Nifty 50)",
        "category": "📊 Technical Signals",
        "short_def": "Measures whether a specific stock is gaining faster than the broader Indian market (Nifty 50).",
        "detailed": """
Institutional funds park their billions into the fastest-moving market leaders:
- If Nifty is up +1% and a stock is up +3%, that stock has **High Relative Strength**.
- If Nifty is down -1% and a stock stays flat or green, institutions are aggressively accumulating it.
- In TraderAI, stocks exhibiting top relative strength earn bonus recommendation points.
""",
        "analogy": "In a running race, you want to draft behind the athlete pulling ahead of the pack, not the runner lagging behind.",
    },

    # 4. FUNDAMENTAL ANALYSIS & BUSINESS QUALITY
    {
        "term": "P/E Ratio (Price-to-Earnings)",
        "category": "🏢 Fundamentals",
        "short_def": "How many rupees you are paying for every ₹1 of annual profit the company generates.",
        "detailed": """
- If a stock is trading at ₹500 and its annual earnings per share (EPS) is ₹25, its **P/E is 20**.
- **Low P/E (<15-20):** Can indicate value, but check if the business is declining.
- **High P/E (>40-50):** The market expects rapid future earnings growth.
- **Context matters:** Fast-growing tech companies naturally carry higher P/E multiples than slow utility companies.
""",
        "analogy": "If a neighborhood bakery makes ₹10 Lakhs in profit per year and is selling the entire business for ₹1 Crore, the P/E is 10.",
    },
    {
        "term": "Debt-to-Equity (D/E Ratio)",
        "category": "🏢 Fundamentals",
        "short_def": "Total borrowed money divided by shareholder equity. A measure of financial solvency.",
        "detailed": """
- **D/E < 0.5 (Ideal):** The company has very low debt. During economic downturns or rising interest rates, it survives comfortably and can even buy out distressed rivals.
- **D/E > 1.5 (High Risk):** The company carries heavy interest obligations. Any drop in revenue can threaten bankruptcy.
- TraderAI prioritizes companies with low debt for long-term compounder sleeves.
""",
        "analogy": "A homeowner with zero mortgage payments can easily survive a temporary salary cut; someone with 5 maxed-out credit cards faces foreclosure.",
    },
    {
        "term": "ROE (Return on Equity)",
        "category": "🏢 Fundamentals",
        "short_def": "Net profit generated as a percentage of shareholders' equity. Measures capital efficiency.",
        "detailed": """
ROE reveals how talented the company management is at reinvesting retained earnings:
- **ROE > 15-20%:** Outstanding management efficiency (e.g. TCS, Titan, Asian Paints).
- **ROE < 8%:** Money might compound slower than a bank fixed deposit (FD).
""",
        "analogy": "If you hand two managers ₹100 each: Manager A brings back ₹120 (20% ROE); Manager B brings back ₹104 (4% ROE). You give your next investment to Manager A.",
    },
    {
        "term": "Kotak / Broker Ratings (REDUCE vs BUY) vs Quant Algorithmic Edge",
        "category": "🏢 Fundamentals",
        "short_def": "Why Kotak Securities might show 'REDUCE' while TraderAI recommends 'BUY' (Horizon & Valuation vs Momentum).",
        "detailed": """
**Why does Kotak say REDUCE while TraderAI says BUY?**

1. **Kotak Institutional Equities uses a 12-Month DCF Valuation Model:**
   - Brokerage research departments project cash flows over 5-10 years and discount them back to calculate a static 1-year target price.
   - If a market leader rallies strongly and its P/E multiple expands above its historical average, Kotak's model says: *"This stock has reached our 12-month fair value target; expected 1-year capital appreciation is low (-5% to -10% vs Nifty)."* Therefore, by regulation, they must label it **REDUCE**.
   - **Crucial point:** 'REDUCE' rarely means the business is failing; it usually means the stock has performed so well that it is no longer cheap on paper.

2. **TraderAI uses an Active Multi-Factor & Momentum Setup:**
   - TraderAI looks at real-time price trend (above 50 SMA), institutional volume accumulation, positive news sentiment, and quarterly earnings velocity.
   - In real-world Indian markets, the strongest multi-bagger compounders (e.g. Trent, Coforge, BEL, HAL, Dixon Technologies) often trade at 'expensive' valuations and were rated 'REDUCE' or 'NEUTRAL' by institutional brokerages for months while proceeding to rally another +40% to +100%!
   - TraderAI pairs this upside momentum with a **strict -7% Stop-Loss** and **+15% Target**. You capture the upside wave with mathematically capped risk, whereas a static DCF model simply misses the trade completely.

**What should you do?**
- If you are swing/positional trading: Trust TraderAI's setup with the defined Stop-Loss.
- If you already hold the stock with >25% profit: Kotak's 'REDUCE' and TraderAI's 'TRIM' align — consider booking partial profits and trailing the rest!
""",
        "analogy": "Imagine a luxury sports car that is so popular it's selling above its original factory sticker price. A conservative car appraiser says 'REDUCE/Don't Buy, it's above sticker price!' But race drivers (momentum traders) are still buying it because it's winning every single race on the track with a safety roll cage (stop-loss) installed.",
    },

    # 5. MACROECONOMICS & REGIMES
    {
        "term": "India VIX (Volatility Index)",
        "category": "🌍 Macro & Regimes",
        "short_def": "The Indian stock market's 'fear gauge' based on Nifty option pricing.",
        "detailed": """
- **VIX < 13 (Calm / Bullish):** Low market anxiety. Trend-following strategies work exceptionally well.
- **VIX 13 to 18 (Normal):** Standard market environment.
- **VIX > 20 (High Fear / Turmoil):** Rapid, jagged swings. News events cause sharp gaps.
- **TraderAI Response:** When VIX spikes above 18-20, TraderAI shifts capital into Gold ETFs (`GOLDBEES.NS`) and increases cash reserves.
""",
        "analogy": "Like a sea weather forecast. VIX 11 is calm sunny water; VIX 24 is high waves and turbulent winds where small boats stay near the shore.",
    },

    # 6. TRADERAI SCORING & ARCHITECTURE
    {
        "term": "Recommendation Score (0 to 100)",
        "category": "🤖 TraderAI Engine",
        "short_def": "The composite confidence score blending Technicals, Fundamentals, Sentiment, Macro, and Event Safety.",
        "detailed": """
TraderAI evaluates every stock across 5 independent mathematical pillars:
1. **Technical Score (0-100):** Moving averages, momentum, RSI, and support levels.
2. **Fundamental Score (0-100):** Earnings growth, ROE, debt safety, and valuation.
3. **Sentiment Score (0-100):** Financial news media headlines processed via NLP.
4. **Event Risk Score (0-100):** Checks if earnings announcements or high-risk binary events are imminent.
5. **Macro Alignment (0-100):** Synchronized with India VIX, interest rates, and global markets.

**Score Interpretation:**
- **80 to 100:** Strong high-conviction candidate with aligned technicals & fundamentals.
- **65 to 79:** Favorable setup with controlled risk.
- **Below 60:** Neutral / Hold. Fails strict deployment gates.
""",
        "analogy": "Like a university admission score that combines your GPA, test scores, recommendation letters, and interviews instead of just one test.",
    },
    {
        "term": "Stability vs Opportunity Sleeves",
        "category": "🤖 TraderAI Engine",
        "short_def": "The two asset pillars that balance safety with aggressive capital compounding.",
        "detailed": """
- **Stability Sleeve (Anchors):** Composed of Index ETFs (NIFTYBEES), Gold (GOLDBEES), and ultra-defensive blue-chips. Their purpose is capital preservation, lower drawdown, and peace of mind.
- **Opportunity Sleeve (Accelerators):** Sector leaders and momentum break-outs with high earnings growth. Their purpose is generating market-beating returns (alpha).
- TraderAI dynamically balances these sleeves based on your risk profile (Conservative, Balanced, or Aggressive).
""",
        "analogy": "Stability is the goalkeeper and defense on a football team; Opportunity is the strike force scoring goals. You cannot win without both.",
    },
    {
        "term": "Dual-AI: Analyst vs Judge",
        "category": "🤖 TraderAI Engine",
        "short_def": "An adversarial two-LLM architecture where the AI Analyst pitches trades and the AI Judge fact-checks them.",
        "detailed": """
Standard AI models often 'hallucinate' or get over-enthusiastic about hype. TraderAI uses an institutional check-and-balance system:
- **AI Analyst (Gemini Flash):** Synthesizes macro trends, price action, and news into a structured investment thesis with clear bull and bear scenarios.
- **AI Judge (Gemini Flash-Lite):** Acts as an adversarial auditor. It interrogates the Analyst's thesis, verifies math against the quant screener, assigns a Hallucination Score, and has full authority to reject or revise the trade!
""",
        "analogy": "The Analyst is the eager startup founder pitching an idea; the Judge is the seasoned venture capitalist auditing the financial spreadsheets before writing a check.",
    },
    {
        "term": "Paper Week (7-Day Shadow Gate)",
        "category": "🤖 TraderAI Engine",
        "short_def": "A mandatory 7-day virtual simulation gate where new signals are tracked in paper mode before real money is unlocked.",
        "detailed": """
Before committing hard-earned rupees to any strategy:
- Signals run in real-time shadow mode.
- P&L, slippage, and hit rates are logged daily.
- Real money deployment unlocks only after passing statistical reliability gates.
- Even when unlocked, Kotak Neo is strictly **read-only** — this app will NEVER place automated orders without your manual approval in your broker app.
""",
        "analogy": "A pilot spending 50 hours in a flight simulator before flying passengers through actual storms.",
    },
]


def render_glossary_section(standalone: bool = False):
    """Renders the interactive Market Academy and Glossary component."""
    if standalone:
        st.markdown("### 🎓 Stock Market Academy & Jargon Buster")
        st.caption("Plain-English explanations, real-world analogies, and rules for smart, stress-free delivery investing.")
    
    # Category Pills
    categories = ["All Terms", "⏰ Timings & Holidays", "🔰 Market Basics", "🛡️ Risk & Protection", "📊 Technical Signals", "🏢 Fundamentals", "🧺 ETFs & Assets", "🌍 Macro & Regimes", "🤖 TraderAI Engine"]
    
    col_search, col_cat = st.columns([2, 1])
    with col_search:
        search_query = st.text_input(
            "🔍 Search any term or concept (e.g. Stop-Loss, RSI, Trailing Stop, Delivery, ETF)",
            value="",
            key="glossary_search",
            placeholder="Type term name...",
        ).strip().lower()
    with col_cat:
        selected_cat = st.selectbox("Category filter", categories, key="glossary_cat")

    # Filter items
    filtered = []
    for item in GLOSSARY_ITEMS:
        match_cat = (selected_cat == "All Terms") or (item["category"] == selected_cat)
        match_search = (
            not search_query
            or search_query in item["term"].lower()
            or search_query in item["short_def"].lower()
            or search_query in item["detailed"].lower()
        )
        if match_cat and match_search:
            filtered.append(item)

    st.write(f"Showing **{len(filtered)}** concepts:")

    # Practical Broker Order Placement Cheat Sheet
    with st.expander("📱 Broker Order Cheat Sheet: Exactly What Buttons to Press (Kotak Neo, Zerodha, Groww)", expanded=True):
        st.markdown("""
### 🛒 Universal Rule: Always Select **CNC / Delivery**
Whether you are buying for 5 days or 5 years, **NEVER select MIS / Intraday**. Delivery means 100% cash paid upfront, zero margin interest, and zero forced 3:15 PM liquidation.
""")
        b_tabs = st.tabs([
            "🟢 Short-Term Swings",
            "🟡 Mid-Term (1-3 Yrs)",
            "🔵 Long-Term (3+ Yrs)",
            "🧺 ETFs (Gold & Nifty)",
            "🔴 Selling & GTT Stop-Loss",
            "⏰ Timings & Holidays",
        ])
        with b_tabs[0]:
            st.markdown("""
**For Short-Term Swings (Days to Months):**
- **Exchange:** `NSE`
- **Product Type:** `CNC` (Cash 'n Carry / Delivery)
- **Order Type:** `Limit` (enter the current price shown in TraderAI)
- **Quantity:** Use the suggested share quantity calculated by TraderAI
- **Exit Strategy:** Once your buy order is executed, immediately place a **GTT (Good Till Triggered) OCO Order**:
  - **Stop-Loss Trigger:** -7% below buy price (e.g. ₹93 if bought at ₹100)
  - **Target Trigger:** +15% above buy price (e.g. ₹115 if bought at ₹100)
  - **Trailing:** If the stock rallies to +6%, edit the Stop trigger to +1.5% (break-even).
""")
        with b_tabs[1]:
            st.markdown("""
**For Mid-Term Stocks (1 to 3 Years):**
- **Exchange:** `NSE`
- **Product Type:** `CNC` (Delivery)
- **Order Type:** `Limit` (set at or slightly below CMP)
- **Exit Strategy:**
  - Place a **GTT Stop-Loss** at ~10% to 12% below entry (or just below the 200-day moving average).
  - Review quarterly as company earnings are reported.
  - Partial profit target: +25% to +35%.
""")
        with b_tabs[2]:
            st.markdown("""
**For Long-Term Blue Chips (3+ Years):**
- **Exchange:** `NSE`
- **Product Type:** `CNC` (Delivery)
- **Order Type:** `Limit`
- **Exit Strategy:**
  - Do NOT set tight stop-losses (normal market pullbacks of 5-10% are standard over 3 years).
  - Only sell if company fundamentals break down (e.g. debt spikes, earnings drop for 3 consecutive quarters, or TraderAI flags 'SELL').
""")
        with b_tabs[3]:
            st.markdown("""
**For ETFs (`NIFTYBEES.NS`, `GOLDBEES.NS`, `MON100.NS`):**
- **Exchange:** `NSE`
- **Product Type:** `CNC` (Delivery)
- **Order Type:** `Limit` (or `Market` between 10:00 AM and 3:00 PM when market depth is deep).
- **Execution Timing:** Avoid the volatile opening 15 minutes (9:15–9:30 AM). Best time to buy ETFs is 11:30 AM to 2:00 PM.
- **Exit Strategy:** Buy & hold. Compound for years. Only rebalance when TraderAI signals Macro High Volatility.
""")
        with b_tabs[4]:
            st.markdown("""
**How to Sell Delivery Shares on Indian Brokers:**
1. **CDSL TPIN Authorization:** When you tap SELL on a Delivery holding, your broker will prompt for CDSL e-DIS. Enter your 6-digit TPIN + mobile OTP (valid for the whole trading day).
2. **Order Type:** Select `Limit` (at the price you want to exit) or `Market` (if executing an immediate exit).
3. **Product Type:** Ensure it says `CNC` (Delivery sell).
4. **GTT Auto-Selling:** If you set a GTT order, the broker will automatically place the sell order for you the moment the trigger price is touched during market hours.
""")
        with b_tabs[5]:
            m_stat = get_market_status()
            st.markdown(f"### Live Market Status: **{m_stat['badge']}**")
            st.info(f"{m_stat['detail']} (Current Time: {m_stat['current_time_str']})")
            st.markdown("""
**Standard Indian Trading Session Timings (Mon–Fri):**
- **09:00 AM – 09:08 AM:** Pre-Market Order Entry (accumulating opening orders)
- **09:08 AM – 09:15 AM:** Order Matching & Opening Price Discovery
- **09:15 AM – 03:30 PM:** Normal Continuous Trading Session (all live trades occur here)
- **03:30 PM – 03:40 PM:** Closing Price Calculation (30-min volume-weighted price)
- **03:40 PM – 04:00 PM:** Post-Market Trading Session
- **Weekends:** Saturday & Sunday (Closed)
""")
            st.markdown("#### 📅 Official Upcoming NSE Trading Holidays")
            hols = get_upcoming_holidays(limit=6)
            if hols:
                st.dataframe(pd.DataFrame(hols)[["formatted", "day_name", "name", "countdown"]].rename(columns={
                    "formatted": "Date",
                    "day_name": "Day",
                    "name": "Holiday Name",
                    "countdown": "Timeline",
                }), use_container_width=True)

    # Quick Rule of Thumb Banner
    with st.expander("⚡ 5 Golden Rules for Beginners (Read Before Buying Anything)", expanded=False):
        st.markdown("""
1. **Never Trade with Money Needed in 30 Days**: Delivery investing allows you to hold through short-term market dips without panic.
2. **Always Use a Stop-Loss**: Never let a small -7% dip turn into a -40% unrecoverable disaster.
3. **Start with Index & Gold ETFs First**: `NIFTYBEES.NS` and `GOLDBEES.NS` provide instant diversification across India's top 50 companies and physical gold with zero single-company bankruptcy risk.
4. **Never Chase Parabolic Spikes**: If a stock already rallied +30% in 5 days, let it pull back to its 50-day moving average.
5. **Trust the 2:1 Reward-to-Risk Math**: You don't need to predict the future 90% of the time. Making ₹2 on winners while losing ₹1 on losers compounds wealth consistently.
""")

    # Render accordion cards
    for item in filtered:
        with st.expander(f"**{item['term']}** — *{item['category']}*"):
            st.markdown(f"**Quick Definition:** {item['short_def']}")
            st.divider()
            st.markdown(item["detailed"])
            if item.get("analogy"):
                st.info(f"💡 **Real-World Analogy:** {item['analogy']}")
