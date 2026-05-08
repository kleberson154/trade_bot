"""
Indicadores técnicos utilizados pelo bot
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Optional


# ── Estrutura de Mercado ───────────────────────────────────────────────────────

def find_swing_highs_lows(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Identifica swing highs e swing lows."""
    df = df.copy()
    df["swing_high"] = False
    df["swing_low"] = False

    for i in range(lookback, len(df) - lookback):
        window_high = df["high"].iloc[i - lookback: i + lookback + 1]
        window_low = df["low"].iloc[i - lookback: i + lookback + 1]

        if df["high"].iloc[i] == window_high.max():
            df.loc[df.index[i], "swing_high"] = True
        if df["low"].iloc[i] == window_low.min():
            df.loc[df.index[i], "swing_low"] = True

    return df


def identify_market_structure(df: pd.DataFrame) -> str:
    """
    Identifica estrutura atual: uptrend, downtrend, ranging.
    Compara últimos swing highs e lows.
    """
    swings = find_swing_highs_lows(df)
    highs = df[swings["swing_high"]]["high"].tail(3).values
    lows = df[swings["swing_low"]]["low"].tail(3).values

    if len(highs) < 2 or len(lows) < 2:
        return "ranging"

    hh = highs[-1] > highs[-2]   # Higher High
    hl = lows[-1] > lows[-2]     # Higher Low
    lh = highs[-1] < highs[-2]   # Lower High
    ll = lows[-1] < lows[-2]     # Lower Low

    if hh and hl:
        return "uptrend"
    elif lh and ll:
        return "downtrend"
    else:
        return "ranging"


# ── CHoCH / BOS ────────────────────────────────────────────────────────────────

def detect_choch(df: pd.DataFrame, lookback: int = 5) -> List[dict]:
    """
    Detecta Change of Character (CHoCH).
    CHoCH de alta: preço quebra abaixo do último swing low (em uptrend)
    CHoCH de baixa: preço quebra acima do último swing high (em downtrend)
    """
    signals = []
    swings = find_swing_highs_lows(df, lookback)
    structure = identify_market_structure(df)

    recent_close = df["close"].iloc[-1]
    recent_idx = len(df) - 1

    if structure == "uptrend":
        last_lows = df[swings["swing_low"]]["low"]
        if len(last_lows) > 0:
            last_swing_low = last_lows.iloc[-1]
            if recent_close < last_swing_low:
                signals.append({
                    "type": "CHoCH",
                    "direction": "bearish",
                    "price": last_swing_low,
                    "bar": recent_idx,
                    "strength": 0.8,
                })
    elif structure == "downtrend":
        last_highs = df[swings["swing_high"]]["high"]
        if len(last_highs) > 0:
            last_swing_high = last_highs.iloc[-1]
            if recent_close > last_swing_high:
                signals.append({
                    "type": "CHoCH",
                    "direction": "bullish",
                    "price": last_swing_high,
                    "bar": recent_idx,
                    "strength": 0.8,
                })
    return signals


# ── FVG / IFVG ────────────────────────────────────────────────────────────────

def detect_fvg(df: pd.DataFrame, min_size_pct: float = 0.001) -> List[dict]:
    """
    Detecta Fair Value Gaps (FVG) e Inverse FVG.
    FVG Bullish: low[i+1] > high[i-1] (gap de alta)
    FVG Bearish: high[i+1] < low[i-1] (gap de baixa)
    """
    fvgs = []
    for i in range(1, len(df) - 1):
        c1_high = df["high"].iloc[i - 1]
        c1_low = df["low"].iloc[i - 1]
        c3_high = df["high"].iloc[i + 1]
        c3_low = df["low"].iloc[i + 1]
        mid_price = df["close"].iloc[i]

        # FVG Bullish
        if c3_low > c1_high:
            size = (c3_low - c1_high) / mid_price
            if size >= min_size_pct:
                fvgs.append({
                    "type": "FVG",
                    "direction": "bullish",
                    "top": c3_low,
                    "bottom": c1_high,
                    "mid": (c3_low + c1_high) / 2,
                    "bar": i,
                    "size_pct": size,
                    "filled": False,
                })

        # FVG Bearish
        if c3_high < c1_low:
            size = (c1_low - c3_high) / mid_price
            if size >= min_size_pct:
                fvgs.append({
                    "type": "FVG",
                    "direction": "bearish",
                    "top": c1_low,
                    "bottom": c3_high,
                    "mid": (c1_low + c3_high) / 2,
                    "bar": i,
                    "size_pct": size,
                    "filled": False,
                })

    # Marca FVGs preenchidos (IFVG)
    recent_close = df["close"].iloc[-1]
    for fvg in fvgs:
        if fvg["direction"] == "bullish" and recent_close < fvg["bottom"]:
            fvg["type"] = "IFVG"
            fvg["filled"] = True
        elif fvg["direction"] == "bearish" and recent_close > fvg["top"]:
            fvg["type"] = "IFVG"
            fvg["filled"] = True

    return fvgs[-20:]  # Retorna os 20 mais recentes


