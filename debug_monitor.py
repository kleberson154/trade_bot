#!/usr/bin/env python3
"""Debug: compara trade_state.json com posições da exchange e mostra correspondências por order_id."""
from data.bybit_client import BybitClient
from core.trade_state import TradeStateManager
from utils.config import Config
import json

cfg = Config()
client = BybitClient(api_key=cfg.BYBIT_API_KEY, api_secret=cfg.BYBIT_API_SECRET, mode=cfg.BYBIT_MODE)
state = TradeStateManager()

# Pega posições e tenta importar para o estado local (reconciliação)
positions = client.get_positions()
try:
    state.import_positions(positions)
except Exception:
    pass

print('\n=== Trades registrados (abertos) ===')
open_trades = state.get_open_trades()
for t in open_trades:
    print(json.dumps({
        'id': t.id,
        'symbol': t.symbol,
        'order_id': t.order_id,
        'qty': t.qty,
        'status': t.status,
        'opened_at': t.opened_at
    }, indent=2))

print('\n=== Posições na exchange ===')
print(json.dumps(positions, indent=2, default=str))

# Verifica correspondência por order_id
print('\n=== Correspondência (por order_id) ===')
for t in open_trades:
    matched = []
    for p in positions:
        for key in ('orderId','order_id','orderID','id'):
            if p.get(key) and str(p.get(key)) == str(t.order_id):
                matched.append(p)
    print(f"Trade {t.id} order_id={t.order_id} -> matches: {len(matched)}")
    if matched:
        print(json.dumps(matched, indent=2, default=str))

# Verifica fallback por símbolo
print('\n=== Correspondência (fallback por símbolo) ===')
for t in open_trades:
    sym_matches = [p for p in positions if p.get('symbol') == t.symbol]
    print(f"Trade {t.id} symbol={t.symbol} -> positions: {len(sym_matches)}")
    if sym_matches:
        print(json.dumps(sym_matches, indent=2, default=str))

print('\n=== Done ===')
