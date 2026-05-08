"""
Análise de Contextos de Mercado:
- Captura de Liquidez
- Estruturas de Wyckoff
- Inversão de Fluxo
- Rompimento de Regiões
- Macro e Micro
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from strategies.indicators import (
    find_swing_highs_lows,
    identify_market_structure,
    analyze_volume,
    add_emas,
    add_atr,
)
from utils.logger import setup_logger

logger = setup_logger("contexts")


# ── Captura de Liquidez ───────────────────────────────────────────────────────

def analyze_liquidity_capture(df: pd.DataFrame) -> Dict:
    """
    Detecta captura de liquidez:
    - Stop hunt acima de swing highs (velas de pavio longo)
    - Stop hunt abaixo de swing lows
    Após a captura, reversão é esperada.
    """
    result = {"detected": False, "direction": None, "score": 0.0, "description": ""}

    swings = find_swing_highs_lows(df, lookback=10)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    last_highs = df[swings["swing_high"]]["high"].tail(5).values
    last_lows = df[swings["swing_low"]]["low"].tail(5).values

    # Pavio acima de swing high → captura de liquidez bearish
    wick_up = last["high"] - max(last["open"], last["close"])
    body = abs(last["close"] - last["open"])

    if len(last_highs) > 0:
        for h in last_highs[-3:]:
            # Vela penetrou o swing high mas fechou abaixo
            if last["high"] > h and last["close"] < h and wick_up > body * 0.5:
                vol_data = analyze_volume(df)
                score = 0.7 + (0.15 if vol_data["is_spike"] else 0)
                result.update({
                    "detected": True,
                    "direction": "bearish",
                    "score": min(score, 1.0),
                    "description": f"Captura de liquidez acima de {h:.4f} | pavio={wick_up:.4f}",
                    "level": h,
                })
                return result

    # Pavio abaixo de swing low → captura de liquidez bullish
    wick_down = min(last["open"], last["close"]) - last["low"]

    if len(last_lows) > 0:
        for l in last_lows[-3:]:
            if last["low"] < l and last["close"] > l and wick_down > body * 0.5:
                vol_data = analyze_volume(df)
                score = 0.7 + (0.15 if vol_data["is_spike"] else 0)
                result.update({
                    "detected": True,
                    "direction": "bullish",
                    "score": min(score, 1.0),
                    "description": f"Captura de liquidez abaixo de {l:.4f} | pavio={wick_down:.4f}",
                    "level": l,
                })
                return result

    return result


# ── Estrutura de Wyckoff ──────────────────────────────────────────────────────

def analyze_wyckoff(df: pd.DataFrame) -> Dict:
    """
    Identifica fases de Wyckoff:
    - Acumulação: Range lateral após queda com testes de suporte
    - Distribuição: Range lateral após alta com testes de resistência
    - Spring / Upthrust
    """
    result = {"detected": False, "phase": None, "direction": None, "score": 0.0, "description": ""}

    df_ema = add_emas(df, [20, 50])
    df_atr = add_atr(df_ema)

    # Verifica se o mercado está em ranging (condição de Wyckoff)
    structure = identify_market_structure(df)
    if structure != "ranging":
        return result

    # Detecta range
    recent = df.tail(40)
    range_high = recent["high"].max()
    range_low = recent["low"].min()
    range_size = range_high - range_low
    atr = df_atr["atr"].iloc[-1]

    # Range saudável: entre 2x e 10x ATR
    if not (2 * atr < range_size < 10 * atr):
        return result

    current_price = df["close"].iloc[-1]
    range_mid = (range_high + range_low) / 2

    vol_data = analyze_volume(df)

    # Spring (acumulação): preço testa abaixo do range_low com volume alto, fecha acima
    last = df.iloc[-1]
    if last["low"] < range_low * 1.001 and last["close"] > range_low:
        if vol_data["is_spike"]:
            result.update({
                "detected": True,
                "phase": "spring",
                "direction": "bullish",
                "score": 0.82,
                "description": f"Wyckoff Spring | Range {range_low:.4f}-{range_high:.4f}",
                "range_low": range_low,
                "range_high": range_high,
            })
            return result

    # Upthrust (distribuição): preço testa acima do range_high com volume alto, fecha abaixo
    if last["high"] > range_high * 0.999 and last["close"] < range_high:
        if vol_data["is_spike"]:
            result.update({
                "detected": True,
                "phase": "upthrust",
                "direction": "bearish",
                "score": 0.80,
                "description": f"Wyckoff Upthrust | Range {range_low:.4f}-{range_high:.4f}",
                "range_low": range_low,
                "range_high": range_high,
            })
            return result

    return result


# ── Inversão de Fluxo ─────────────────────────────────────────────────────────

def analyze_flow_inversion(df: pd.DataFrame) -> Dict:
    """
    Detecta inversão de fluxo de ordens:
    - Sequência de candles opostos após tendência clara
    - Delta de volume invertendo
    - Engolfamentos significativos
    """
    result = {"detected": False, "direction": None, "score": 0.0, "description": ""}

    if len(df) < 10:
        return result

    # Últimas 5 velas
    recent = df.tail(10)
    vol_data = analyze_volume(df)

    closes = recent["close"].values
    opens = recent["open"].values

    # Conta sequência direcional
    bull_count = sum(1 for i in range(len(closes)) if closes[i] > opens[i])
    bear_count = len(closes) - bull_count

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Engolfamento de alta após sequência bearish
    if bear_count >= 6:
        engulf_bull = (
            last["close"] > last["open"] and  # vela de alta
            last["open"] < prev["close"] and  # abre abaixo do close anterior
            last["close"] > prev["open"]       # fecha acima do open anterior
        )
        if engulf_bull:
            score = 0.72 + (0.10 if vol_data["delta_bullish"] else 0)
            result.update({
                "detected": True,
                "direction": "bullish",
                "score": min(score, 1.0),
                "description": f"Inversão de Fluxo Bullish | Engolfamento após {bear_count} velas bearish",
            })
            return result

    # Engolfamento de baixa após sequência bullish
    if bull_count >= 6:
        engulf_bear = (
            last["close"] < last["open"] and
            last["open"] > prev["close"] and
            last["close"] < prev["open"]
        )
        if engulf_bear:
            score = 0.72 + (0.10 if not vol_data["delta_bullish"] else 0)
            result.update({
                "detected": True,
                "direction": "bearish",
                "score": min(score, 1.0),
                "description": f"Inversão de Fluxo Bearish | Engolfamento após {bull_count} velas bullish",
            })
            return result

    return result


# ── Rompimento de Regiões ─────────────────────────────────────────────────────

def analyze_breakout(df: pd.DataFrame) -> Dict:
    """
    Detecta rompimentos de regiões-chave com volume.
    - Rompimento de range
    - Rompimento de nível de swing high/low
    """
    result = {"detected": False, "direction": None, "score": 0.0, "description": ""}

    swings = find_swing_highs_lows(df, lookback=10)
    vol_data = analyze_volume(df)

    recent_high = df[swings["swing_high"]]["high"].tail(3)
    recent_low = df[swings["swing_low"]]["low"].tail(3)

    if recent_high.empty or recent_low.empty:
        return result

    key_high = recent_high.max()
    key_low = recent_low.min()
    current_close = df["close"].iloc[-1]
    current_vol = vol_data["ratio"]

    # Rompimento bullish com volume
    if current_close > key_high and current_vol > 1.3:
        score = 0.68 + (0.12 if vol_data["is_spike"] else 0)
        result.update({
            "detected": True,
            "direction": "bullish",
            "score": min(score, 1.0),
            "description": f"Rompimento Bullish de {key_high:.4f} | Vol={current_vol:.1f}x",
            "level": key_high,
        })
        return result

    # Rompimento bearish com volume
    if current_close < key_low and current_vol > 1.3:
        score = 0.68 + (0.12 if not vol_data["delta_bullish"] else 0)
        result.update({
            "detected": True,
            "direction": "bearish",
            "score": min(score, 1.0),
            "description": f"Rompimento Bearish de {key_low:.4f} | Vol={current_vol:.1f}x",
            "level": key_low,
        })
        return result

    return result


# ── Macro e Micro ─────────────────────────────────────────────────────────────

def analyze_macro_micro(
    df_macro: pd.DataFrame,
    df_micro: pd.DataFrame,
) -> Dict:
    """
    Alinhamento entre timeframe macro (4H) e micro (5min).
    Bias macro direciona entradas micro.
    """
    result = {"detected": False, "bias": None, "aligned": False, "score": 0.0}

    macro_structure = identify_market_structure(df_macro)
    micro_structure = identify_market_structure(df_micro)

    df_macro_ema = add_emas(df_macro, [50, 200])
    macro_close = df_macro_ema["close"].iloc[-1]
    macro_ema50 = df_macro_ema["ema_50"].iloc[-1]
    macro_ema200 = df_macro_ema["ema_200"].iloc[-1]

    # Bias macro
    if macro_close > macro_ema50 > macro_ema200:
        macro_bias = "bullish"
    elif macro_close < macro_ema50 < macro_ema200:
        macro_bias = "bearish"
    else:
        macro_bias = "neutral"

    # Alinhamento
    aligned = (
        (macro_bias == "bullish" and micro_structure in ["uptrend", "ranging"]) or
        (macro_bias == "bearish" and micro_structure in ["downtrend", "ranging"])
    )

    score = 0.65 if macro_bias != "neutral" else 0.0
    if aligned:
        score += 0.15

    result.update({
        "detected": macro_bias != "neutral",
        "bias": macro_bias,
        "aligned": aligned,
        "macro_structure": macro_structure,
        "micro_structure": micro_structure,
        "score": min(score, 1.0),
        "description": f"Macro={macro_structure}({macro_bias}) | Micro={micro_structure} | Aligned={aligned}",
    })
    return result


# ── Analisador de Contexto Principal ─────────────────────────────────────────

class ContextAnalyzer:
    """Executa todos os analisadores de contexto e retorna resultados combinados."""

    def analyze_all(
        self,
        df_primary: pd.DataFrame,
        df_macro: pd.DataFrame,
        df_micro: pd.DataFrame,
    ) -> Dict:
        contexts = {}

        contexts["liquidity"] = analyze_liquidity_capture(df_primary)
        contexts["wyckoff"] = analyze_wyckoff(df_primary)
        contexts["flow_inversion"] = analyze_flow_inversion(df_primary)
        contexts["breakout"] = analyze_breakout(df_primary)
        contexts["macro_micro"] = analyze_macro_micro(df_macro, df_micro)

        # Contextos ativos
        active = {k: v for k, v in contexts.items() if v.get("detected")}

        # Direção predominante
        bullish = sum(1 for v in active.values() if v.get("direction") == "bullish" or v.get("bias") == "bullish")
        bearish = sum(1 for v in active.values() if v.get("direction") == "bearish" or v.get("bias") == "bearish")

        direction = "bullish" if bullish > bearish else ("bearish" if bearish > bullish else None)
        context_score = max(
            sum(v.get("score", 0) for v in active.values()) / max(len(active), 1),
            0,
        )

        return {
            "contexts": contexts,
            "active_contexts": list(active.keys()),
            "active_count": len(active),
            "direction": direction,
            "context_score": round(context_score, 3),
            "descriptions": [v.get("description", "") for v in active.values() if v.get("description")],
        }
