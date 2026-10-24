"""
TraderAI - Technical Analysis Engine
Computes technical indicators and generates a TechnicalScore (0-100).
"""
import pandas as pd
import numpy as np
import ta
import logging

logger = logging.getLogger(__name__)


def compute_technical_score(df: pd.DataFrame, ticker: str = "") -> dict:
    """
    Compute a comprehensive technical analysis score for a stock.
    
    Args:
        df: OHLCV DataFrame (needs Open, High, Low, Close, Volume columns)
        ticker: Stock symbol for labeling
    
    Returns:
        Dict with overall score (0-100), individual indicator scores, and signals
    """
    if df.empty or len(df) < 50:
        return {"ticker": ticker, "score": 50, "signal": "NEUTRAL", "error": "Insufficient data"}

    try:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        signals = {}
        scores = []

        # ─── TREND INDICATORS ────────────────────────────────
        # SMA Crossover — use 50/200 when enough history, else 20/50
        sma_fast_w, sma_slow_w = (50, 200) if len(close) >= 200 else (20, 50)
        sma_50 = ta.trend.sma_indicator(close, window=sma_fast_w)
        sma_200 = ta.trend.sma_indicator(close, window=sma_slow_w)
        fast_v, slow_v = float(sma_50.iloc[-1]), float(sma_200.iloc[-1])

        if slow_v == 0 or (fast_v != fast_v) or (slow_v != slow_v):  # NaN guard
            sma_signal, sma_score = "NEUTRAL", 50
        elif fast_v > slow_v:
            sma_signal = "BULLISH"
            sma_score = 70 + min(30, (fast_v - slow_v) / slow_v * 1000)
        else:
            sma_signal = "BEARISH"
            sma_score = 30 - min(30, (slow_v - fast_v) / slow_v * 1000)

        signals["sma_crossover"] = {
            "signal": sma_signal,
            "sma_fast": round(fast_v, 2) if fast_v == fast_v else None,
            "sma_slow": round(slow_v, 2) if slow_v == slow_v else None,
            "windows": [sma_fast_w, sma_slow_w],
        }
        scores.append(("SMA Crossover", max(0, min(100, sma_score)), 0.15))

        cur_close = float(close.iloc[-1]) if float(close.iloc[-1]) > 0 else 1.0

        # MACD (Price-Normalized Histogram)
        macd = ta.trend.MACD(close)
        macd_line = macd.macd()
        macd_signal_line = macd.macd_signal()
        macd_hist = macd.macd_diff()
        # Price-normalized histogram percentage
        hist_pct = (abs(macd_hist.iloc[-1]) / cur_close) * 100.0 if cur_close > 0 else 0.0

        if macd_line.iloc[-1] > macd_signal_line.iloc[-1]:
            macd_signal = "BULLISH"
            macd_score = 65 + min(35, hist_pct * 30.0)
        else:
            macd_signal = "BEARISH"
            macd_score = 35 - min(35, hist_pct * 30.0)

        signals["macd"] = {"signal": macd_signal, "macd": round(macd_line.iloc[-1], 2), "histogram_pct": round(hist_pct, 3)}
        scores.append(("MACD", max(0, min(100, macd_score)), 0.15))

        # EMA trend & Over-Extension Guard (Avoid buying stretched rubber bands > 6% above 20 EMA)
        ema_20 = ta.trend.ema_indicator(close, window=20)
        price_vs_ema = (close.iloc[-1] - ema_20.iloc[-1]) / ema_20.iloc[-1] * 100

        if 0.5 <= price_vs_ema <= 4.5:
            ema_signal = "SWEET_SPOT_VALUE"
            ema_score = 90  # Ideal low-risk swing entry near dynamic 20 EMA support
        elif -2.0 <= price_vs_ema < 0.5:
            ema_signal = "EMA_SUPPORT_TEST"
            ema_score = 75  # Retesting support in healthy trend
        elif 4.5 < price_vs_ema <= 6.0:
            ema_signal = "MODERATE_EXTENSION"
            ema_score = 65  # Momentum continuation; caution on gap-ups
        elif price_vs_ema > 6.0:
            ema_signal = "OVER_EXTENDED"
            ema_score = 35  # Stretched rubber band (>6% above 20 EMA); high risk of intraday fade
        elif -5.0 <= price_vs_ema < -2.0:
            ema_signal = "PULLBACK_BELOW_EMA"
            ema_score = 45
        else:
            ema_signal = "BREAKDOWN_BELOW_EMA"
            ema_score = 25  # Deep breakdown below moving average

        signals["ema_20"] = {
            "signal": ema_signal,
            "deviation_pct": round(price_vs_ema, 2),
            "is_overextended": price_vs_ema > 6.0,
        }
        scores.append(("EMA 20", max(0, min(100, ema_score)), 0.10))

        # ─── MOMENTUM & BREAKOUT FACTORS ─────────────────────
        is_uptrend = (fast_v > slow_v) if (fast_v == fast_v and slow_v == slow_v) else (cur_close > float(ema_20.iloc[-1]))
        
        # Regime-Aware RSI (Do not penalize Stage 2 momentum breakouts!)
        rsi = ta.momentum.rsi(close, window=14)
        rsi_val = float(rsi.iloc[-1])

        if is_uptrend:
            if 60 <= rsi_val <= 75:
                rsi_signal = "MOMENTUM_SWEET_SPOT"
                rsi_score = 85  # Strong institutional trend acceleration
            elif 75 < rsi_val <= 85:
                rsi_signal = "HIGH_MOMENTUM"
                rsi_score = 70  # Breakout power; trailing stop required
            elif rsi_val > 85:
                rsi_signal = "PARABOLIC_OVERBOUGHT"
                rsi_score = 40  # Risk of sharp mean-reversion
            elif 50 <= rsi_val < 60:
                rsi_signal = "HEALTHY_ACCUMULATION"
                rsi_score = 65
            elif 40 <= rsi_val < 50:
                rsi_signal = "PULLBACK_SUPPORT"
                rsi_score = 50
            else:
                rsi_signal = "MOMENTUM_LOSS"
                rsi_score = 30
        else:
            # Downtrend regime: oversold bounce is lower probability
            if rsi_val < 30:
                rsi_signal = "OVERSOLD_DOWNTREND"
                rsi_score = 45  # Potential counter-trend bounce, but catching a falling knife
            elif 30 <= rsi_val < 50:
                rsi_signal = "BEARISH_TREND"
                rsi_score = 25
            else:
                rsi_signal = "BEAR_MARKET_RALLY"
                rsi_score = 40

        signals["rsi"] = {"signal": rsi_signal, "value": round(rsi_val, 2)}
        scores.append(("RSI", max(0, min(100, rsi_score)), 0.15))

        # 52-Week High Proximity (Proven Indian Market Momentum Driver)
        lookback_bars = min(len(high), 252)
        high_52w = float(high.rolling(window=lookback_bars).max().iloc[-1])
        pct_from_52w = ((cur_close - high_52w) / high_52w * 100.0) if high_52w > 0 else -50.0

        if pct_from_52w >= -5.0:
            h52_signal = "NEAR_52W_HIGH"
            h52_score = 85  # Market leader breaking out / near highs
        elif pct_from_52w >= -15.0:
            h52_signal = "UPPER_QUADRANT"
            h52_score = 70  # Strong accumulation zone
        elif pct_from_52w >= -25.0:
            h52_signal = "MID_RANGE"
            h52_score = 50
        else:
            h52_signal = "LAGGARD"
            h52_score = 25  # Deep laggard; underperforming market

        signals["52w_proximity"] = {"signal": h52_signal, "distance_pct": round(pct_from_52w, 2), "high_52w": round(high_52w, 2)}
        scores.append(("52W Proximity", h52_score, 0.10))

        # ─── VOLATILITY & EXPANSION ───────────────────────────
        # Bollinger Bands (Breakout-Friendly Interpretation)
        bb = ta.volatility.BollingerBands(close)
        bb_upper = bb.bollinger_hband()
        bb_lower = bb.bollinger_lband()
        bb_band_width = (bb_upper.iloc[-1] - bb_lower.iloc[-1])
        bb_position = (cur_close - bb_lower.iloc[-1]) / bb_band_width if bb_band_width > 0 else 0.5

        if is_uptrend:
            if bb_position > 0.8:
                bb_signal = "BAND_WALK_EXPANSION"
                bb_score = 75  # Volatility expansion in direction of trend
            elif 0.4 <= bb_position <= 0.8:
                bb_signal = "TREND_CHANNEL"
                bb_score = 65
            else:
                bb_signal = "LOWER_BAND_PULLBACK"
                bb_score = 50
        else:
            if bb_position < 0.2:
                bb_signal = "BREAKING_FLOOR"
                bb_score = 25
            else:
                bb_signal = "DOWNTREND_RANGE"
                bb_score = 40

        signals["bollinger"] = {"signal": bb_signal, "position": round(bb_position, 2)}
        scores.append(("Bollinger Bands", bb_score, 0.10))

        # ATR (Average True Range — volatility measure)
        atr = ta.volatility.average_true_range(high, low, close)
        atr_pct = atr.iloc[-1] / cur_close * 100
        signals["atr"] = {"value": round(atr.iloc[-1], 2), "atr_percent": round(atr_pct, 2)}

        # ─── MINERVINI VCP (VOLATILITY CONTRACTION PATTERN) ──
        high_5d = float(high.tail(5).max()) if len(high) >= 5 else float(high.max())
        low_5d = float(low.tail(5).min()) if len(low) >= 5 else float(low.min())
        high_20d = float(high.tail(20).max()) if len(high) >= 20 else float(high.max())
        low_20d = float(low.tail(20).min()) if len(low) >= 20 else float(low.min())
        range_20d = high_20d - low_20d
        vcp_ratio = (high_5d - low_5d) / range_20d if range_20d > 0 else 1.0
        is_vcp_tight = (vcp_ratio <= 0.65)
        
        cur_open = float(df["Open"].iloc[-1]) if "Open" in df.columns else cur_close
        is_bullish_candle = bool(cur_close > cur_open)
        is_sweet_spot_rebound = bool(0.0 <= price_vs_ema <= 2.5 and is_bullish_candle)

        signals["vcp"] = {
            "vcp_ratio": round(vcp_ratio, 2),
            "is_contracted": is_vcp_tight,
            "signal": "TIGHT_CONTRACTION" if is_vcp_tight else "NORMAL_RANGE"
        }
        signals["sweet_spot_rebound"] = {
            "is_sweet_spot": is_sweet_spot_rebound,
            "is_bullish_candle": is_bullish_candle,
            "deviation_pct": round(price_vs_ema, 2)
        }

        # ─── VOLUME INDICATORS ───────────────────────────────
        vol_sma = volume.rolling(window=min(len(volume), 20)).mean().iloc[-1]
        vol_ratio = float(volume.iloc[-1] / vol_sma) if vol_sma > 0 else 1.0

        # OBV trend
        obv = ta.volume.on_balance_volume(close, volume)
        obv_sma = obv.rolling(window=20).mean()

        if obv.iloc[-1] > obv_sma.iloc[-1]:
            vol_signal = "ACCUMULATION"
            vol_score = 65
        else:
            vol_signal = "DISTRIBUTION"
            vol_score = 35

        # ADTV (Average Daily Turnover in INR) — Minimum ₹5 Crore Liquidity Filter
        turnover_20d = (volume * close).rolling(window=min(len(close), 20)).mean().iloc[-1]
        adtv_cr = round(turnover_20d / 10_000_000, 2) if turnover_20d > 0 else 0.0
        is_liquid = turnover_20d >= 50_000_000  # Minimum ₹5 Crore daily turnover
        if not is_liquid and turnover_20d > 0:
            vol_score -= 15
            vol_signal += "_LOW_LIQUIDITY"

        signals["volume"] = {"signal": vol_signal, "volume_ratio": round(vol_ratio, 2)}
        signals["adtv"] = {"adtv_crores": adtv_cr, "is_liquid": is_liquid}
        scores.append(("Volume", max(0, min(100, vol_score)), 0.10))

        # ─── PRICE ACTION ────────────────────────────────────
        # Recent price momentum (5-day and 20-day returns)
        ret_5d = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0
        ret_20d = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0

        momentum_score = 50 + ret_5d * 2.5 + ret_20d * 0.8
        signals["momentum"] = {"return_5d": round(ret_5d, 2), "return_20d": round(ret_20d, 2)}
        scores.append(("Price Momentum", max(0, min(100, momentum_score)), 0.15))

        # ─── FINAL SCORE CALCULATION ─────────────────────────
        weighted_score = sum(score * weight for _, score, weight in scores)
        total_weight = sum(weight for _, _, weight in scores)
        final_score = weighted_score / total_weight if total_weight > 0 else 50

        # Determine overall signal
        if final_score >= 70:
            overall_signal = "STRONG_BUY"
        elif final_score >= 60:
            overall_signal = "BUY"
        elif final_score >= 45:
            overall_signal = "HOLD"
        elif final_score >= 35:
            overall_signal = "SELL"
        else:
            overall_signal = "STRONG_SELL"

        valid_close = close.dropna()
        latest_close = float(valid_close.iloc[-1]) if not valid_close.empty else 0.0

        return {
            "ticker": ticker,
            "score": round(final_score, 1),
            "signal": overall_signal,
            "indicators": signals,
            "breakdown": {name: round(score, 1) for name, score, _ in scores},
            "current_price": round(latest_close, 2),
            "atr": round(atr.iloc[-1], 2),
            "atr_percent": round(atr_pct, 2),
        }

    except Exception as e:
        logger.error(f"Error computing technical score for {ticker}: {e}")
        return {"ticker": ticker, "score": 50, "signal": "NEUTRAL", "error": str(e)}


def compute_support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    """
    Calculate basic support and resistance levels.
    
    Returns:
        Dict with support and resistance price levels
    """
    if df.empty or len(df) < window:
        return {}

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    # Recent support and resistance
    recent_low = low.tail(window).min()
    recent_high = high.tail(window).max()

    # Pivot points
    typical = (high.iloc[-1] + low.iloc[-1] + close.iloc[-1]) / 3
    r1 = 2 * typical - low.iloc[-1]
    s1 = 2 * typical - high.iloc[-1]
    r2 = typical + (high.iloc[-1] - low.iloc[-1])
    s2 = typical - (high.iloc[-1] - low.iloc[-1])

    return {
        "current_price": round(close.iloc[-1], 2),
        "support_1": round(s1, 2),
        "support_2": round(s2, 2),
        "resistance_1": round(r1, 2),
        "resistance_2": round(r2, 2),
        "recent_low": round(recent_low, 2),
        "recent_high": round(recent_high, 2),
        "pivot": round(typical, 2),
    }
