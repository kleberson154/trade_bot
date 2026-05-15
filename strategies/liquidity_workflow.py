"""
Fluxo de Trabalho de Liquidez - 5 Passos
Baseado no Manual de Liquidez: Como Pensar e Operar Como o Dinheiro Inteligente

Passos:
1. Identificar Liquidez: topos/fundos iguais, consolidações
2. Esperar Sweep: captura de stops (FVG ou análise de POI)
3. Confirmar CHoCH/BOS: mudança de estrutura
4. Confirmar Fluxo: volume alinhado
5. Entrar no Pullback: Order Block ou FVG (NUNCA no impulso!)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from utils.logger import setup_logger


logger = setup_logger("liquidity_workflow")
DEFAULT_SWEEP_EPS = 0.001
# Limiar de penetração única para aceitar BOS/CHOCH (0.001 = 0.1%)
CHOCH_SINGLE_PENETRATION = 0.001
# Limiar mínimo de volume_ratio para aceitar fluxo (conservador)
VOLUME_RATIO_THRESHOLD = 0.90


@dataclass
class LiquidityState:
    """Estado da sequência de liquidez"""
    step: int  # 0-5 (0=esperando liquidez, 1-5 = etapas do fluxo)
    liquidity_level: float = None  # Nível onde liquidez foi encontrada
    has_equal_highs: bool = False  # Topos iguais detectados
    has_equal_lows: bool = False  # Fundos iguais detectados
    has_consolidation: bool = False  # Consolidação detectada
    sweep_confirmed: bool = False  # Sweep foi realizado
    structure_change_confirmed: bool = False  # CHoCH/BOS confirmado
    volume_confirmed: bool = False  # Volume alinhado
    pullback_detected: bool = False  # Pullback detectado (pronto para entrada)
    entry_ready: bool = False  # Pronto para executar trade


class LiquidityWorkflow:
    """Valida o fluxo de trabalho completo de 5 passos"""
    
    def __init__(self):
        self.state = LiquidityState(step=0)
        self.lookback = 50
        
    def reset_workflow(self):
        """Reseta o workflow após conclusão de trade"""
        self.state = LiquidityState(step=0)
    
    def step_1_identify_liquidity(self, df: pd.DataFrame, tolerance_pct: float = 0.5) -> Dict:
        """
        PASSO 1: Identificar liquidez óbvia
        - Topos iguais (Equal Highs)
        - Fundos iguais (Equal Lows)
        - Consolidações (movimentação lateral)
        
        Args:
            df: DataFrame com OHLCV
            tolerance_pct: Tolerância em % para considerar "igual"
        
        Returns:
            Dict com análise de liquidez
        """
        result = {
            'liquidity_found': False,
            'equal_highs': [],
            'equal_lows': [],
            'consolidation': None,
            'level': None,
            'type': None,
        }
        
        if len(df) < self.lookback:
            return result
        
        recent = df.iloc[-self.lookback:]
        highs = recent['high'].values
        lows = recent['low'].values
        closes = recent['close'].values
        
        # Detectar topos iguais (Equal Highs)
        tolerance = np.mean(highs) * (tolerance_pct / 100)
        for i in range(len(highs) - 2):
            for j in range(i + 2, len(highs)):
                if abs(highs[i] - highs[j]) <= tolerance:
                    result['equal_highs'].append((i, highs[i], j, highs[j]))
        
        # Detectar fundos iguais (Equal Lows)
        for i in range(len(lows) - 2):
            for j in range(i + 2, len(lows)):
                if abs(lows[i] - lows[j]) <= tolerance:
                    result['equal_lows'].append((i, lows[i], j, lows[j]))
        
        # Detectar consolidações (range trading)
        high_range = np.max(recent['high'].iloc[-20:]) - np.min(recent['low'].iloc[-20:])
        recent_range = np.max(recent['high'].iloc[-5:]) - np.min(recent['low'].iloc[-5:])
        
        if recent_range < high_range * 0.3:  # Consolidação = 30% do range anterior
            result['consolidation'] = {
                'high': np.max(recent['high'].iloc[-5:]),
                'low': np.min(recent['low'].iloc[-5:]),
                'range': recent_range,
            }
        
        # Determinar nivel de liquidez
        if result['equal_highs']:
            result['level'] = result['equal_highs'][-1][1]  # Último topo igual
            result['type'] = 'SUPPLY'
            result['liquidity_found'] = True
        elif result['equal_lows']:
            result['level'] = result['equal_lows'][-1][1]  # Último fundo igual
            result['type'] = 'DEMAND'
            result['liquidity_found'] = True
        elif result['consolidation']:
            result['level'] = (result['consolidation']['high'] + result['consolidation']['low']) / 2
            result['type'] = 'CONSOLIDATION'
            result['liquidity_found'] = True
        
        if result['liquidity_found']:
            self.state.step = 1
            self.state.liquidity_level = result['level']
            self.state.has_equal_highs = len(result['equal_highs']) > 0
            self.state.has_equal_lows = len(result['equal_lows']) > 0
            self.state.has_consolidation = result['consolidation'] is not None
            logger.info(
                "Passo 1 OK | tipo=%s nivel=%.4f equal_highs=%d equal_lows=%d consolidacao=%s",
                result['type'],
                result['level'],
                len(result['equal_highs']),
                len(result['equal_lows']),
                bool(result['consolidation']),
            )
        else:
            logger.info("Passo 1 falhou | sem liquidez clara no lookback=%d", self.lookback)
        
        return result
    
    def step_2_wait_for_sweep(self, df: pd.DataFrame, liquidity_level: float, direction: str) -> Dict:
        """
        PASSO 2: Esperar pelo sweep (captura de stops)
        - O mercado captura liquidez (stops)
        - Cria um FVG ou Order Block
        - Spike rápido penetrando a região de liquidez
        
        Args:
            df: DataFrame com OHLCV
            liquidity_level: Nível de liquidez identificado
            direction: 'up' (bullish) ou 'down' (bearish)
        
        Returns:
            Dict com análise do sweep
        """
        result = {
            'sweep_detected': False,
            'sweep_type': None,  # 'fvg' ou 'order_block'
            'sweep_level': None,
            'penetration_depth': None,
        }
        
        sweep_window = 8
        if len(df) < sweep_window:
            return result

        recent = df.iloc[-sweep_window:]
        
        if direction == 'up':
            # Esperamos uma penetração rápida da liquidez anterior
            # Usa janela maior e tolerância pequena para aceitar variações micro
            min_low = np.min(recent['low'])
            eps = max(1e-8, liquidity_level * DEFAULT_SWEEP_EPS)  # default tolerance
            if min_low < liquidity_level - eps or min_low <= liquidity_level + eps:
                # Penetrou a liquidez (capturou stops) ou micro-penetração aceitável
                result['sweep_detected'] = True
                result['penetration_depth'] = abs(min_low - liquidity_level)
                result['sweep_level'] = min_low
                result['sweep_type'] = 'order_block'
        
        elif direction == 'down':
            # Esperamos uma penetração rápida da liquidez anterior
            max_high = np.max(recent['high'])
            eps = max(1e-8, liquidity_level * 0.0005)
            if max_high > liquidity_level + eps or max_high >= liquidity_level - eps:
                result['sweep_detected'] = True
                result['penetration_depth'] = abs(max_high - liquidity_level)
                result['sweep_level'] = max_high
                result['sweep_type'] = 'order_block'
        
        if result['sweep_detected']:
            self.state.step = 2
            self.state.sweep_confirmed = True
            logger.info(
                "Passo 2 OK | direction=%s tipo=%s nivel=%.4f profundidade=%.4f",
                direction,
                result['sweep_type'],
                result['sweep_level'],
                result['penetration_depth'],
            )
        else:
            # Diagnóstico: registrar extremos recentes para entender por que não houve sweep
            logger.info(
                "Passo 2 falhou | direction=%s nivel_liquidez=%.4f recent_min_low=%.4f recent_max_high=%.4f",
                direction,
                liquidity_level,
                np.min(recent['low']),
                np.max(recent['high']),
            )
        
        return result
    
    def step_3_confirm_structure_change(self, df: pd.DataFrame, direction: str) -> Dict:
        """
        PASSO 3: Confirmar CHoCH ou BOS (mudança de estrutura)
        - CHoCH = Change of Character (mudança de caráter via swing points)
        - BOS = Break of Structure (rompimento de nível anterior)
        - Usa swing points (picos e vales locais) ao invés de apenas última vela
        
        Args:
            df: DataFrame com OHLCV
            direction: 'up' (bullish) ou 'down' (bearish)
        
        Returns:
            Dict com análise de estrutura
        """
        result = {
            'structure_change': False,
            'type': None,  # 'choch_bullish', 'bos_bullish', 'choch_bearish', 'bos_bearish'
            'confirmation_candle': None,
        }
        
        if len(df) < 20:
            return result
        
        # Detecta swing highs e lows (picos e vales locais)
        # Um swing high é um candle com high maior que 2 candles antes e depois
        # Um swing low é um candle com low menor que 2 candles antes e depois
        lookback = min(20, len(df) - 1)
        
        def find_swings(prices, window=1):
            """Encontra swing points (máximos e mínimos locais)"""
            swings = {'highs': [], 'lows': []}
            for i in range(window, len(prices) - window):
                # Swing high local - relaxado: apenas comparar com vizinhos diretos
                if (i == 0 or prices[i] > prices[i-1]) and \
                   (i == len(prices) - 1 or prices[i] > prices[i+1]):
                    is_high = True
                    for j in range(max(0, i-2), min(len(prices), i+3)):
                        if j != i and prices[j] >= prices[i]:
                            is_high = False
                            break
                    if is_high:
                        swings['highs'].append((i, prices[i]))
                
                # Swing low local - relaxado: apenas comparar com vizinhos diretos
                if (i == 0 or prices[i] < prices[i-1]) and \
                   (i == len(prices) - 1 or prices[i] < prices[i+1]):
                    is_low = True
                    for j in range(max(0, i-2), min(len(prices), i+3)):
                        if j != i and prices[j] <= prices[i]:
                            is_low = False
                            break
                    if is_low:
                        swings['lows'].append((i, prices[i]))
            return swings
        
        if direction == 'up':
            # CHoCH Bullish: novo swing low ACIMA do swing low anterior (estrutura de alta confirmada)
            # BOS Bullish: preço rompeu para cima da resistência anterior
            last_candle = df.iloc[-1]
            
            # Detecta swing points nos últimos candles
            recent_lows = df.iloc[-lookback:]['low'].values
            recent_highs = df.iloc[-lookback:]['high'].values
            
            swings_low = find_swings(recent_lows, window=2)
            swings_high = find_swings(recent_highs, window=2)
            
            # CHoCH bullish: novo swing low MAIS ALTO que o anterior
            if len(swings_low['lows']) >= 2:
                latest_swing_low = swings_low['lows'][-1][1]
                prev_swing_low = swings_low['lows'][-2][1]
                if latest_swing_low > prev_swing_low:
                    result['structure_change'] = True
                    result['type'] = 'choch_bullish'
            
            # BOS bullish: rompimento para cima do último swing high
            elif len(swings_high['highs']) >= 1:
                prev_high = swings_high['highs'][-1][1]
                if last_candle['close'] > prev_high:
                    result['structure_change'] = True
                    result['type'] = 'bos_bullish'
            
            if result['structure_change']:
                result['confirmation_candle'] = {
                    'open': last_candle['open'],
                    'close': last_candle['close'],
                    'high': last_candle['high'],
                    'low': last_candle['low'],
                }
            # Fallback permissivo BOS: aceitar 2 fechamentos consecutivos acima do prev_high
            if not result['structure_change']:
                # determinar prev_high de referência
                try:
                    if len(swings_high['highs']) >= 1:
                        prev_high = swings_high['highs'][-1][1]
                    else:
                        prev_high = np.max(df.iloc[-21:-1]['high'])
                except Exception:
                    prev_high = np.max(df['high'].iloc[-21:-1]) if len(df) >= 22 else np.max(df['high'])

                try:
                    close1 = df.iloc[-1]['close']
                    close2 = df.iloc[-2]['close']
                    # dois fechamentos consecutivos acima do prev_high
                    if close1 > prev_high and close2 > prev_high:
                        result['structure_change'] = True
                        result['type'] = 'bos_bullish'
                        result['confirmation_candle'] = {
                            'open': last_candle['open'],
                            'close': last_candle['close'],
                            'high': last_candle['high'],
                            'low': last_candle['low'],
                        }
                    else:
                        # aceitar single close contendo penetração significativa (>0.15%)
                        if close1 > prev_high and (close1 - prev_high) / prev_high > CHOCH_SINGLE_PENETRATION:
                            result['structure_change'] = True
                            result['type'] = 'bos_bullish'
                            result['confirmation_candle'] = {
                                'open': last_candle['open'],
                                'close': last_candle['close'],
                                'high': last_candle['high'],
                                'low': last_candle['low'],
                            }
                except Exception:
                    pass
        
        elif direction == 'down':
            # CHoCH Bearish: novo swing high ABAIXO do swing high anterior (estrutura de baixa confirmada)
            # BOS Bearish: preço rompeu para baixo do suporte anterior
            last_candle = df.iloc[-1]
            
            # Detecta swing points nos últimos candles
            recent_lows = df.iloc[-lookback:]['low'].values
            recent_highs = df.iloc[-lookback:]['high'].values
            
            swings_low = find_swings(recent_lows, window=2)
            swings_high = find_swings(recent_highs, window=2)
            
            # CHoCH bearish: novo swing high MAIS BAIXO que o anterior
            if len(swings_high['highs']) >= 2:
                latest_swing_high = swings_high['highs'][-1][1]
                prev_swing_high = swings_high['highs'][-2][1]
                if latest_swing_high < prev_swing_high:
                    result['structure_change'] = True
                    result['type'] = 'choch_bearish'
            
            # BOS bearish: rompimento para baixo do último swing low
            elif len(swings_low['lows']) >= 1:
                prev_low = swings_low['lows'][-1][1]
                if last_candle['close'] < prev_low:
                    result['structure_change'] = True
                    result['type'] = 'bos_bearish'
            
            if result['structure_change']:
                result['confirmation_candle'] = {
                    'open': last_candle['open'],
                    'close': last_candle['close'],
                    'high': last_candle['high'],
                    'low': last_candle['low'],
                }
            # Fallback permissivo BOS bearish: 2 fechamentos consecutivos abaixo do prev_low
            if not result['structure_change']:
                try:
                    if len(swings_low['lows']) >= 1:
                        prev_low = swings_low['lows'][-1][1]
                    else:
                        prev_low = np.min(df.iloc[-21:-1]['low'])
                except Exception:
                    prev_low = np.min(df['low'].iloc[-21:-1]) if len(df) >= 22 else np.min(df['low'])

                try:
                    close1 = df.iloc[-1]['close']
                    close2 = df.iloc[-2]['close']
                    if close1 < prev_low and close2 < prev_low:
                        result['structure_change'] = True
                        result['type'] = 'bos_bearish'
                        result['confirmation_candle'] = {
                            'open': last_candle['open'],
                            'close': last_candle['close'],
                            'high': last_candle['high'],
                            'low': last_candle['low'],
                        }
                    else:
                        if close1 < prev_low and (prev_low - close1) / prev_low > CHOCH_SINGLE_PENETRATION:
                            result['structure_change'] = True
                            result['type'] = 'bos_bearish'
                            result['confirmation_candle'] = {
                                'open': last_candle['open'],
                                'close': last_candle['close'],
                                'high': last_candle['high'],
                                'low': last_candle['low'],
                            }
                except Exception:
                    pass
        
        if result['structure_change']:
            self.state.step = 3
            self.state.structure_change_confirmed = True
            logger.info(
                "Passo 3 OK | direction=%s tipo=%s candle_confirmacao=%s",
                direction,
                result['type'],
                result['confirmation_candle'],
            )
        else:
            # Diagnóstico: informar quantos swings foram detectados e último candle
            swings_low_count = len(swings_low['lows']) if 'swings_low' in locals() else 0
            swings_high_count = len(swings_high['highs']) if 'swings_high' in locals() else 0
            logger.info(
                "Passo 3 falhou | direction=%s sem CHoCH/BOS confirmado | swings_low=%d swings_high=%d last_candle=%s",
                direction,
                swings_low_count,
                swings_high_count,
                last_candle.to_dict() if 'last_candle' in locals() else {},
            )
        
        return result
    
    def step_4_confirm_flow(self, df: pd.DataFrame, direction: str, volume_sma_period: int = 20) -> Dict:
        """
        PASSO 4: Confirmar fluxo (volume alinhado)
        - Volume na direção do movimento
        - Impulso forte sem hesitação
        - Volume > média móvel de volume
        
        Args:
            df: DataFrame com OHLCV
            direction: 'up' (bullish) ou 'down' (bearish)
            volume_sma_period: Período para SMA de volume
        
        Returns:
            Dict com análise de fluxo
        """
        result = {
            'flow_confirmed': False,
            'volume_ratio': None,
            'avg_volume': None,
            'recent_volume': None,
            'volume_strength': None,
        }
        
        if len(df) < volume_sma_period + 5:
            return result
        
        if 'volume' not in df.columns:
            # Se não houver volume, considerar confirmado
            result['flow_confirmed'] = True
            result['volume_strength'] = 'unknown'
            return result
        
        recent = df.iloc[-5:]
        avg_vol = df.iloc[-volume_sma_period:-5]['volume'].mean()
        recent_vol = recent['volume'].mean()
        
        result['avg_volume'] = avg_vol
        result['recent_volume'] = recent_vol
        result['volume_ratio'] = recent_vol / avg_vol if avg_vol > 0 else 1.0
        
        if direction == 'up':
            # Volume deve estar crescendo + preço subindo
            has_up_movement = recent.iloc[-1]['close'] > recent.iloc[0]['open']
            has_volume = result['volume_ratio'] >= VOLUME_RATIO_THRESHOLD  # Acima da média (conservador)
            
            if has_up_movement and has_volume:
                result['flow_confirmed'] = True
                result['volume_strength'] = 'strong'
            elif has_up_movement:
                result['flow_confirmed'] = True
                result['volume_strength'] = 'moderate'
        
        elif direction == 'down':
            # Volume deve estar crescendo + preço caindo
            has_down_movement = recent.iloc[-1]['close'] < recent.iloc[0]['open']
            has_volume = result['volume_ratio'] >= VOLUME_RATIO_THRESHOLD  # Acima da média (conservador)
            
            if has_down_movement and has_volume:
                result['flow_confirmed'] = True
                result['volume_strength'] = 'strong'
            elif has_down_movement:
                result['flow_confirmed'] = True
                result['volume_strength'] = 'moderate'
        
        if result['flow_confirmed']:
            self.state.step = 4
            self.state.volume_confirmed = True
            logger.info(
                "Passo 4 OK | direction=%s volume_ratio=%.2f strength=%s",
                direction,
                result['volume_ratio'] if result['volume_ratio'] is not None else -1.0,
                result['volume_strength'],
            )
        else:
            # Diagnóstico: informar média e volume recente para calibrar thresholds
            logger.info(
                "Passo 4 falhou | direction=%s volume_ratio=%s avg_volume=%s recent_volume=%s strength=%s",
                direction,
                "n/a" if result['volume_ratio'] is None else f"{result['volume_ratio']:.2f}",
                (f"{result['avg_volume']:.2f}" if result['avg_volume'] is not None else "n/a"),
                (f"{result['recent_volume']:.2f}" if result['recent_volume'] is not None else "n/a"),
                result['volume_strength'],
            )
        
        return result
    
    def step_5_entry_pullback(self, df: pd.DataFrame, direction: str, sweep_level: float) -> Dict:
        """
        PASSO 5: Entrar no pullback (Order Block ou FVG)
        - NUNCA entrar no impulso!
        - Esperar reação/pullback
        - Entrar no suporte (OB) ou nos níveis de suporte/resistência
        
        Args:
            df: DataFrame com OHLCV
            direction: 'up' (bullish) ou 'down' (bearish)
            sweep_level: Nível do sweep anterior
        
        Returns:
            Dict com análise de entrada
        """
        result = {
            'entry_ready': False,
            'entry_reason': None,
            'entry_level': None,
            'pullback_depth': None,
            'is_in_impulse': False,
        }
        
        if len(df) < 3:
            return result
        
        last_close = df.iloc[-1]['close']
        
        if direction == 'up':
            # Bullish: Procuramos pullback (reação para baixo)
            # Entrada será no suporte (Order Block)
            
            # Verificar se estamos em impulso (cada candle mais alto = ainda em impulso)
            is_impulse = (df.iloc[-1]['high'] > df.iloc[-2]['high'] and 
                         df.iloc[-1]['close'] > df.iloc[-2]['close'])
            
            if is_impulse:
                result['is_in_impulse'] = True
                result['entry_reason'] = 'Aguardando pullback (ainda em impulso)'
                return result
            
            # Detectar pullback (lower low ou close abaixo do anterior)
            is_pullback = (df.iloc[-1]['low'] < df.iloc[-2]['low'] or 
                          df.iloc[-1]['close'] < df.iloc[-2]['close'])
            
            if is_pullback:
                pullback_level = df.iloc[-1]['low']
                pullback_depth = abs(df.iloc[-2]['high'] - pullback_level)
                
                result['entry_ready'] = True
                result['entry_reason'] = 'Pullback confirmado'
                result['entry_level'] = pullback_level
                result['pullback_depth'] = pullback_depth
        
        elif direction == 'down':
            # Bearish: Procuramos pullback (reação para cima)
            # Entrada será na resistência (Order Block)
            
            # Verificar se estamos em impulso (cada candle mais baixo = ainda em impulso)
            is_impulse = (df.iloc[-1]['low'] < df.iloc[-2]['low'] and 
                         df.iloc[-1]['close'] < df.iloc[-2]['close'])
            
            if is_impulse:
                result['is_in_impulse'] = True
                result['entry_reason'] = 'Aguardando pullback (ainda em impulso)'
                return result
            
            # Detectar pullback (higher high ou close acima do anterior)
            is_pullback = (df.iloc[-1]['high'] > df.iloc[-2]['high'] or 
                          df.iloc[-1]['close'] > df.iloc[-2]['close'])
            
            if is_pullback:
                pullback_level = df.iloc[-1]['high']
                pullback_depth = abs(pullback_level - df.iloc[-2]['low'])
                
                result['entry_ready'] = True
                result['entry_reason'] = 'Pullback confirmado'
                result['entry_level'] = pullback_level
                result['pullback_depth'] = pullback_depth
        
        if result['entry_ready']:
            self.state.step = 5
            self.state.pullback_detected = True
            self.state.entry_ready = True
            logger.info(
                "Passo 5 OK | direction=%s entry_level=%.4f pullback_depth=%.4f",
                direction,
                result['entry_level'],
                result['pullback_depth'],
            )
        else:
            logger.info(
                "Passo 5 falhou | direction=%s motivo=%s",
                direction,
                result['entry_reason'],
            )
        
        return result
    
    def validate_complete_workflow(self, df: pd.DataFrame, 
                                  direction: str = 'up',
                                  liquidity_level: Optional[float] = None,
                                  sweep_level: Optional[float] = None) -> Dict:
        """
        Valida o fluxo completo de 5 passos
        Retorna True apenas se todos os 5 passos foram validados
        
        Args:
            df: DataFrame com OHLCV
            direction: 'up' ou 'down'
            liquidity_level: Nível de liquidez (optional)
            sweep_level: Nível do sweep (optional)
        
        Returns:
            Dict com resultado da validação completa
        """
        
        # Passo 1: Identificar liquidez
        step1 = self.step_1_identify_liquidity(df)
        if not step1['liquidity_found']:
            logger.info("Workflow rejeitado na etapa 1 | reason=Liquidez nao identificada")
            return {
                'workflow_valid': False,
                'current_step': 0,
                'reason': 'Liquidez não identificada',
                'details': step1,
            }
        
        # Usar nível fornecido ou do step 1
        liq_level = liquidity_level or step1['level']
        
        # Passo 2: Esperar sweep
        step2 = self.step_2_wait_for_sweep(df, liq_level, direction)
        if not step2['sweep_detected']:
            logger.info("Workflow rejeitado na etapa 2 | reason=Sweep nao detectado")
            return {
                'workflow_valid': False,
                'current_step': 1,
                'reason': 'Sweep não detectado',
                'details': step1,
            }
        
        # Usar nível do sweep
        sweep_lv = sweep_level or step2['sweep_level']
        
        # Passo 3: Confirmar mudança de estrutura
        step3 = self.step_3_confirm_structure_change(df, direction)
        if not step3['structure_change']:
            logger.info("Workflow rejeitado na etapa 3 | reason=CHoCH/BOS nao confirmado")
            return {
                'workflow_valid': False,
                'current_step': 2,
                'reason': 'Mudança de estrutura (CHoCH/BOS) não confirmada',
                'details': step1,
            }
        
        # Passo 4: Confirmar fluxo
        step4 = self.step_4_confirm_flow(df, direction)
        if not step4['flow_confirmed']:
            logger.info("Workflow rejeitado na etapa 4 | reason=Fluxo nao confirmado")
            return {
                'workflow_valid': False,
                'current_step': 3,
                'reason': 'Fluxo não confirmado (volume fraco)',
                'details': step1,
            }
        
        # Passo 5: Entrada no pullback
        step5 = self.step_5_entry_pullback(df, direction, sweep_lv)
        if not step5['entry_ready']:
            logger.info("Workflow rejeitado na etapa 5 | reason=%s", step5['entry_reason'])
            return {
                'workflow_valid': False,
                'current_step': 4,
                'reason': step5['entry_reason'],
                'details': step1,
            }
        
        # Todos os 5 passos validados!
        return {
            'workflow_valid': True,
            'current_step': 5,
            'reason': 'Fluxo de liquidez completo validado!',
            'step_1_liquidity': step1,
            'step_2_sweep': step2,
            'step_3_structure': step3,
            'step_4_flow': step4,
            'step_5_entry': step5,
            'entry_level': step5['entry_level'],
            'entry_ready': True,
        }


if __name__ == '__main__':
    # Teste básico
    workflow = LiquidityWorkflow()
    print("LiquidityWorkflow iniciado")
    print(f"  Estado inicial: Passo {workflow.state.step}")
