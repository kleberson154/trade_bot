#!/usr/bin/env python3
"""
Teste: criar ordem e validar persistência de order_id no trade_state.json
"""
import json
import uuid
from data.bybit_client import BybitClient
from core.trade_state import TradeStateManager
from utils.config import Config

cfg = Config()
client = BybitClient(api_key=cfg.BYBIT_API_KEY, api_secret=cfg.BYBIT_API_SECRET, mode=cfg.BYBIT_MODE)
state = TradeStateManager()

print("\n" + "="*70)
print("TESTE: Criação de Ordem e Persistência de order_id")
print("="*70)

# Testa criação de 1 ordem real (ou mock)
print("\n[1] Testando place_market_order em ETHUSDT (10 USDT de risco)")

try:
    # Simula parâmetros de uma ordem
    symbol = "ETHUSDT"
    side = "Buy"
    qty = 0.05  # pequena quantidade
    leverage = 5
    
    # Tenta criar ordem no demo
    order_response = client.place_market_order(
        symbol=symbol,
        side=side,
        qty=qty,
        leverage=leverage,
    )
    
    print(f"✓ Ordem criada com sucesso!")
    print(f"  Response keys: {order_response.keys() if isinstance(order_response, dict) else 'N/A'}")
    
    # Extrai order_id da resposta
    order_id = None
    if isinstance(order_response, dict):
        for key in ("orderId", "order_id", "orderID", "id"):
            if key in order_response and order_response.get(key):
                order_id = order_response.get(key)
                break
    
    print(f"  order_id extraído: {order_id}")
    
    # Simula registro da ordem no state (como faria o bot)
    if order_id:
        state.open_trade(
            symbol=symbol,
            side=side,
            entry_price=100.0,  # placeholder
            stop_loss=95.0,     # placeholder
            take_profit=110.0,  # placeholder
            qty=qty,
            leverage=leverage,
            risk_usdt=10.0,
            rr_ratio=1.0,
            confidence=0.8,
            triggers=["TEST"],
            contexts=["test"],
            ai_reasoning="test order",
            order_id=order_id,  # IMPORTANTE: persistir order_id
        )
        print(f"✓ Trade registrado no estado com order_id: {order_id}")
    else:
        print(f"⚠ Aviso: order_id não encontrado na resposta")
    
except Exception as e:
    print(f"✗ Erro ao criar ordem: {e}")
    print(f"  Continuando com teste mock...")
    # Cria mock order com uuid
    order_id = str(uuid.uuid4())
    state.open_trade(
        symbol="ETHUSDT",
        side="Buy",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        qty=0.05,
        leverage=5,
        risk_usdt=10.0,
        rr_ratio=1.0,
        confidence=0.8,
        triggers=["TEST"],
        contexts=["test"],
        ai_reasoning="test order (mock)",
        order_id=order_id,
    )
    print(f"✓ Trade mock registrado com order_id: {order_id}")

# Valida persistência
print("\n[2] Validando persistência no trade_state.json")
open_trades = state.get_open_trades()
print(f"✓ Total de trades abertos: {len(open_trades)}")

found_with_order_id = False
for t in open_trades:
    if t.order_id and t.symbol == "ETHUSDT":
        print(f"  Trade: {t.id} | Symbol: {t.symbol} | order_id: {t.order_id} | Status: {t.status}")
        found_with_order_id = True

if found_with_order_id:
    print(f"✓ SUCESSO: Trade com order_id foi persistido!")
else:
    print(f"⚠ Aviso: Nenhum trade ETHUSDT com order_id encontrado")

# Lê o arquivo trade_state.json diretamente
print("\n[3] Verificando trade_state.json diretamente")
try:
    with open("data/trade_state.json", "r") as f:
        trades_data = json.load(f)
    
    for trade_id, trade_data in trades_data.items():
        if trade_data.get("symbol") == "ETHUSDT" and trade_data.get("status") == "open":
            print(f"  Trade ID: {trade_id}")
            print(f"    order_id: {trade_data.get('order_id')}")
            print(f"    qty: {trade_data.get('qty')}")
            print(f"    entry_price: {trade_data.get('entry_price')}")
            print(f"    ai_reasoning: {trade_data.get('ai_reasoning')}")
except Exception as e:
    print(f"✗ Erro ao ler trade_state.json: {e}")

print("\n" + "="*70)
print("Teste concluído!")
print("="*70 + "\n")
