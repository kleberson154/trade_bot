"""
Indicadores Macro do Bitcoin
- BTC Dominance: Analisa % de mercado crypto do Bitcoin
- BTC Trend: Valida tendência do BTC vs trade
"""

import pandas as pd
from typing import Dict, Optional, Tuple
import requests


class BTCDominanceAnalyzer:
    """
    Analisa dominância do Bitcoin no mercado crypto.
    
    Faixas de Dominância:
    - > 65%: Mercado muito BTC (altcoins débeis)     ⚠️ CAUTELA (-20%)
    - 55-65%: Saudável, altcoins têm espaço          ✓ SEGURO (+5%)
    - 45-55%: Mercado equilibrado                     ✓ ÓTIMO (+15%)
    - < 45%: Altcoins dominam (risco alto)          ❌ RISCO (-15%)
    
    Bonus: +15% em zona ótima (45-55%)
    Penalty: -20% em zona de risco (>65% ou <45%)
    """
    
    @staticmethod
    def get_btc_dominance() -> Optional[float]:
        """
        Busca dominância atual do BTC.
        Tenta usar CoinGecko API (gratuita).
        
        Returns: float (0-100) ou None se falhar
        """
        try:
            # CoinGecko API - gratuita, sem autenticação
            url = "https://api.coingecko.com/api/v3/global"
            response = requests.get(url, timeout=5)
            data = response.json()
            
            btc_dom = data.get("data", {}).get("btc_dominance", None)
            return btc_dom if btc_dom is not None else None
            
        except Exception as e:
            # Fallback: retornar None se não conseguir buscar
            return None
    
    @staticmethod
    def evaluate_dominance(dominance: Optional[float]) -> Dict:
        """
        Avalia nível de dominância e retorna bonus/penalty.
        
        Args:
            dominance: Valor de 0-100 (%)
        
        Returns:
            {
                "dominance": float,
                "level": str ("MUITO_ALTO", "ALTO", "ÓTIMO", "BAIXO", "MUITO_BAIXO"),
                "bonus": float (+0.15 a -0.20),
                "description": str,
                "recommendation": str,
                "valid": bool (False se sem dados)
            }
        """
        
        result = {
            "dominance": dominance,
            "level": "DESCONHECIDO",
            "bonus": 0.0,
            "description": "",
            "recommendation": "",
            "valid": False
        }
        
        if dominance is None:
            result["description"] = "Dominância indisponível (sem conexão)"
            result["recommendation"] = "Usar trading normal"
            return result
        
        result["valid"] = True
        result["dominance"] = round(dominance, 2)
        
        # Classificar faixa
        if dominance > 65:
            result["level"] = "MUITO_ALTO"
            result["bonus"] = -0.20  # -20% confiança
            result["description"] = f"Dominância MUITO ALTA ({dominance:.1f}%) - Mercado muito BTC"
            result["recommendation"] = "CAUTELA: Altcoins muito fracas, risco sistêmico alto"
        
        elif dominance >= 55:
            result["level"] = "ALTO"
            result["bonus"] = 0.05  # +5% confiança
            result["description"] = f"Dominância ALTA ({dominance:.1f}%) - Zona segura"
            result["recommendation"] = "OK: Altcoins têm espaço moderado"
        
        elif dominance >= 45:
            result["level"] = "ÓTIMO"
            result["bonus"] = 0.15  # +15% confiança
            result["description"] = f"Dominância ÓTIMA ({dominance:.1f}%) - Mercado equilibrado"
            result["recommendation"] = "IDEAL: Melhor zona para operar altcoins"
        
        elif dominance >= 35:
            result["level"] = "BAIXO"
            result["bonus"] = -0.10  # -10% confiança
            result["description"] = f"Dominância BAIXA ({dominance:.1f}%) - Altcoins dominam"
            result["recommendation"] = "CAUTION: Altcoins em risco, possível correção"
        
        else:
            result["level"] = "MUITO_BAIXO"
            result["bonus"] = -0.20  # -20% confiança
            result["description"] = f"Dominância MUITO BAIXA ({dominance:.1f}%) - Risco sistêmico"
            result["recommendation"] = "EVITAR: Risco muito alto, esperar melhora"
        
        return result


