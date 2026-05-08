"""
Configurações centrais do bot
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # ── Bybit API ──────────────────────────────────────────────
    BYBIT_API_KEY: str = field(default_factory=lambda: os.getenv("BYBIT_API_KEY", ""))
    BYBIT_API_SECRET: str = field(default_factory=lambda: os.getenv("BYBIT_API_SECRET", ""))
    # BYBIT_MODE: "testnet" (API testnet), "demo" (Demo da conta real), "real" (Produção)
    BYBIT_MODE: str = field(default_factory=lambda: os.getenv("BYBIT_MODE", "demo"))
    BYBIT_TESTNET: bool = field(default_factory=lambda: os.getenv("BYBIT_TESTNET", "true").lower() == "true")

    # ── Telegram ───────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    TELEGRAM_CHAT_ID: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # ── Groq AI (gratuito) ─────────────────────────────────────
    # Crie sua chave gratuita em: https://console.groq.com (sem cartão)
    GROQ_API_KEY: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))

    # ── AI Multi-Provider (Ollama + Together AI + Fallback) ───────
    # 1. OLLAMA (local, ilimitado) - https://ollama.ai
    OLLAMA_URL: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    
    # 2. TOGETHER AI (cloud, ~100/dia grátis) - https://www.together.ai/
    TOGETHER_API_KEY: str = field(default_factory=lambda: os.getenv("TOGETHER_API_KEY", ""))
    
    # 3. Fallback automático (análise calculada, sem IA)

    # ── Gerenciamento de Risco ─────────────────────────────────
    RISK_PER_TRADE: float = 0.02          # 2% do saldo por trade
    MIN_RR_RATIO: float = 3.0             # Mínimo 1:3 Risk/Reward
    MAX_OPEN_TRADES: int = 3              # Máximo de trades simultâneos
    MAX_DAILY_LOSS: float = 0.06          # Stop diário: -6% da banca
    MAX_LEVERAGE: int = 20                # Alavancagem máxima permitida
    MIN_LEVERAGE: int = 2                 # Alavancagem mínima
    TRAILING_STOP_ACTIVATION: float = 0.5  # Ativar trailing após 50% do TP

    # ── Pares Operados ─────────────────────────────────────────
    SYMBOLS: List[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "SOLUSDT",
        "TONUSDT", "XRPUSDT", "DOGEUSDT",
        "WIFUSDT", "HYPEUSDT", "1000PEPEUSDT",
        "NEARUSDT", "TAOUSDT", "FARTCOINUSDT",
        "SUIUSDT", "ADAUSDT", "DASHUSDT",
        "ONDOUSDT", "LINKUSDT", "BNBUSDT",
        "AAVEUSDT", "NOTUSDT", "VIRTUALUSDT",
        "XAUUSDT", "ZECUSDT",
    ])

    # ── Timeframes ─────────────────────────────────────────────
    PRIMARY_TF: str = "15"       # Timeframe primário (15 min)
    MACRO_TF: str = "240"        # Macro: 4H
    MICRO_TF: str = "5"          # Micro: 5 min
    ENTRY_TF: str = "1"          # Refinamento de entrada: 1 min

    # ── Parâmetros de Análise ──────────────────────────────────
    CANDLES_LOOKBACK: int = 200           # Candles para análise
    MIN_CONFLUENCE_SCORE: float = 0.65    # Score mínimo para entrada (0-1)
    VOLUME_DIVERGENCE_THRESHOLD: float = 1.5  # Multiplicador volume anomalia
    
    # ── Validação de Gatilhos (Recenticidade) ──────────────────
    # Máximo de candles desde detecção do gatilho para considerar "recente"
    # Evita entradas muito atrasadas no passado
    MAX_TRIGGER_AGE_CANDLES: int = 8      # ~120 min em 15min TF, ~40 min em 5min TF
    PREFER_RECENT_TRIGGERS: bool = True   # Se True, desconta score de gatilhos antigos

    # ── Loop do Bot ───────────────────────────────────────────
    SCAN_INTERVAL: int = 60       # Segundos entre scans
    STATUS_INTERVAL: int = 3600   # Status a cada 1h

    # ── Categorias de confiança ────────────────────────────────
    # Define alavancagem baseada na confiança do bot
    CONFIDENCE_LEVERAGE_MAP: dict = field(default_factory=lambda: {
        "very_high": 15,   # > 0.85
        "high": 10,        # 0.75 - 0.85
        "medium": 6,       # 0.65 - 0.75
        "low": 3,          # Abaixo do threshold → não opera
    })
