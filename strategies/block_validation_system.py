"""
Validação de Blocos e Rompimentos
- Demand/Supply Breakout Validation: Valida se demanda/oferta realmente "não entrou"
- Order Block Legitimacy: Verifica se OB nasceu de consolidação real
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional


class DemandSupplyValidator:
    """
    Valida rompimentos de demanda/oferta.
    
    Conceito:
    - Quando rompe uma região de DEMANDA (compra), valida se a demanda NÃO entrou
    - Quando rompe uma região de OFERTA (venda), valida se a oferta NÃO entrou
    - Se demanda/oferta entrou onde era pra entrar = rompimento FAKE
    - Se demanda/oferta NÃO entrou = rompimento LEGÍTIMO
    
    Bonus: +20% confiança se rompimento é validado como legítimo
    Penalidade: -15% se validado como fake
    """
    
    @staticmethod
    def validate_breakout(
        df: pd.DataFrame,
        poi_level: float,
        direction: str,  # "buy" ou "sell"
        lookback: int = 20
    ) -> Dict:
        """
        Valida se um rompimento é legítimo ou fake.
        
        Args:
            df: DataFrame com OHLCV
            poi_level: Nível de POI que foi rompido
            direction: "buy" (rompeu oferta) ou "sell" (rompeu demanda)
            lookback: Candles para validar comportamento
            
        Returns:
            {
                "is_legitimate": bool,
                "reason": str,
                "confidence": float (0.0-1.0),
                "bonus": float (+0.20 se legítimo, -0.15 se fake),
                "entry_action": str ("COMPRE COM CONFIANÇA" ou "VENDA COM CONFIANÇA" ou "SKIP"),
                "validation_data": {...}
            }
        """
        
        if len(df) < lookback + 5:
            return {
                "is_legitimate": False,
                "reason": "Dados insuficientes",
                "confidence": 0.0,
                "bonus": 0.0,
                "entry_action": "SKIP",
                "validation_data": {}
            }
        
        result = {
            "is_legitimate": False,
            "reason": "",
            "confidence": 0.0,
            "bonus": 0.0,
            "entry_action": "SKIP",
            "validation_data": {}
        }
        
        recent_df = df.iloc[-lookback:].copy()
        current_price = df["close"].iloc[-1]
        
        if direction == "sell":
            # Rompeu DEMANDA (POI de compra)
            # Validar: demanda NÃO entrou onde era pra entrar
            
            # Demanda "entra" se houver toques no POI após rompimento
            touches_at_poi = 0
            for idx, row in recent_df.iterrows():
                if row["low"] <= poi_level <= row["high"]:
                    touches_at_poi += 1
            
            # Validação: se demanda NÃO tocou POI = "Sem demanda" = Legítimo
            if touches_at_poi == 0:
                result["is_legitimate"] = True
                result["reason"] = "Sem demanda - Demanda NÃO entrou onde era para entrar"
                result["confidence"] = 0.85
                result["bonus"] = 0.20  # +20% confiança
                result["entry_action"] = "VENDA COM CONFIANÇA"
            else:
                result["is_legitimate"] = False
                result["reason"] = f"Demanda entrou - {touches_at_poi} toques no POI após rompimento"
                result["confidence"] = 0.3
                result["bonus"] = -0.15  # -15% confiança (fake)
                result["entry_action"] = "SKIP - Rompimento Fake"
        
        elif direction == "buy":
            # Rompeu OFERTA (POI de venda)
            # Validar: oferta NÃO entrou onde era pra entrar
            
            # Oferta "entra" se houver toques no POI após rompimento
            touches_at_poi = 0
            for idx, row in recent_df.iterrows():
                if row["low"] <= poi_level <= row["high"]:
                    touches_at_poi += 1
            
            # Validação: se oferta NÃO tocou POI = "Sem oferta" = Legítimo
            if touches_at_poi == 0:
                result["is_legitimate"] = True
                result["reason"] = "Sem oferta - Oferta NÃO entrou onde era para entrar"
                result["confidence"] = 0.85
                result["bonus"] = 0.20  # +20% confiança
                result["entry_action"] = "COMPRE COM CONFIANÇA"
            else:
                result["is_legitimate"] = False
                result["reason"] = f"Oferta entrou - {touches_at_poi} toques no POI após rompimento"
                result["confidence"] = 0.3
                result["bonus"] = -0.15  # -15% confiança (fake)
                result["entry_action"] = "SKIP - Rompimento Fake"
        
        result["validation_data"] = {
            "poi_level": poi_level,
            "current_price": current_price,
            "touches_at_poi": touches_at_poi,
            "lookback_candles": lookback
        }
        
        return result
    
    @staticmethod
    def detect_demand_supply_regions(
        df: pd.DataFrame,
        lookback: int = 50
    ) -> Dict:
        """
        Detecta regiões de demanda e oferta no gráfico.
        
        Demanda: Região onde compradores entraram (suporte com volume)
        Oferta: Região onde vendedores entraram (resistência com volume)
        
        Returns:
            {
                "demand_regions": [{"level": float, "strength": float, "candle_idx": int}],
                "supply_regions": [{"level": float, "strength": float, "candle_idx": int}],
                "active_demand": float or None,
                "active_supply": float or None
            }
        """
        
        if len(df) < lookback:
            return {
                "demand_regions": [],
                "supply_regions": [],
                "active_demand": None,
                "active_supply": None
            }
        
        recent_df = df.iloc[-lookback:].copy()
        demand_regions = []
        supply_regions = []
        
        # Detectar regiões de demanda (suportes com bom volume)
        for i in range(1, len(recent_df) - 2):
            low_before = recent_df["low"].iloc[i - 1]
            low_curr = recent_df["low"].iloc[i]
            low_after = recent_df["low"].iloc[i + 1]
            volume_curr = recent_df["volume"].iloc[i] if "volume" in recent_df.columns else 1
            
            # Mínimo local = potencial demanda
            if low_curr < low_before and low_curr < low_after:
                strength = min(1.0, volume_curr / (recent_df["volume"].max() if "volume" in recent_df.columns else 1))
                demand_regions.append({
                    "level": low_curr,
                    "strength": strength,
                    "candle_idx": i,
                    "type": "demand_low"
                })
        
        # Detectar regiões de oferta (resistências com bom volume)
        for i in range(1, len(recent_df) - 2):
            high_before = recent_df["high"].iloc[i - 1]
            high_curr = recent_df["high"].iloc[i]
            high_after = recent_df["high"].iloc[i + 1]
            volume_curr = recent_df["volume"].iloc[i] if "volume" in recent_df.columns else 1
            
            # Máximo local = potencial oferta
            if high_curr > high_before and high_curr > high_after:
                strength = min(1.0, volume_curr / (recent_df["volume"].max() if "volume" in recent_df.columns else 1))
                supply_regions.append({
                    "level": high_curr,
                    "strength": strength,
                    "candle_idx": i,
                    "type": "supply_high"
                })
        
        # Identificar regiões mais ativas (recentes e com bom volume)
        active_demand = None
        active_supply = None
        
        if demand_regions:
            # Demanda mais recente com força significativa
            strong_demands = [d for d in demand_regions if d["strength"] > 0.5]
            if strong_demands:
                active_demand = strong_demands[-1]["level"]  # Mais recente
        
        if supply_regions:
            # Oferta mais recente com força significativa
            strong_supplies = [s for s in supply_regions if s["strength"] > 0.5]
            if strong_supplies:
                active_supply = strong_supplies[-1]["level"]  # Mais recente
        
        return {
            "demand_regions": sorted(demand_regions, key=lambda x: x["level"]),
            "supply_regions": sorted(supply_regions, key=lambda x: x["level"]),
            "active_demand": active_demand,
            "active_supply": active_supply
        }


class OrderBlockLegitimacyChecker:
    """
    Verifica se um Order Block é legítimo.
    
    Conceito:
    - OB legítimo = nascido de CONSOLIDAÇÃO (não apenas qualquer vela)
    - No TF Maior (1h): Última vela de BAIXA antes do grande movimento de ALTA
    - No TF Menor (5m): Mesma região deve ser LATERALIDADE (consolidação)
    - Se OB é legítimo = confiança, se fake = skip
    
    Bonus: +15% se OB é legítimo
    Penalidade: -10% se OB é fake
    """
    
    @staticmethod
    def validate_order_block(
        df_macro: pd.DataFrame,  # TF maior (1h)
        df_micro: pd.DataFrame,  # TF menor (5m)
        ob_price: float,
        direction: str  # "buy" ou "sell"
    ) -> Dict:
        """
        Valida legitimidade de um Order Block.
        
        Args:
            df_macro: DataFrame com timeframe maior (1h, 4h)
            df_micro: DataFrame com timeframe menor (5m, 15m)
            ob_price: Preço do OB
            direction: "buy" (OB de venda = suporte) ou "sell" (OB de compra = resistência)
            
        Returns:
            {
                "is_legitimate": bool,
                "confidence": float (0.0-1.0),
                "bonus": float (+0.15 se legítimo, -0.10 se fake),
                "reason": str,
                "consolidation_strength": float,
                "validity_level": str ("FORTE", "MODERADO", "FRACO", "FAKE")
            }
        """
        
        result = {
            "is_legitimate": False,
            "confidence": 0.0,
            "bonus": 0.0,
            "reason": "",
            "consolidation_strength": 0.0,
            "validity_level": "FRACO"
        }
        
        if len(df_macro) < 5 or len(df_micro) < 10:
            result["reason"] = "Dados insuficientes"
            return result
        
        # 1. Validar Macro TF: OB nasceu de consolidação?
        last_candle_macro = df_macro.iloc[-1]
        
        if direction == "buy":
            # OB de compra (suporte) = última vela de BAIXA antes de alta
            # Verificar: vela anterior foi de queda?
            prev_candle = df_macro.iloc[-2]
            is_after_downtrend = prev_candle["close"] < prev_candle["open"]
            
            if not is_after_downtrend:
                result["reason"] = "OB não foi criado após downtrend (não é consolidação)"
                result["validity_level"] = "FAKE"
                result["bonus"] = -0.10
                return result
        
        elif direction == "sell":
            # OB de venda (resistência) = última vela de ALTA antes de queda
            # Verificar: vela anterior foi de alta?
            prev_candle = df_macro.iloc[-2]
            is_after_uptrend = prev_candle["close"] > prev_candle["open"]
            
            if not is_after_uptrend:
                result["reason"] = "OB não foi criado após uptrend (não é consolidação)"
                result["validity_level"] = "FAKE"
                result["bonus"] = -0.10
                return result
        
        # 2. Validar Micro TF: Mesma região foi consolidação?
        consolidation_strength = OrderBlockLegitimacyChecker._check_consolidation(
            df_micro, ob_price
        )
        
        result["consolidation_strength"] = consolidation_strength
        
        # 3. Classificar legitimidade
        if consolidation_strength > 0.7:
            result["is_legitimate"] = True
            result["confidence"] = 0.90
            result["bonus"] = 0.15  # +15% confiança
            result["validity_level"] = "FORTE"
            result["reason"] = f"OB legítimo - consolidação real detectada ({consolidation_strength:.0%})"
        
        elif consolidation_strength > 0.5:
            result["is_legitimate"] = True
            result["confidence"] = 0.75
            result["bonus"] = 0.10  # +10% confiança
            result["validity_level"] = "MODERADO"
            result["reason"] = f"OB moderado - consolidação parcial ({consolidation_strength:.0%})"
        
        else:
            result["is_legitimate"] = False
            result["confidence"] = 0.3
            result["bonus"] = -0.10  # -10% confiança
            result["validity_level"] = "FAKE"
            result["reason"] = f"OB fake - sem consolidação real ({consolidation_strength:.0%})"
        
        return result
    
    @staticmethod
    def _check_consolidation(df: pd.DataFrame, price_level: float, lookback: int = 20) -> float:
        """
        Verifica força da consolidação em torno do price_level.
        
        Consolidação = região lateral com baixa volatilidade
        Retorna: 0.0-1.0 força da consolidação
        """
        
        if len(df) < lookback:
            return 0.0
        
        recent_df = df.iloc[-lookback:].copy()
        range_size = price_level * 0.005  # Tolerância de 0.5% em torno do preço
        
        # Candles que tocam/estão perto do nível
        candles_in_range = 0
        for idx, row in recent_df.iterrows():
            if price_level - range_size <= row["low"] and row["high"] <= price_level + range_size:
                candles_in_range += 1
        
        # Força: quanto mais candles perto do nível = consolidação mais forte
        consolidation_strength = min(1.0, candles_in_range / (lookback * 0.6))
        
        # Também validar: volatilidade está baixa?
        atr = recent_df["high"].max() - recent_df["low"].min()
        volatility_ratio = atr / price_level
        
        # Volatilidade baixa = consolidação mais forte
        if volatility_ratio < 0.02:  # < 2% volatilidade
            consolidation_strength *= 1.2  # Bonus 20%
        elif volatility_ratio > 0.05:  # > 5% volatilidade
            consolidation_strength *= 0.5  # Penalidade 50% (não é consolidação)
        
        return min(1.0, consolidation_strength)
    
    @staticmethod
    def detect_order_blocks(
        df: pd.DataFrame,
        lookback: int = 50
    ) -> Dict:
        """
        Detecta Order Blocks no gráfico.
        
        Returns:
            {
                "buy_blocks": [...],
                "sell_blocks": [...],
                "strongest_buy_block": {...} or None,
                "strongest_sell_block": {...} or None
            }
        """
        
        if len(df) < lookback:
            return {
                "buy_blocks": [],
                "sell_blocks": [],
                "strongest_buy_block": None,
                "strongest_sell_block": None
            }
        
        recent_df = df.iloc[-lookback:].copy()
        buy_blocks = []
        sell_blocks = []
        
        for i in range(2, len(recent_df) - 1):
            curr = recent_df.iloc[i]
            prev = recent_df.iloc[i - 1]
            next_candle = recent_df.iloc[i + 1]
            
            # Buy Block: Última vela de queda (consolidação para alta)
            if prev["close"] < prev["open"] and curr["close"] > curr["open"]:
                # Transição de queda para alta = potencial buy block
                buy_blocks.append({
                    "price": prev["low"],
                    "strength": 0.8,
                    "candle_idx": i - 1,
                    "type": "buy_block"
                })
            
            # Sell Block: Última vela de alta (consolidação para queda)
            if prev["close"] > prev["open"] and curr["close"] < curr["open"]:
                # Transição de alta para queda = potencial sell block
                sell_blocks.append({
                    "price": prev["high"],
                    "strength": 0.8,
                    "candle_idx": i - 1,
                    "type": "sell_block"
                })
        
        # Identificar blocos mais fortes
        strongest_buy = max(buy_blocks, key=lambda x: x["strength"]) if buy_blocks else None
        strongest_sell = max(sell_blocks, key=lambda x: x["strength"]) if sell_blocks else None
        
        return {
            "buy_blocks": buy_blocks,
            "sell_blocks": sell_blocks,
            "strongest_buy_block": strongest_buy,
            "strongest_sell_block": strongest_sell
        }
