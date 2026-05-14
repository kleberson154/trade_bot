"""
Análise de Contextos de Mercado:
- Captura de Liquidez
- Estruturas de Wyckoff
- Inversão de Fluxo
- Rompimento de Regiões
- Macro e Micro
- NOVO: 10 Análises Avançadas (Regiões, Liquidez Int/Ext, Wyckoff Nomeado, SMS, Laterais, etc)
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from strategies.indicators import (
    find_swing_highs_lows,
    identify_market_structure,
    analyze_volume,
    add_emas,
    add_atr,
)
from strategies.advanced_liquidity_analysis import (
    LiquidityRegions,
    InternalExternalLiquidity,
    NamedWyckoffStructures,
    ShiftOfMarketStructure,
    LateralCorrections,
    LegThreeFlowReversal,
    DailyOperationalPlan,
    InternalStructureLiquidityCapture,
    ContinuityPOIValidation,
    ManipulationVsRealDetection,
)
from strategies.block_validation_system import (
    DemandSupplyValidator,
    OrderBlockLegitimacyChecker,
)
from strategies.btc_macro_indicator import (
    BTCDominanceAnalyzer,
    BTCTrendValidator,
    BTCMacroAnalyzer,
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
    
    def __init__(self):
        self.daily_plan = DailyOperationalPlan()

    def analyze_all(
        self,
        df_primary: pd.DataFrame,
        df_macro: pd.DataFrame,
        df_micro: pd.DataFrame,
        advanced: bool = True  # Ativa 10 análises avançadas
    ) -> Dict:
        from utils.config import Config
        cfg = Config()
        
        contexts = {}

        contexts["liquidity"] = analyze_liquidity_capture(df_primary)
        contexts["wyckoff"] = analyze_wyckoff(df_primary)
        contexts["flow_inversion"] = analyze_flow_inversion(df_primary)
        contexts["breakout"] = analyze_breakout(df_primary)
        contexts["macro_micro"] = analyze_macro_micro(df_macro, df_micro)

        # NOVO: 10 Análises Avançadas
        if advanced:
            contexts["advanced"] = self.analyze_advanced_structures(df_primary)

        # Separa contextos primários vs suporte
        primary_active = {k: v for k, v in contexts.items() if v.get("detected") and k in cfg.PRIMARY_CONTEXTS}
        support_active = {k: v for k, v in contexts.items() if v.get("detected") and k in cfg.SUPPORT_CONTEXTS}
        
        # Direção predominante (apenas primários)
        bullish = sum(1 for v in primary_active.values() if v.get("direction") == "bullish" or v.get("bias") == "bullish")
        bearish = sum(1 for v in primary_active.values() if v.get("direction") == "bearish" or v.get("bias") == "bearish")

        direction = "bullish" if bullish > bearish else ("bearish" if bearish > bullish else None)
        
        # Score: primários + bônus por suportes alinhados
        primary_score = max(
            sum(v.get("score", 0) for v in primary_active.values()) / max(len(primary_active), 1),
            0,
        )
        
        # Bônus por suportes alinhados (cada um adiciona 8%)
        support_bonus = len(support_active) * cfg.SUPPORT_CONTEXT_BONUS
        context_score = min(primary_score + support_bonus, 1.0)

        return {
            "contexts": contexts,
            "active_contexts": list(primary_active.keys()),  # Apenas primários
            "support_contexts": list(support_active.keys()),  # Suportes separados
            "active_count": len(primary_active),
            "support_count": len(support_active),
            "direction": direction,
            "context_score": round(context_score, 3),
            "descriptions": [v.get("description", "") for v in primary_active.values() if v.get("description")],
        }
    
    def analyze_advanced_structures(self, df: pd.DataFrame) -> Dict:
        """
        NOVO: 10 Análises Avançadas
        1. Regiões de Liquidez Mapeadas
        2. Liquidez Interna vs Externa
        3. Estruturas Wyckoff Nomeadas
        4. SMS - Shift of Market Structure
        5. Correções Laterais
        6. Pernada 3 de Inversão
        7. (Plano é global)
        8. Capturas Dentro de Estrutura
        9. Validação POI Continuidade
        10. Manipulação vs Real
        """
        
        result = {
            "detected": False,
            "structures": [],
            "bonuses": 0.0,  # Bonificação total
            "description": ""
        }
        
        # 1. Regiões de Liquidez
        liq_zones = LiquidityRegions.map_liquidity_zones(df, lookback=50)
        if liq_zones["swing_highs"] or liq_zones["swing_lows"]:
            result["structures"].append({"type": "liquidity_zones", "data": liq_zones})
        
        # 2. Liquidez Interna vs Externa
        if "atr" in df.columns:
            low_min, high_max = df["low"].min(), df["high"].max()
            int_ext = InternalExternalLiquidity.analyze_liquidity_location(df, (low_min, high_max))
            if int_ext["type"] == "internal":
                result["bonuses"] += 0.15  # +15% confiança para liquidez interna
            result["structures"].append({"type": "int_ext_liquidity", "data": int_ext})
        
        # 3. Estruturas Wyckoff Nomeadas
        wyckoff_named = NamedWyckoffStructures.detect_wyckoff_structures(df)
        if wyckoff_named["structures"]:
            for struct in wyckoff_named["structures"]:
                result["bonuses"] += struct.get("confidence", 0) * 0.10
            result["structures"].append({"type": "wyckoff_named", "data": wyckoff_named})
        
        # 4. SMS - Shift of Market Structure
        sms = ShiftOfMarketStructure.detect_sms(df)
        if sms["detected"]:
            result["bonuses"] -= 0.15  # -15% confiança (relutância = esgotamento)
            result["structures"].append({"type": "sms", "data": sms})
        
        # 5. Correções Laterais (Reacumulação/Redistribuição)
        laterals = LateralCorrections.detect_lateral_phase(df)
        if laterals["detected"]:
            result["bonuses"] += laterals["bonus_confidence"]
            result["structures"].append({"type": "lateral_correction", "data": laterals})
        
        # 6. Pernada 3 de Inversão
        leg3 = LegThreeFlowReversal.detect_leg_three(df)
        if leg3["detected"]:
            result["bonuses"] += leg3["bonus"]
            result["structures"].append({"type": "leg_three", "data": leg3})
        
        # 8. Capturas Dentro de Estrutura
        internal_captures = InternalStructureLiquidityCapture.detect_internal_capture(df, max(0, len(df) - 30))
        if internal_captures["detected"]:
            result["bonuses"] += len(internal_captures["captures"]) * 0.10
            result["structures"].append({"type": "internal_captures", "data": internal_captures})
        
        # 9. Validação POI Continuidade
        # (precisa de entrada do POI level, assume último swing)
        swings = find_swing_highs_lows(df, lookback=10)
        if not swings["swing_high"].empty:
            poi_level = df[swings["swing_high"]]["high"].iloc[-1]
            poi_val = ContinuityPOIValidation.validate_poi_continuation(df, poi_level)
            if poi_val["is_continuation"]:
                result["bonuses"] += poi_val["bonus"]
            result["structures"].append({"type": "poi_continuity", "data": poi_val})
        
        # NOVO: 11. Validação Demand/Supply Breakout (Sem demanda/Sem oferta)
        ds_regions = DemandSupplyValidator.detect_demand_supply_regions(df, lookback=50)
        if ds_regions["active_demand"] or ds_regions["active_supply"]:
            result["structures"].append({"type": "demand_supply_regions", "data": ds_regions})
        
        # NOVO: 12. Validação Order Block Legitimidade (OB é consolidação?)
        ob_blocks = OrderBlockLegitimacyChecker.detect_order_blocks(df, lookback=50)
        if ob_blocks["strongest_buy_block"] or ob_blocks["strongest_sell_block"]:
            result["structures"].append({"type": "order_blocks_detected", "data": ob_blocks})
        
        # 10. Manipulação vs Real
        manip_check = ManipulationVsRealDetection.validate_capture_authenticity(df)
        if not manip_check["is_real"]:
            result["bonuses"] *= manip_check["confidence_multiplier"]
        result["structures"].append({"type": "manip_check", "data": manip_check})
        
        result["detected"] = len(result["structures"]) > 0
        result["bonuses"] = round(max(result["bonuses"], -0.4), 2)  # Limita entre -40% e +XXX%
        result["description"] = f"Análises avançadas | Estruturas={len(result['structures'])} | Bonus={result['bonuses']:+.1%}"
        
        return result
    
    def validate_demand_supply_breakout(
        self,
        df: pd.DataFrame,
        poi_level: float,
        direction: str
    ) -> Dict:
        """
        Valida se um rompimento é legítimo (sem demanda/sem oferta).
        
        Args:
            df: DataFrame OHLCV
            poi_level: Nível de POI que foi rompido
            direction: "buy" (rompeu oferta) ou "sell" (rompeu demanda)
        
        Returns: {is_legitimate, confidence, bonus, entry_action, ...}
        """
        return DemandSupplyValidator.validate_breakout(df, poi_level, direction)
    
    def validate_order_block_legitimacy(
        self,
        df_macro: pd.DataFrame,
        df_micro: pd.DataFrame,
        ob_price: float,
        direction: str
    ) -> Dict:
        """
        Valida se um Order Block é legítimo (nascido de consolidação).
        
        Args:
            df_macro: DataFrame com TF maior (1h, 4h)
            df_micro: DataFrame com TF menor (5m, 15m)
            ob_price: Preço do OB
            direction: "buy" ou "sell"
        
        Returns: {is_legitimate, confidence, bonus, validity_level, ...}
        """
        return OrderBlockLegitimacyChecker.validate_order_block(df_macro, df_micro, ob_price, direction)
    
    def validate_with_daily_plan(self, symbol: str, direction: str, entry: float) -> Dict:
        """
        7. Validação de Plano Operacional Diário
        """
        return self.daily_plan.validate_trade(symbol, direction, entry)
    
    def set_daily_plan(self, direction: str, context: str, key_levels: List[float]):
        """Define o plano operacional do dia."""
        self.daily_plan.create_plan(
            pd.DataFrame(),  # dummy
            direction,
            context,
            key_levels
        )
    
    def analyze_btc_macro(self, df_btc: pd.DataFrame, trade_direction: str) -> Dict:
        """
        NOVO: Análise Macro do Bitcoin
        13. Dominância do BTC + Tendência
        
        Args:
            df_btc: DataFrame com dados BTC (1h ou TF correspondente)
            trade_direction: "buy" ou "sell"
        
        Returns: Análise completa com bonuses de dominância e trend
        """
        return BTCMacroAnalyzer.analyze_btc_macro(df_btc, trade_direction)


