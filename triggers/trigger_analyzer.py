"""
Gatilhos de Entrada:
- CHoCH (Change of Character)
- POI (Point of Interest - Estrutura de Continuidade)
- Troca de Polaridade
- FVG (Fair Value Gap)
- IFVG (Inverse Fair Value Gap)

Ao menos 2 gatilhos devem confirmar para operar.
Validação de recenticidade: gatilhos muito antigos são rejeitados ou penalizados.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from strategies.indicators import (
    detect_choch,
    detect_fvg,
    detect_poi,
    detect_polarity_change,
    add_atr,
    analyze_volume,
)
from utils.logger import setup_logger
from utils.config import Config

logger = setup_logger("triggers")


class TriggerAnalyzer:
    """Detecta gatilhos e calcula entrada, SL e TP."""

    MIN_TRIGGERS = 1  # Mínimo de gatilhos para sinal válido (1 contexto + 1 gatilho = válido)

    def __init__(self, config: Optional[Config] = None):
        self.cfg = config or Config()

    # ── Validação de Recenticidade ────────────────────────────────────────────

    def _get_trigger_age(self, trigger_bar: int, current_bar: int) -> int:
        """Retorna quantos candles passaram desde a detecção do gatilho."""
        return current_bar - trigger_bar

    def _is_trigger_recent(self, trigger_bar: int, current_bar: int) -> bool:
        """
        Verifica se gatilho é considerado recente.
        Gatilhos muito antigos são rejeitados (idade > MAX_TRIGGER_AGE_CANDLES).
        """
        age = self._get_trigger_age(trigger_bar, current_bar)
        return age <= self.cfg.MAX_TRIGGER_AGE_CANDLES

    def _apply_age_penalty(self, strength: float, trigger_bar: int, current_bar: int) -> float:
        """
        Aplica penalidade/bônus de força baseado na idade do gatilho.
        
        Lógica:
        - 0-2 candles: bônus de confiança (+10%)
        - 3-MAX_AGE: decay linear (mínimo 70%)
        - Acima de MAX_AGE: penalidade severa (50%)
        """
        if not self.cfg.PREFER_RECENT_TRIGGERS:
            return strength

        age = self._get_trigger_age(trigger_bar, current_bar)
        
        if age <= 2:
            # Muito recente: bônus
            return min(strength * 1.1, 1.0)
        elif age <= self.cfg.MAX_TRIGGER_AGE_CANDLES:
            # Dentro do limite: decaimento linear
            decay_factor = 1.0 - (age / (self.cfg.MAX_TRIGGER_AGE_CANDLES * 2))
            return strength * max(decay_factor, 0.7)
        else:
            # Muito antigo: penalidade severa
            return strength * 0.5

    # ── Análise Principal ─────────────────────────────────────────────────────

    def analyze(self, df: pd.DataFrame, direction_bias: Optional[str] = None) -> Dict:
        """
        Executa todos os gatilhos e retorna sinal consolidado.
        
        Args:
            df: DataFrame com OHLCV
            direction_bias: 'bullish' / 'bearish' / None
            
        Valida recenticidade: rejeita gatilhos muito antigos para evitar
        entradas atrasadas. A idade máxima é definida por MAX_TRIGGER_AGE_CANDLES.
        """
        current_price = df["close"].iloc[-1]
        current_bar = len(df) - 1
        df_atr = add_atr(df)
        atr = df_atr["atr"].iloc[-1]

        triggers_found = []

        # 1. CHoCH
        choch_signals = detect_choch(df)
        for sig in choch_signals:
            if direction_bias is None or sig["direction"] == direction_bias:
                trigger_bar = sig.get("bar", current_bar)
                
                # Valida recenticidade
                if not self._is_trigger_recent(trigger_bar, current_bar):
                    age = self._get_trigger_age(trigger_bar, current_bar)
                    logger.debug(f"CHoCH rejeitado: {age} candles (máximo={self.cfg.MAX_TRIGGER_AGE_CANDLES})")
                    continue

                adjusted_strength = self._apply_age_penalty(sig["strength"], trigger_bar, current_bar)
                triggers_found.append({
                    "trigger": "CHoCH",
                    "direction": sig["direction"],
                    "price": sig["price"],
                    "strength": adjusted_strength,
                    "bar": trigger_bar,
                    "age_candles": self._get_trigger_age(trigger_bar, current_bar),
                })

        # 2. FVG / IFVG
        fvgs = detect_fvg(df)
        for fvg in fvgs[-5:]:  # Últimos 5 FVGs
            fvg_dir = fvg["direction"]
            if direction_bias and fvg_dir != direction_bias:
                continue
            if current_price <= fvg["top"] and current_price >= fvg["bottom"]:
                trigger_bar = fvg.get("bar", current_bar)
                
                # Valida recenticidade
                if not self._is_trigger_recent(trigger_bar, current_bar):
                    age = self._get_trigger_age(trigger_bar, current_bar)
                    logger.debug(f"FVG/{fvg['type']} rejeitado: {age} candles (máximo={self.cfg.MAX_TRIGGER_AGE_CANDLES})")
                    continue

                original_strength = 0.75 + fvg["size_pct"] * 10
                adjusted_strength = self._apply_age_penalty(original_strength, trigger_bar, current_bar)
                triggers_found.append({
                    "trigger": fvg["type"],  # "FVG" ou "IFVG"
                    "direction": fvg_dir,
                    "price": fvg["mid"],
                    "zone_top": fvg["top"],
                    "zone_bottom": fvg["bottom"],
                    "strength": adjusted_strength,
                    "bar": trigger_bar,
                    "age_candles": self._get_trigger_age(trigger_bar, current_bar),
                })

        # 3. POI
        pois = detect_poi(df)
        for poi in pois[-5:]:
            poi_dir = "bullish" if poi["zone"] == "demand" else "bearish"
            if direction_bias and poi_dir != direction_bias:
                continue
            if current_price <= poi["top"] and current_price >= poi["bottom"]:
                trigger_bar = poi.get("bar", current_bar)
                
                # Valida recenticidade
                if not self._is_trigger_recent(trigger_bar, current_bar):
                    age = self._get_trigger_age(trigger_bar, current_bar)
                    logger.debug(f"POI rejeitado: {age} candles (máximo={self.cfg.MAX_TRIGGER_AGE_CANDLES})")
                    continue

                adjusted_strength = self._apply_age_penalty(poi["strength"], trigger_bar, current_bar)
                triggers_found.append({
                    "trigger": "POI",
                    "direction": poi_dir,
                    "price": poi["price"],
                    "zone_top": poi["top"],
                    "zone_bottom": poi["bottom"],
                    "strength": adjusted_strength,
                    "bar": trigger_bar,
                    "age_candles": self._get_trigger_age(trigger_bar, current_bar),
                })

        # 4. Troca de Polaridade
        polarity = detect_polarity_change(df)
        for pc in polarity:
            if direction_bias and pc["direction"] != direction_bias:
                continue
            trigger_bar = pc.get("bar", current_bar)
            
            # Valida recenticidade
            if not self._is_trigger_recent(trigger_bar, current_bar):
                age = self._get_trigger_age(trigger_bar, current_bar)
                logger.debug(f"POLARITY_CHANGE rejeitado: {age} candles (máximo={self.cfg.MAX_TRIGGER_AGE_CANDLES})")
                continue

            adjusted_strength = self._apply_age_penalty(pc["strength"], trigger_bar, current_bar)
            triggers_found.append({
                "trigger": "POLARITY_CHANGE",
                "direction": pc["direction"],
                "price": pc["price"],
                "strength": adjusted_strength,
                "bar": trigger_bar,
                "age_candles": self._get_trigger_age(trigger_bar, current_bar),
            })

        # ── Consolidação ──────────────────────────────────────────────────────

        if not triggers_found:
            return self._empty_signal()

        # Filtra pela direção mais comum
        bull = [t for t in triggers_found if t["direction"] == "bullish"]
        bear = [t for t in triggers_found if t["direction"] == "bearish"]

        # Mínimo 1 gatilho (foi: 2)
        if len(bull) >= self.MIN_TRIGGERS:
            chosen_triggers = bull
            trade_direction = "Buy"
        elif len(bear) >= self.MIN_TRIGGERS:
            chosen_triggers = bear
            trade_direction = "Sell"
        else:
            return self._empty_signal()

        # Volume confirma
        vol_data = analyze_volume(df)
        vol_confirms = (
            (trade_direction == "Buy" and vol_data["delta_bullish"]) or
            (trade_direction == "Sell" and not vol_data["delta_bullish"])
        )
        vol_bonus = 0.08 if vol_confirms else 0.0
        vol_spike_bonus = 0.05 if vol_data["is_spike"] else 0.0

        # Score médio dos gatilhos (já com penalidade de idade aplicada)
        avg_strength = sum(t["strength"] for t in chosen_triggers) / len(chosen_triggers)
        trigger_score = min(avg_strength + vol_bonus + vol_spike_bonus, 1.0)

        # Log da recenticidade dos gatilhos selecionados
        avg_age = sum(t["age_candles"] for t in chosen_triggers) / len(chosen_triggers)
        logger.info(f"✓ Gatilhos selecionados: {len(chosen_triggers)} | Idade média: {avg_age:.1f} candles | Score: {trigger_score:.3f}")

        # ── Cálculo de Entrada, SL e TP ───────────────────────────────────────
        entry, sl, tp = self._calculate_levels(
            df=df,
            triggers=chosen_triggers,
            direction=trade_direction,
            current_price=current_price,
            atr=atr,
        )

        if entry is None:
            return self._empty_signal()

        return {
            "valid": True,
            "direction": trade_direction,
            "triggers": [t["trigger"] for t in chosen_triggers],
            "trigger_count": len(chosen_triggers),
            "trigger_score": round(trigger_score, 3),
            "entry": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "volume_confirms": vol_confirms,
            "descriptions": [f"{t['trigger']}@{t['price']:.4f}" for t in chosen_triggers],
        }

    def _calculate_levels(
        self,
        df: pd.DataFrame,
        triggers: List[Dict],
        direction: str,
        current_price: float,
        atr: float,
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Calcula entrada, stop loss e take profit."""
        entry = current_price

        if direction == "Buy":
            # SL abaixo da zona mais baixa dos triggers
            zone_bottoms = [t.get("zone_bottom", t["price"]) for t in triggers]
            sl = min(zone_bottoms) - atr * 0.5
            sl = round(sl, 4)

            # TP com RR fixo 1:3
            risk = entry - sl
            tp = entry + risk * 3.0  # 1:3 RR fixo
            tp = round(tp, 4)

        else:  # Sell
            zone_tops = [t.get("zone_top", t["price"]) for t in triggers]
            sl = max(zone_tops) + atr * 0.5
            sl = round(sl, 4)

            risk = sl - entry
            tp = entry - risk * 3.0  # 1:3 RR fixo
            tp = round(tp, 4)

        # Validação básica
        if direction == "Buy" and (sl >= entry or tp <= entry):
            return None, None, None
        if direction == "Sell" and (sl <= entry or tp >= entry):
            return None, None, None

        return entry, sl, tp

    def _empty_signal(self) -> Dict:
        return {
            "valid": False,
            "direction": None,
            "triggers": [],
            "trigger_count": 0,
            "trigger_score": 0.0,
            "entry": None,
            "stop_loss": None,
            "take_profit": None,
            "volume_confirms": False,
            "descriptions": [],
        }
