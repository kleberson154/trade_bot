"""
Análise de IA Multi-Provider (GRATUITO)
Ordem de tentativa:
  1. OLLAMA (local, ilimitado) → http://localhost:11434
  2. TOGETHER AI (cloud, ~100/dia) → api.together.xyz
  3. Fallback (análise calculada, sem IA)

Configuração em utils/config.py:
  - AI_PROVIDER: "multi" (padrão) | "ollama" | "together" | "groq"
  - OLLAMA_URL: "http://localhost:11434" (padrão)
  - TOGETHER_API_KEY: sua chave Together AI
  - GROQ_API_KEY: sua chave Groq (backup)
"""

import json
import urllib.request
import urllib.error
import os
from abc import ABC, abstractmethod
from typing import Dict, Optional
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


class OllamaProvider(AIProvider):
    """Ollama local - ilimitado, sem API key, privado."""
    
    def __init__(self, url: str = "http://localhost:11434", model: str = "mistral"):
        self.url = url
        self.model = model
    
    def is_available(self) -> bool:
        """Testa se Ollama está rodando."""
        try:
            req = urllib.request.Request(
                f"{self.url}/api/tags",
                method="GET",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False
    
    def analyze(self, prompt: str) -> Dict:
        """Chama Ollama local."""
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "temperature": 0.1,
        }).encode("utf-8")
        
        try:
            req = urllib.request.Request(
                f"{self.url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            
            raw = data.get("message", {}).get("content", "")
            result = self._parse_response(raw)
            logger.info(f"[OK] Ollama: conf={result['confidence']:.2f}")
            return result
        except Exception as e:
            logger.warning(f"[FAIL] Ollama falhou: {e}")
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
            logger.error(f"Erro ao parsear Ollama: {e}")
            return None


class TogetherAIProvider(AIProvider):
    """Together AI - cloud, ~100/dia grátis, modelo Llama."""
    
    def __init__(self, api_key: str, model: str = "meta-llama/Llama-2-7b-chat-hf"):
        self.api_key = api_key
        self.model = model
        self.url = "https://api.together.xyz/v1/chat/completions"
    
    def is_available(self) -> bool:
        """Testa se API key é válida (quick test)."""
        return bool(self.api_key)
    
    def analyze(self, prompt: str) -> Dict:
        """Chama Together AI."""
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 500,
            "temperature": 0.1,
        }).encode("utf-8")
        
        try:
            req = urllib.request.Request(
                self.url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            
            raw = data["choices"][0]["message"]["content"]
            result = self._parse_response(raw)
            logger.info(f"[OK] Together AI: conf={result['confidence']:.2f}")
            return result
        except Exception as e:
            logger.warning(f"[FAIL] Together AI falhou: {e}")
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
            logger.error(f"Erro ao parsear Together AI: {e}")
            return None


class AIAnalyzer:
    """
    Analisador multi-provider com fallback automático.
    Tenta: Ollama (local) → Together AI (cloud) → Fallback (calculado).
    """

    def __init__(self, groq_key: str = "", together_key: str = "", ollama_url: str = ""):
        self.providers = []
        
        # 1. Ollama (sempre tenta primeiro - local, ilimitado)
        ollama_url = ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama = OllamaProvider(url=ollama_url, model="mistral")
        self.providers.append(("Ollama", self.ollama))
        
        # 2. Together AI (second - cloud, ~100/dia grátis)
        together_key = together_key or os.getenv("TOGETHER_API_KEY", "")
        if together_key:
            self.together = TogetherAIProvider(api_key=together_key)
            self.providers.append(("Together AI", self.together))
        
        # 3. Fallback é automático (sem provider necessário)
        logger.info(f"AIAnalyzer Multi-Provider inicializado com {len(self.providers)} provider(s)")
        for name, _ in self.providers:
            logger.info(f"   - {name}")

    def analyze_opportunity(
        self,
        symbol: str,
        direction: str,
        context_data: Dict,
        trigger_data: Dict,
        market_data: Dict,
    ) -> Dict:
        """
        Tenta analisar com cada provider em ordem de preferência.
        Fallback automático se um falhar.
        """
        prompt = self._build_prompt(symbol, direction, context_data, trigger_data, market_data)
        
        # Tenta cada provider na ordem
        for provider_name, provider in self.providers:
            try:
                if not provider.is_available():
                    logger.debug(f"{provider_name} nao disponivel")
                    continue
                
                logger.debug(f"Tentando {provider_name}...")
                result = provider.analyze(prompt)
                
                if result:
                    logger.info(
                        f"[OK] {symbol} via {provider_name} | "
                        f"conf={result['confidence']:.2f} | rec={result['recommendation']}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"[ERR] {provider_name} erro: {e}")
                continue
        
        # Fallback: análise calculada (sem IA)
        logger.info(f"[FALLBACK] {symbol} usando analise calculada (IA indisponivel)")
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