class BTCTrendValidator:
    """
    Valida tendência do BTC e alinha com direção da trade.
    
    Conceito:
    - COMPRA em altcoin: Só entra se BTC também está subindo
    - VENDA em altcoin: Só entra se BTC também está descendo
    - Evita: Comprar alt enquanto BTC cai (risco de drawdown)
    
    Bonus: +10% se aligned
    Penalty: -15% se misaligned
    """
    
    @staticmethod
    def get_btc_trend(df_btc: pd.DataFrame, timeframe: str = "1h") -> str:
        """
        Determina tendência do BTC.
        
        Args:
            df_btc: DataFrame com OHLCV do BTC
            timeframe: Timeframe para análise (apenas para log)
        
        Returns: "uptrend", "downtrend" ou "lateral"
        """
        
        if len(df_btc) < 50:
            return "unknown"
        
        # Usar últimas 50 velas para análise
        recent = df_btc.iloc[-50:].copy()
        
        # Calcular EMAs simples
        close = recent["close"]
        ema_20 = close.ewm(span=20, adjust=False).mean()
        ema_50 = close.ewm(span=50, adjust=False).mean()
        
        # Determinar tendência
        current_ema20 = ema_20.iloc[-1]
        current_ema50 = ema_50.iloc[-1]
        
        if current_ema20 > current_ema50 * 1.005:  # 0.5% margin
            return "uptrend"
        elif current_ema20 < current_ema50 * 0.995:
            return "downtrend"
        else:
            return "lateral"
    
    @staticmethod
    def validate_trade_alignment(
        btc_trend: str,
        trade_direction: str  # "buy" ou "sell"
    ) -> Dict:
        """
        Valida se trade está alinhada com tendência do BTC.
        
        Args:
            btc_trend: "uptrend", "downtrend", "lateral" ou "unknown"
            trade_direction: "buy" ou "sell"
        
        Returns:
            {
                "is_aligned": bool,
                "bonus": float,
                "reason": str,
                "btc_trend": str,
                "confidence": float
            }
        """
        
        result = {
            "is_aligned": False,
            "bonus": 0.0,
            "reason": "",
            "btc_trend": btc_trend,
            "confidence": 0.0
        }
        
        if btc_trend == "unknown":
            result["reason"] = "Tendência BTC desconhecida"
            result["bonus"] = 0.0
            result["confidence"] = 0.5
            return result
        
        # Validar alinhamento
        if trade_direction == "buy":
            if btc_trend == "uptrend":
                result["is_aligned"] = True
                result["bonus"] = 0.10  # +10%
                result["reason"] = "BTC em uptrend confirma compra"
                result["confidence"] = 0.95
            elif btc_trend == "lateral":
                result["is_aligned"] = True
                result["bonus"] = 0.05  # +5%
                result["reason"] = "BTC lateral permite compra"
                result["confidence"] = 0.70
            else:  # downtrend
                result["is_aligned"] = False
                result["bonus"] = -0.15  # -15%
                result["reason"] = "BTC em downtrend desaconselha compra"
                result["confidence"] = 0.20
        
        elif trade_direction == "sell":
            if btc_trend == "downtrend":
                result["is_aligned"] = True
                result["bonus"] = 0.10  # +10%
                result["reason"] = "BTC em downtrend confirma venda"
                result["confidence"] = 0.95
            elif btc_trend == "lateral":
                result["is_aligned"] = True
                result["bonus"] = 0.05  # +5%
                result["reason"] = "BTC lateral permite venda"
                result["confidence"] = 0.70
            else:  # uptrend
                result["is_aligned"] = False
                result["bonus"] = -0.15  # -15%
                result["reason"] = "BTC em uptrend desaconselha venda"
                result["confidence"] = 0.20
        
        return result
    
    @staticmethod
    def btc_macro_health(btc_trend: str, dominance: Optional[float]) -> Dict:
        """
        Avalia saúde geral do macro BTC + mercado.
        
        Returns:
            {
                "health": str ("healthy", "caution", "danger"),
                "score": float (0-1),
                "components": {...}
            }
        """
        
        components = {
            "trend": btc_trend,
            "dominance_level": None,
            "trend_score": 0.0,
            "dominance_score": 0.0
        }
        
        # Score da tendência
        if btc_trend == "uptrend":
            components["trend_score"] = 0.8
        elif btc_trend == "lateral":
            components["trend_score"] = 0.5
        elif btc_trend == "downtrend":
            components["trend_score"] = 0.2
        else:
            components["trend_score"] = 0.3
        
        # Score da dominância
        if dominance is None:
            components["dominance_score"] = 0.5  # Neutro
        elif dominance > 65:
            components["dominance_score"] = 0.3
        elif dominance >= 55:
            components["dominance_score"] = 0.6
        elif dominance >= 45:
            components["dominance_score"] = 0.9  # Ótimo
        elif dominance >= 35:
            components["dominance_score"] = 0.5
        else:
            components["dominance_score"] = 0.2
        
        # Score final
        score = (components["trend_score"] + components["dominance_score"]) / 2
        
        if score >= 0.7:
            health = "healthy"
        elif score >= 0.4:
            health = "caution"
        else:
            health = "danger"
        
        return {
            "health": health,
            "score": round(score, 2),
            "components": components
        }


class BTCMacroAnalyzer:
    """Orquestrador de análise BTC macro."""
    
    @staticmethod
    def analyze_btc_macro(
        df_btc: pd.DataFrame,
        trade_direction: str
    ) -> Dict:
        """
        Análise completa: Dominância + Trend do BTC.
        
        Returns:
            {
                "dominance": {...},
                "trend": {...},
                "alignment": {...},
                "health": {...},
                "total_bonus": float (-0.35 a +0.25),
                "recommendation": str
            }
        """
        
        # 1. Buscar dominância
        dominance_value = BTCDominanceAnalyzer.get_btc_dominance()
        dominance_eval = BTCDominanceAnalyzer.evaluate_dominance(dominance_value)
        
        # 2. Analisar trend
        btc_trend = BTCTrendValidator.get_btc_trend(df_btc)
        alignment = BTCTrendValidator.validate_trade_alignment(btc_trend, trade_direction)
        
        # 3. Saúde macro
        health = BTCTrendValidator.btc_macro_health(btc_trend, dominance_value)
        
        # 4. Cálculo de bonus total
        total_bonus = dominance_eval["bonus"] + alignment["bonus"]
        
        # 5. Recomendação
        if total_bonus >= 0.10:
            recommendation = f"EXCELENTE: Condições ideais ({total_bonus:+.1%})"
        elif total_bonus >= 0.0:
            recommendation = f"BOM: Condições favoráveis ({total_bonus:+.1%})"
        elif total_bonus >= -0.10:
            recommendation = f"CAUTELA: Condições moderadas ({total_bonus:+.1%})"
        else:
            recommendation = f"RISCO: Condições desfavoráveis ({total_bonus:+.1%})"
        
        return {
            "dominance": dominance_eval,
            "trend": {
                "btc_trend": btc_trend,
                "trend_description": f"BTC em {btc_trend}"
            },
            "alignment": alignment,
            "health": health,
            "total_bonus": round(total_bonus, 3),
            "recommendation": recommendation
        }
