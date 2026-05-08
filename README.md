# 🤖 AI Trade Bot — Bybit Futures

Bot de day trade com IA para mercado de futuros na Bybit.
Utiliza **Smart Money Concepts**, **Wyckoff**, **Price Action** e **Claude AI** para análise de confluências.

---

## 📁 Estrutura do Projeto

```
trade_bot/
├── main.py                        # Entry point
├── requirements.txt
├── .env.example                   # Template de variáveis de ambiente
│
├── core/
│   ├── bot.py                     # Orquestrador principal
│   └── trade_state.py             # Gerenciador de estado dos trades
│
├── data/
│   └── bybit_client.py            # Conector API Bybit v5
│
├── contexts/
│   └── context_analyzer.py        # Análise dos 5 contextos de mercado
│
├── triggers/
│   └── trigger_analyzer.py        # Gatilhos de entrada (CHoCH, FVG, POI...)
│
├── strategies/
│   ├── indicators.py              # Indicadores técnicos (EMA, ATR, RSI, swings)
│   └── ai_analyzer.py             # Análise via Claude AI (Anthropic)
│
├── risk/
│   └── risk_manager.py            # Gerenciamento de risco (2%, RR 1:3, leverage)
│
├── notifications/
│   └── telegram_notifier.py       # Notificações Telegram
│
└── utils/
    ├── config.py                  # Configurações centrais
    └── logger.py                  # Sistema de logging
```

---

## 🧠 Lógica de Análise

### Contextos Analisados
| Contexto | Descrição |
|---|---|
| **Captura de Liquidez** | Stop hunts acima/abaixo de swing points com pavio longo |
| **Estrutura de Wyckoff** | Spring, Upthrust, fases de acumulação/distribuição |
| **Inversão de Fluxo** | Engolfamentos após sequências direcionais + delta de volume |
| **Rompimento de Regiões** | Breakouts de níveis-chave com confirmação de volume |
| **Macro e Micro** | Alinhamento entre 4H (bias) e 5min (execução) |

### Gatilhos de Entrada
| Gatilho | Descrição |
|---|---|
| **CHoCH** | Change of Character — quebra da estrutura |
| **FVG** | Fair Value Gap — gap entre 3 velas |
| **IFVG** | Inverse FVG — FVG preenchido (polaridade invertida) |
| **POI** | Point of Interest — zona de demanda/oferta |
| **Troca de Polaridade** | Suporte vira resistência e vice-versa |

> **Regra de Confluência**: Mínimo **2 gatilhos** + **2 contextos** para validar entrada.

### Pipeline de Análise
```
Dados OHLCV (1min/5min/15min/4H)
        ↓
[Contextos] → 5 análises paralelas
        ↓
[Gatilhos] → CHoCH + FVG + POI + Polaridade
        ↓
[Volume] → confirmação / divergência
        ↓
[Claude AI] → validação final + score de confiança
        ↓
[Risk Manager] → sizing 2%, RR 1:3, leverage dinâmica
        ↓
[Execução] → ordem market com SL e TP automáticos
        ↓
[Telegram] → notificação instantânea
```

---

## ⚙️ Configuração

### 1. Instalar dependências
```bash
cd trade_bot
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente
```bash
cp .env.example .env
# Edite o .env com seus dados
```

### 3. Obter credenciais

**Bybit API:**
1. Acesse [bybit.com](https://www.bybit.com/app/user/api-management)
2. Crie uma API Key com permissões: `Trade` (Read + Write) e `Positions` (Read)
3. **Comece sempre no Testnet**: [testnet.bybit.com](https://testnet.bybit.com)

**Telegram Bot:**
1. Fale com [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copie o token
3. Inicie conversa com seu bot
4. Acesse `https://api.telegram.org/bot<TOKEN>/getUpdates` para pegar o `chat_id`

**Anthropic (Claude AI):**
1. Acesse [console.anthropic.com](https://console.anthropic.com/api-keys)
2. Crie uma API Key

### 4. Executar
```bash
python main.py
```

---

## 🛡️ Gerenciamento de Risco

| Parâmetro | Valor |
|---|---|
| Risco por trade | **2% do saldo total** |
| RR mínimo | **1:3** (bot usa 1:3.5 para margem) |
| Stop diário | **-6% da banca** |
| Máx. trades simultâneos | **3** |
| Alavancagem (confiança > 85%) | **15x** |
| Alavancagem (confiança 75–85%) | **10x** |
| Alavancagem (confiança 65–75%) | **6x** |
| Confiança mínima | **65%** |

---

## 📱 Notificações Telegram

O bot envia 3 tipos de notificação:

1. **Trade Aberto** — Par, direção, entrada, SL, TP, alavancagem, confiança, gatilhos, contextos
2. **Trade Fechado** — Resultado (Win/Loss), PnL em USDT, motivo
3. **Status da Banca** (a cada 1h) — Equity, disponível, PnL do dia, wins, losses, win rate

---

## 🪙 Pares Operados

**Principais:** BTC, ETH, SOL  
**Altcoins:** TON, XRP, DOGE, WIF, HYPE, 1000PEPE, NEAR, TAO, FARTCOIN, SUI, ADA, DASH, ONDO, LINK, BNB, AAVE, NOT, VIRTUAL, XAUUSDT, ZEC

---

## ⚠️ Sugestões de Melhorias Futuras

1. **Backtesting** — Implementar engine de backtest com dados históricos da Bybit
2. **Trailing Stop** — Ativação após 50% do TP atingido
3. **Sessões de Mercado** — Filtrar horários por liquidez (Londres/NY)
4. **Correlação entre pares** — Evitar posições correlacionadas simultâneas
5. **Dashboard Web** — Interface para monitoramento em tempo real
6. **Machine Learning local** — Modelo treinado com histórico próprio de trades
7. **Gestão de portfólio** — Kelly Criterion para sizing dinâmico
8. **Alertas de sentimento** — Fear & Greed Index, funding rate extremos
9. **Paper trading mode** — Simular trades sem abrir ordens reais
10. **Multi-exchange** — Suporte a Binance, OKX como backup

---

## 🔴 AVISO IMPORTANTE

> **Trading de futuros envolve risco elevado de perda de capital.**
> Sempre teste no **Testnet** antes de usar dinheiro real.
> Este bot é uma ferramenta, não uma garantia de lucro.
> **Use com responsabilidade e gerencie seu risco.**
