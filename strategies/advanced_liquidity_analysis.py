"""
ANALISES AVANCADAS DE LIQUIDEZ E ESTRUTURA WYCKOFF
Implementa os 10 pontos faltantes no bot:

1. Regiões de Liquidez Mapeadas (SL, BSL, EQL, EQH, SH)
2. Liquidez Interna vs Externa
3. Estruturas Wyckoff Nomeadas (SC, AR, ST, UA, LPS, mSOW, BC, PSY, UTAD)
4. SMS - Shift of Market Structure (relutância)
5. Correções Laterais (Reacumulação/Redistribuição)
6. Pernada 3 de Inversão de Fluxo
7. Validação de Plano Operacional Diário
8. Capturas de Liquidez Dentro de Estrutura
9. Validação de Continuidade POI
10. Detecção Manipulação vs Real (Volume confirmation)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from strategies.indicators import find_swing_highs_lows, analyze_volume
from utils.logger import setup_logger

logger = setup_logger("advanced_liquidity")


# ════════════════════════════════════════════════════════════════════════════════
# 1. REGIÕES DE LIQUIDEZ MAPEADAS (SL, BSL, EQL, EQH, SH)
# ════════════════════════════════════════════════════════════════════════════════

class LiquidityRegions:
    """
    SL = Swing Low (fundo de swing)
    SLL = Swing Low Level (nível exato)
    BSL = Below Swing Low (abaixo do fundo)
    
    SH = Swing High (topo de swing)
    
    EQL = Equal Liquidity (topo anterior que não foi renovado) 
    EQH = Equal High Liquidity
    """
    
    @staticmethod
    def map_liquidity_zones(df: pd.DataFrame, lookback: int = 50) -> Dict:
        """Mapeia todas as regiões de liquidez importantes."""
        
        swings = find_swing_highs_lows(df, lookback=10)
        result = {
            "swing_lows": [],      # SL
            "swing_highs": [],     # SH
            "below_swing_low": [], # BSL
            "equal_lows": [],      # EQL
            "equal_highs": [],     # EQH
            "liquidity_zones": []
        }
        
        # Pega swings últimos 50 candles
        highs = df[swings["swing_high"]]["high"].tail(lookback)
        lows = df[swings["swing_low"]]["low"].tail(lookback)
        
        if len(highs) > 0:
            # SH = Swing Highs
            result["swing_highs"] = highs.values.tolist()
            
            # EQH = Highs antigos que não foram renovados (bullish continuation)
            for i, h in enumerate(highs[:-1]):
                if h > highs.iloc[-1]:  # Topo antigo maior que topo recente
                    result["equal_highs"].append({
                        "level": h,
                        "age": len(highs) - i,
                        "strength": i + 1  # Mais antigo = mais forte
                    })
        
        if len(lows) > 0:
            # SL = Swing Lows
            result["swing_lows"] = lows.values.tolist()
            
            # BSL = Abaixo do swing low (área de captura)
            last_sl = lows.iloc[-1]
            atr = df["atr"].iloc[-1] if "atr" in df.columns else (df["high"].iloc[-20:].max() - df["low"].iloc[-20:].min()) / 2
            result["below_swing_low"] = {
                "level": last_sl,
                "capture_zone": [last_sl - atr * 0.5, last_sl],
                "danger_zone": [last_sl - atr, last_sl - atr * 0.5]
            }
            
            # EQL = Lows antigos que não foram penetrados (bearish continuation)
            for i, l in enumerate(lows[:-1]):
                if l < lows.iloc[-1]:  # Fundo antigo menor que fundo recente
                    result["equal_lows"].append({
                        "level": l,
                        "age": len(lows) - i,
                        "strength": i + 1
                    })
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 2. LIQUIDEZ INTERNA vs EXTERNA
# ════════════════════════════════════════════════════════════════════════════════

class InternalExternalLiquidity:
    """
    Liquidez Interna = Fundos dentro de uma estrutura (fundo antigo dentro de lateral)
    Liquidez Externa = Fundos fora (abaixo/acima da estrutura)
    
    Interna = mais forte (smart money já está lá)
    Externa = quebra de estrutura (mais agressiva)
    """
    
    @staticmethod
    def analyze_liquidity_location(df: pd.DataFrame, structure_bounds: Tuple[float, float]) -> Dict:
        """
        Determina se a liquidez está dentro (interna) ou fora (externa) da estrutura.
        
        structure_bounds = (min_price, max_price) = limites da estrutura atual
        """
        
        low_min, high_max = structure_bounds
        last_low = df["low"].iloc[-1]
        last_high = df["high"].iloc[-1]
        
        swings = find_swing_highs_lows(df, lookback=10)
        swing_lows = df[swings["swing_low"]]["low"].tail(3)
        swing_highs = df[swings["swing_high"]]["high"].tail(3)
        
        result = {
            "type": None,  # "internal", "external", "boundary"
            "lows_location": None,
            "highs_location": None,
            "confidence": 0.0,
            "description": ""
        }
        
        # Verifica localização dos fundos
        if len(swing_lows) > 0:
            avg_low = swing_lows.mean()
            
            if low_min <= avg_low <= high_max:
                result["lows_location"] = "internal"
                result["confidence"] += 0.35
                result["description"] += "Fundos internos (força) "
            elif avg_low < low_min:
                result["lows_location"] = "external"
                result["description"] += "Fundos externos (fraco) "
        
        # Verifica localização dos topos
        if len(swing_highs) > 0:
            avg_high = swing_highs.mean()
            
            if low_min <= avg_high <= high_max:
                result["highs_location"] = "internal"
                result["confidence"] += 0.35
                result["description"] += "Topos internos (força) "
            elif avg_high > high_max:
                result["highs_location"] = "external"
                result["description"] += "Topos externos (impulso) "
        
        # Conclusão
        if result["lows_location"] == "internal" or result["highs_location"] == "internal":
            result["type"] = "internal"
        else:
            result["type"] = "external"
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 3. ESTRUTURAS WYCKOFF NOMEADAS
# ════════════════════════════════════════════════════════════════════════════════

class NamedWyckoffStructures:
    """
    SC = Spring (rejeição no suporte)
    AR = Automatic Rally (rali após spring)
    ST = Secondary Test (teste secundário)
    UA = Upthrust (rejeição no topo)
    LPS = Last Point of Support
    mSOW = Minor Sell Off Worth
    BC = Back Clift
    PSY = Preliminary Supply (oferta)
    UTAD = Upthrust Above Downtrend
    """
    
    @staticmethod
    def detect_wyckoff_structures(df: pd.DataFrame) -> Dict:
        """Detecta estruturas Wyckoff nomeadas."""
        
        result = {
            "structures": [],
            "current_phase": None,
            "entry_opportunities": []
        }
        
        swings = find_swing_highs_lows(df, lookback=20)
        swing_lows = df[swings["swing_low"]]["low"].tail(10)
        swing_highs = df[swings["swing_high"]]["high"].tail(10)
        closes = df["close"].tail(20)
        
        last_low = swing_lows.iloc[-1] if len(swing_lows) > 0 else df["low"].iloc[-1]
        last_high = swing_highs.iloc[-1] if len(swing_highs) > 0 else df["high"].iloc[-1]
        
        # SC - Spring: Penetração rápida do suporte com fechamento acima
        if len(swing_lows) >= 2:
            prev_low = swing_lows.iloc[-2]
            if df["low"].iloc[-1] < prev_low and df["close"].iloc[-1] > prev_low:
                result["structures"].append({
                    "name": "Spring (SC)",
                    "confidence": 0.8,
                    "action": "PREPARE BUY",
                    "reason": "Rejeição do suporte com fechamento acima"
                })
                result["entry_opportunities"].append("spring_reversal")
        
        # UA - Upthrust: Penetração rápida da resistência com fechamento abaixo
        if len(swing_highs) >= 2:
            prev_high = swing_highs.iloc[-2]
            if df["high"].iloc[-1] > prev_high and df["close"].iloc[-1] < prev_high:
                result["structures"].append({
                    "name": "Upthrust (UA)",
                    "confidence": 0.8,
                    "action": "PREPARE SHORT",
                    "reason": "Rejeição da resistência com fechamento abaixo"
                })
                result["entry_opportunities"].append("upthrust_reversal")
        
        # UTAD - Upthrust Above Downtrend: UA em downtrend
        if len(closes) >= 5:
            if closes.iloc[-5] > closes.iloc[-1]:  # Downtrend
                if df["high"].iloc[-1] > swing_highs.max() and df["close"].iloc[-1] < df["open"].iloc[-1]:
                    result["structures"].append({
                        "name": "Upthrust Above Downtrend (UTAD)",
                        "confidence": 0.9,
                        "action": "STRONG SHORT",
                        "reason": "UA confirmada em downtrend estabelecido"
                    })
                    result["entry_opportunities"].append("utad_entry")
        
        # LPS - Last Point of Support: Último suporte antes da queda
        if len(swing_lows) >= 3:
            if swing_lows.iloc[-1] < swing_lows.iloc[-2] and swing_lows.iloc[-2] > swing_lows.iloc[-3]:
                result["structures"].append({
                    "name": "Last Point of Support (LPS)",
                    "confidence": 0.75,
                    "level": swing_lows.iloc[-2],
                    "action": "WATCH FOR BREAK"
                })
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 4. SMS - SHIFT OF MARKET STRUCTURE (Relutância)
# ════════════════════════════════════════════════════════════════════════════════

class ShiftOfMarketStructure:
    """
    SMS = Relutância em renovar máximos ou mínimos
    Sinal de esgotamento e possível reversão
    """
    
    @staticmethod
    def detect_sms(df: pd.DataFrame) -> Dict:
        """Detecta SMS (relutância)."""
        
        result = {
            "detected": False,
            "type": None,  # "reluctance_high", "reluctance_low"
            "strength": 0.0,
            "description": ""
        }
        
        if len(df) < 5:
            return result
        
        highs = df["high"].tail(10).values
        lows = df["low"].tail(10).values
        closes = df["close"].tail(10).values
        
        # SMS para topos (relutância em renovar máximos)
        recent_highs = highs[-3:]
        if len(recent_highs) >= 2:
            # Topo recente é menor que anterior = SMS
            if recent_highs[-1] < recent_highs[-2] and recent_highs[-2] < highs[-5]:
                result["detected"] = True
                result["type"] = "reluctance_high"
                result["strength"] = 0.7 + (0.2 if closes[-1] < closes[-2] else 0)
                result["description"] = f"Relutância em renovar topos | Recente={recent_highs[-1]:.4f} < Anterior={recent_highs[-2]:.4f}"
        
        # SMS para fundos (relutância em renovar mínimos)
        recent_lows = lows[-3:]
        if len(recent_lows) >= 2:
            if recent_lows[-1] > recent_lows[-2] and recent_lows[-2] > lows[-5]:
                result["detected"] = True
                result["type"] = "reluctance_low"
                result["strength"] = 0.7 + (0.2 if closes[-1] > closes[-2] else 0)
                result["description"] = f"Relutância em renovar fundos | Recente={recent_lows[-1]:.4f} > Anterior={recent_lows[-2]:.4f}"
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 5. CORREÇÕES LATERAIS (Reacumulação/Redistribuição)
# ════════════════════════════════════════════════════════════════════════════════

class LateralCorrections:
    """
    Reacumulação em uptrend = acumulação de mais força para subir
    Redistribuição em downtrend = distribuição antes de descer mais
    """
    
    @staticmethod
    def detect_lateral_phase(df: pd.DataFrame) -> Dict:
        """Detecta fases laterais com significado."""
        
        result = {
            "detected": False,
            "type": None,  # "reaccumulation", "redistribution"
            "bias": None,  # "bullish", "bearish"
            "bonus_confidence": 0.0,
            "description": ""
        }
        
        if len(df) < 20:
            return result
        
        # Calcula trend macro
        ema_20 = df["close"].ewm(span=20).mean()
        ema_50 = df["close"].ewm(span=50).mean()
        
        # Identifica range (lateral)
        recent_high = df["high"].tail(15).max()
        recent_low = df["low"].tail(15).min()
        range_size = recent_high - recent_low
        range_pct = (range_size / recent_low) * 100
        
        is_lateral = range_pct < 3  # Range menor que 3%
        
        if is_lateral:
            # Reacumulação: lateral em uptrend
            if ema_20.iloc[-1] > ema_50.iloc[-1] and df["close"].iloc[-5:].mean() > ema_50.iloc[-1]:
                result["detected"] = True
                result["type"] = "reaccumulation"
                result["bias"] = "bullish"
                result["bonus_confidence"] = 0.25
                result["description"] = "Reacumulação em uptrend | Entrada tem força extra"
            
            # Redistribuição: lateral em downtrend
            elif ema_20.iloc[-1] < ema_50.iloc[-1] and df["close"].iloc[-5:].mean() < ema_50.iloc[-1]:
                result["detected"] = True
                result["type"] = "redistribution"
                result["bias"] = "bearish"
                result["bonus_confidence"] = 0.25
                result["description"] = "Redistribuição em downtrend | Short tem força extra"
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 6. PERNADA 3 DE INVERSÃO DE FLUXO
# ════════════════════════════════════════════════════════════════════════════════

class LegThreeFlowReversal:
    """
    Inversão de Fluxo = 1,2,3 BOS contra tendência
    Pernada 3 = momento de máxima oportunidade
    """
    
    @staticmethod
    def detect_leg_three(df: pd.DataFrame) -> Dict:
        """Detecta pernada 3 de inversão de fluxo."""
        
        result = {
            "detected": False,
            "leg": None,  # 1, 2, 3
            "confidence": 0.0,
            "bonus": 0.0,
            "description": ""
        }
        
        if len(df) < 10:
            return result
        
        closes = df["close"].tail(10).values
        highs = df["high"].tail(10).values
        lows = df["low"].tail(10).values
        
        # Pernada 1: BOS inicial
        if closes[-1] < closes[-5] and lows[-1] < lows[-5]:
            result["leg"] = 1
        # Pernada 2: Retorno (segundo movimento)
        elif closes[-1] > closes[-3] and closes[-1] < closes[-5]:
            result["leg"] = 2
        # Pernada 3: Novo BOS (PRIME ENTRY)
        elif closes[-1] < lows[-3] and closes[-1] < closes[-5]:
            result["detected"] = True
            result["leg"] = 3
            result["confidence"] = 0.85
            result["bonus"] = 0.30  # +30% no score
            result["description"] = "Pernada 3 detectada | Entrada FORTE de inversão"
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 7. VALIDAÇÃO DE PLANO OPERACIONAL DIÁRIO
# ════════════════════════════════════════════════════════════════════════════════

class DailyOperationalPlan:
    """
    Valida se a operação está DENTRO do plano do dia
    Sem plano = sem operação (disciplina profissional)
    """
    
    def __init__(self):
        self.daily_plan = {
            "direction": None,  # "bullish", "bearish", "neutral"
            "key_levels": [],
            "main_context": None,
            "created_at": None,
            "locked": False
        }
    
    def create_plan(self, df: pd.DataFrame, direction: str, context: str, levels: List[float]):
        """Cria plano operacional diário."""
        self.daily_plan = {
            "direction": direction,
            "key_levels": levels,
            "main_context": context,
            "created_at": pd.Timestamp.now(),
            "locked": True
        }
        logger.info(f"Plano diário criado: {direction.upper()} | Context: {context}")
    
    def validate_trade(self, symbol: str, direction: str, entry: float) -> Dict:
        """Valida se trade está no plano."""
        
        result = {
            "is_valid": True,
            "reason": "",
            "penalty": 0.0
        }
        
        if not self.daily_plan["locked"]:
            result["reason"] = "Plano diário não criado"
            result["is_valid"] = False
            return result
        
        # Direção está no plano?
        if direction != self.daily_plan["direction"]:
            if self.daily_plan["direction"] != "neutral":
                result["reason"] = f"Trade CONTRA o plano | Plano={self.daily_plan['direction']}, Trade={direction}"
                result["is_valid"] = False
                result["penalty"] = 0.20  # -20% confiança
        else:
            result["reason"] = "Trade ALINHADO com plano diário"
            result["is_valid"] = True
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 8. CAPTURAS DE LIQUIDEZ DENTRO DE ESTRUTURA
# ════════════════════════════════════════════════════════════════════════════════

class InternalStructureLiquidityCapture:
    """
    Oportunidades que ocorrem DURANTE a formação de estrutura
    Mais finas e precisas que capturas externas
    """
    
    @staticmethod
    def detect_internal_capture(df: pd.DataFrame, structure_start_idx: int) -> Dict:
        """
        Detecta capturas internas durante uma estrutura.
        structure_start_idx = índice de início da estrutura
        """
        
        result = {
            "detected": False,
            "captures": [],
            "description": ""
        }
        
        if len(df) < 30 or structure_start_idx < 0:
            return result
        
        structure_df = df.iloc[structure_start_idx:].reset_index(drop=True)
        
        # Procura por topos e fundos antigos dentro da estrutura
        highs = structure_df["high"].values
        lows = structure_df["low"].values
        closes = structure_df["close"].values
        
        for i in range(5, len(structure_df) - 2):
            # Verifica se há capture de fundo antigo
            old_low = lows[max(0, i - 5):i].min()
            if closes[i] < old_low and closes[i + 1] > old_low:
                result["detected"] = True
                result["captures"].append({
                    "type": "internal_low_capture",
                    "level": old_low,
                    "idx": i,
                    "confidence": 0.75
                })
            
            # Verifica se há capture de topo antigo
            old_high = highs[max(0, i - 5):i].max()
            if closes[i] > old_high and closes[i + 1] < old_high:
                result["detected"] = True
                result["captures"].append({
                    "type": "internal_high_capture",
                    "level": old_high,
                    "idx": i,
                    "confidence": 0.75
                })
        
        if result["detected"]:
            result["description"] = f"Detectadas {len(result['captures'])} capturas internas"
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 9. VALIDAÇÃO DE CONTINUIDADE POI
# ════════════════════════════════════════════════════════════════════════════════

class ContinuityPOIValidation:
    """
    POI de continuidade = estrutura que continua o movimento
    vs
    POI simples = só zona de suporte/resistência
    
    Continuidade = mais forte (+30% confiança)
    """
    
    @staticmethod
    def validate_poi_continuation(df: pd.DataFrame, poi_level: float) -> Dict:
        """
        Valida se POI tem ESTRUTURA DE CONTINUIDADE.
        """
        
        result = {
            "is_continuation": False,
            "strength": 0.0,
            "bonus": 0.0,
            "description": ""
        }
        
        if len(df) < 20:
            return result
        
        last_close = df["close"].iloc[-1]
        
        # Se está testando POI
        if abs(last_close - poi_level) / poi_level < 0.005:  # Dentro de 0.5%
            
            # Verifica se há estrutura de continuidade (swing prévio)
            highs = df["high"].tail(15).values
            lows = df["low"].tail(15).values
            closes = df["close"].tail(15).values
            
            # Padrão de continuidade: BOS + pullback + break novamente
            if len(closes) >= 5:
                # Procura por movimentos direcionales
                uptrend = closes[-1] > closes[-5]
                downtrend = closes[-1] < closes[-5]
                
                # Em uptrend: pullback em POI + break para cima
                if uptrend and min(closes[-3:]) < poi_level < max(closes[-3:]):
                    result["is_continuation"] = True
                    result["strength"] = 0.8
                    result["bonus"] = 0.30
                    result["description"] = "POI com estrutura de continuidade BULLISH"
                
                # Em downtrend: pullback em POI + break para baixo
                elif downtrend and min(closes[-3:]) < poi_level < max(closes[-3:]):
                    result["is_continuation"] = True
                    result["strength"] = 0.8
                    result["bonus"] = 0.30
                    result["description"] = "POI com estrutura de continuidade BEARISH"
        
        return result


# ════════════════════════════════════════════════════════════════════════════════
# 10. DETECÇÃO MANIPULAÇÃO vs REAL (Volume Confirmation)
# ════════════════════════════════════════════════════════════════════════════════

class ManipulationVsRealDetection:
    """
    Capture de liquidez FAKE = movimento técnico sem confirmação
    Capture de liquidez REAL = com volume e follow-through
    
    Real = confiança total
    Fake = descontar -40% confiança
    """
    
    @staticmethod
    def validate_capture_authenticity(df: pd.DataFrame) -> Dict:
        """
        Valida se a captura é REAL (com volume) ou FAKE (técnica).
        """
        
        result = {
            "is_real": True,
            "confidence_multiplier": 1.0,
            "description": ""
        }
        
        if len(df) < 5:
            return result
        
        last_vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].tail(20).mean()
        
        last_close = df["close"].iloc[-1]
        last_open = df["open"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        
        # Volume spike na vela de captura?
        vol_spike = last_vol > avg_vol * 1.3
        
        # Fechamento confirmou movimento?
        body = abs(last_close - last_open)
        wick = max(df["high"].iloc[-1], df["high"].iloc[-2]) - min(df["close"].iloc[-1], df["open"].iloc[-1])
        
        has_follow_through = body > wick * 0.3
        
        # Validação
        if vol_spike and has_follow_through:
            result["is_real"] = True
            result["confidence_multiplier"] = 1.2  # +20% confiança
            result["description"] = "Captura REAL | Volume + Follow-through confirmado"
        elif vol_spike and not has_follow_through:
            result["is_real"] = False
            result["confidence_multiplier"] = 0.75  # -25% confiança
            result["description"] = "Captura QUESTIONÁVEL | Volume mas sem follow-through"
        elif not vol_spike and has_follow_through:
            result["is_real"] = True
            result["confidence_multiplier"] = 0.95  # Leve desconto
            result["description"] = "Captura REAL | Follow-through sem spike (smart money)"
        else:
            result["is_real"] = False
            result["confidence_multiplier"] = 0.6  # -40% confiança
            result["description"] = "Captura FAKE | Sem volume, sem follow-through"
        
        return result
