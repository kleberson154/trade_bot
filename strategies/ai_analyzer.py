"""
Análise de IA com Grok (GRATUITO)
Ordem de tentativa:
  1. GROK (cloud, ultra-rápido, modelo mais novo) → api.groq.com
  2. Fallback (análise calculada, sem IA)

Configuração em utils/config.py:
  - GROQ_API_KEY: sua chave Grok (console.groq.com - gratuita)

Se Grok não estiver disponível, o sistema continua funcionando com fallback automático.
"""

import json
import os
from abc import ABC, abstractmethod
from typing import Dict, Optional

try:
    from groq import Groq
except ImportError:
    Groq = None

from utils.logger import setup_logger

logger = setup_logger("ai_analyzer")


class AIProvider(ABC):
    """Interface abstrata para provedores de IA."""
    
    @abstractmethod
    def analyze(self, prompt: str) -> Dict:
        """Retorna análise JSON ou None se falhar."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Verifica se o provider está disponível."""
        pass


class GrokProvider(AIProvider):
    """Grok - Cloud API, ultra-rápido, modelo mais recente."""
    
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model
        self.client = None
        
        if Groq and api_key:
            try:
                self.client = Groq(api_key=api_key)
                logger.info(f"Grok client inicializado com modelo {model}")
            except Exception as e:
                logger.warning(f"Erro ao inicializar Grok client: {e}")
    
    def is_available(self) -> bool:
        """Verifica se Grok está disponível."""
        return bool(self.client and self.api_key)
    
    def analyze(self, prompt: str) -> Dict:
        """Chama Grok API."""
        if not self.is_available():
            return None
        
        try:
            message = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": self._system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=self.model,
                temperature=0.1,
                max_tokens=500,
            )
            
            raw = message.choices[0].message.content
            result = self._parse_response(raw)
            
            if result:
                logger.info(f"[OK] Grok: conf={result['confidence']:.2f}")
                return result
            else:
                logger.warning("[FAIL] Grok: erro ao parsear resposta")
                return None
                
        except Exception as e:
            logger.warning(f"[FAIL] Grok falhou: {e}")
            return None
    
    def _system_prompt(self) -> str:
        return """Você é um analista de futuros cripto experiente, especializado em Smart Money Concepts (SMC), 
Wyckoff e Price Action. Sua tarefa é analisar oportunidades de day trade e retornar uma análise estruturada em JSON.

Responda APENAS com um objeto JSON válido, sem markdown, sem texto extra. 
O JSON deve ter exatamente estes campos:
{
  "confidence": <float 0.0 a 1.0>,
  "recommendation": <"trade" | "skip">,
  "reasoning": <string curta explicando a decisão>,
  "risk_notes": <string com pontos de atenção>,
  "refined_rr": <float estimativa do RR real>,
  "entry_quality": <"excellent" | "good" | "fair" | "poor">
}"""
    
    def _parse_response(self, raw: str) -> Dict:
        """Parseia resposta JSON."""
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean.strip())
            
            return {
                "confidence": float(result.get("confidence", 0.5)),
                "recommendation": result.get("recommendation", "skip"),
                "reasoning": result.get("reasoning", ""),
                "risk_notes": result.get("risk_notes", ""),
                "refined_rr": float(result.get("refined_rr", 3.0)),
                "entry_quality": result.get("entry_quality", "fair"),
            }
        except Exception as e:
            logger.error(f"Erro ao parsear Grok: {e}")
            return None


class AIAnalyzer:
    """
    Analisador com Grok como provider principal + fallback automático.
    Tenta: Grok (cloud) → Fallback (calculado).
    
    Se Grok não estiver disponível, o sistema continua operando normalmente com fallback.
    """

    def __init__(self, groq_key: str = ""):
        self.grok = None
        
        groq_key = groq_key or os.getenv("GROQ_API_KEY", "")
        
        if groq_key:
            self.grok = GrokProvider(api_key=groq_key)
            
            if self.grok.is_available():
                logger.info("AIAnalyzer inicializado com Grok")
            else:
                logger.warning("Grok não disponível, usando fallback")
                self.grok = None
        else:
            logger.warning("GROQ_API_KEY não configurada, usando fallback")
            self.grok = None

    def analyze_opportunity(
        self,
        symbol: str,
        direction: str,
        context_data: Dict,
        trigger_data: Dict,
        market_data: Dict,
    ) -> Dict:
        """
        Tenta analisar com Grok, fallback automático se não disponível.
        """
        prompt = self._build_prompt(symbol, direction, context_data, trigger_data, market_data)
        
        # Tenta Grok
        if self.grok:
            try:
                logger.debug("Tentando Grok...")
                result = self.grok.analyze(prompt)
                
                if result:
                    logger.info(
                        f"[OK] {symbol} via Grok | "
                        f"conf={result['confidence']:.2f} | rec={result['recommendation']}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"[ERR] Grok erro: {e}")
        
        # Fallback: análise calculada (sem IA)
        logger.debug(f"[FALLBACK] {symbol} usando analise calculada")
        return self._fallback_analysis(context_data, trigger_data)
    
    def _build_prompt(
        self,
        symbol: str,
        direction: str,
        context_data: Dict,
        trigger_data: Dict,
        market_data: Dict,
    ) -> str:
        return f"""Analise esta oportunidade de trade:

SÍMBOLO: {symbol}
DIREÇÃO: {direction}

CONTEXTOS IDENTIFICADOS ({context_data.get('active_count', 0)} ativos):
{json.dumps(context_data.get('descriptions', []), ensure_ascii=False, indent=2)}

GATILHOS ({trigger_data.get('trigger_count', 0)} confirmados):
{json.dumps(trigger_data.get('descriptions', []), ensure_ascii=False, indent=2)}

DADOS DO MERCADO:
- Preço atual: {market_data.get('price', 0):.4f}
- Entrada proposta: {trigger_data.get('entry', 0):.4f}
- Stop Loss: {trigger_data.get('stop_loss', 0):.4f}
- Take Profit: {trigger_data.get('take_profit', 0):.4f}
- Volume spike: {market_data.get('volume_spike', False)}
- Volume delta bullish: {market_data.get('volume_delta_bullish', False)}
- Estrutura macro: {context_data.get('contexts', {}).get('macro_micro', {}).get('macro_structure', 'N/A')}
- Alinhamento macro/micro: {context_data.get('contexts', {}).get('macro_micro', {}).get('aligned', False)}

SCORES PRÉ-ANÁLISE:
- Score de contexto: {context_data.get('context_score', 0):.2f}
- Score de gatilhos: {trigger_data.get('trigger_score', 0):.2f}

Avalie a qualidade desta entrada, o alinhamento das confluências e a relação risco/retorno.
Considere se há riscos escondidos ou se a entrada é prematura."""



    def _fallback_analysis(self, context_data: Dict, trigger_data: Dict) -> Dict:
        """Análise de fallback sem IA baseada nos scores calculados."""
        ctx_score = context_data.get("context_score", 0)
        trig_score = trigger_data.get("trigger_score", 0)
        avg = (ctx_score + trig_score) / 2

        return {
            "confidence": round(avg, 3),
            "recommendation": "trade" if avg >= 0.65 else "skip",
            "reasoning": "Análise de fallback (IA indisponível) baseada em scores calculados",
            "risk_notes": "IA indisponível - validação reduzida",
            "refined_rr": 3.0,
            "entry_quality": "fair" if avg >= 0.65 else "poor",
        }