# ── POI / Zonas de Demanda e Oferta ───────────────────────────────────────────

def detect_poi(df: pd.DataFrame) -> List[dict]:
    """
    Detecta Points of Interest (POI) - zonas de demanda/oferta.
    POI = swing high/low que precedeu um movimento forte.
    """
    pois = []
    swings = find_swing_highs_lows(df, lookback=5)

    for i in range(5, len(df) - 5):
        if swings["swing_high"].iloc[i]:
            # Verifica se precedeu movimento descendente forte
            move_after = (df["close"].iloc[i + 5] - df["high"].iloc[i]) / df["high"].iloc[i]
            if move_after < -0.005:
                pois.append({
                    "type": "POI",
                    "zone": "supply",
                    "top": df["high"].iloc[i] * 1.001,
                    "bottom": df["open"].iloc[i],
                    "price": df["high"].iloc[i],
                    "bar": i,
                    "strength": min(abs(move_after) * 50, 1.0),
                })

        if swings["swing_low"].iloc[i]:
            move_after = (df["close"].iloc[i + 5] - df["low"].iloc[i]) / df["low"].iloc[i]
            if move_after > 0.005:
                pois.append({
                    "type": "POI",
                    "zone": "demand",
                    "top": df["open"].iloc[i],
                    "bottom": df["low"].iloc[i] * 0.999,
                    "price": df["low"].iloc[i],
                    "bar": i,
                    "strength": min(abs(move_after) * 50, 1.0),
                })

    return pois[-15:]


# ── Troca de Polaridade ────────────────────────────────────────────────────────

def detect_polarity_change(df: pd.DataFrame) -> List[dict]:
    """
    Detecta Troca de Polaridade: resistência vira suporte ou vice-versa.
    """
    signals = []
    swings = find_swing_highs_lows(df)
    current_price = df["close"].iloc[-1]
    tolerance = 0.003  # 0.3%

    prev_highs = df[swings["swing_high"]]["high"].tail(10).values
    prev_lows = df[swings["swing_low"]]["low"].tail(10).values

    # Resistência virando suporte (bullish)
    for h in prev_highs:
        if abs(current_price - h) / h < tolerance:
            signals.append({
                "type": "POLARITY_CHANGE",
                "direction": "bullish",
                "price": h,
                "strength": 0.75,
            })

    # Suporte virando resistência (bearish)
    for l in prev_lows:
        if abs(current_price - l) / l < tolerance:
            signals.append({
                "type": "POLARITY_CHANGE",
                "direction": "bearish",
                "price": l,
                "strength": 0.75,
            })

    return signals


# ── Análise de Volume ─────────────────────────────────────────────────────────

def analyze_volume(df: pd.DataFrame, window: int = 20) -> dict:
    """
    Analisa volume para detectar divergências e anomalias.
    """
    avg_vol = df["volume"].rolling(window).mean()
    last_vol = df["volume"].iloc[-1]
    last_avg = avg_vol.iloc[-1]

    ratio = last_vol / last_avg if last_avg > 0 else 1.0

    # Divergência de volume com preço
    price_direction = 1 if df["close"].iloc[-1] > df["close"].iloc[-5] else -1
    vol_direction = 1 if df["volume"].iloc[-5:].mean() > avg_vol.iloc[-5:].mean() else -1
    divergence = price_direction != vol_direction

    # Delta de volume (compra vs venda)
    df = df.copy()
    df["buy_vol"] = df["volume"].where(df["close"] > df["open"], 0)
    df["sell_vol"] = df["volume"].where(df["close"] <= df["open"], 0)
    recent_buy = df["buy_vol"].tail(5).sum()
    recent_sell = df["sell_vol"].tail(5).sum()
    delta = recent_buy - recent_sell

    return {
        "ratio": round(ratio, 2),
        "is_spike": ratio > 1.5,
        "divergence": divergence,
        "delta": delta,
        "delta_bullish": delta > 0,
        "avg_volume": last_avg,
        "last_volume": last_vol,
    }


# ── EMA / SMA ─────────────────────────────────────────────────────────────────

def add_emas(df: pd.DataFrame, periods: List[int] = [9, 21, 50, 200]) -> pd.DataFrame:
    """Adiciona EMAs ao DataFrame."""
    df = df.copy()
    for p in periods:
        df[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Adiciona ATR ao DataFrame."""
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(period).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Adiciona RSI ao DataFrame."""
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    return df
