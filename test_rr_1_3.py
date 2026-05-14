#!/usr/bin/env python3
"""Teste: validar cálculo de TP com RR 1:3 fixo"""
import pandas as pd
from triggers.trigger_analyzer import TriggerAnalyzer
from utils.config import Config

cfg = Config()
analyzer = TriggerAnalyzer(config=cfg)

# Simula dados OHLCV para teste
data = {
    'open': [100, 101, 102],
    'high': [102, 103, 104],
    'low': [99, 100, 101],
    'close': [101, 102, 103],
    'volume': [1000, 1100, 1200],
}
df = pd.DataFrame(data)

# Simula gatilhos
triggers = [
    {
        'trigger': 'TEST_BUY',
        'price': 101.0,
        'zone_bottom': 99.5,
        'zone_top': 102.5,
    }
]

print("\n" + "="*70)
print("TESTE: Validação de RR 1:3 Fixo no Take Profit")
print("="*70)

# Testa Buy
entry_buy, sl_buy, tp_buy = analyzer._calculate_levels(df, triggers, "Buy", 101.0, 1.0)
if entry_buy and sl_buy and tp_buy:
    risk_buy = entry_buy - sl_buy
    reward_buy = tp_buy - entry_buy
    rr_buy = reward_buy / risk_buy if risk_buy > 0 else 0
    print(f"\n[BUY]")
    print(f"  Entry:  {entry_buy:.4f}")
    print(f"  SL:     {sl_buy:.4f}")
    print(f"  TP:     {tp_buy:.4f}")
    print(f"  Risk:   {risk_buy:.4f}")
    print(f"  Reward: {reward_buy:.4f}")
    print(f"  RR:     1:{rr_buy:.2f} {'✓' if abs(rr_buy - 3.0) < 0.1 else '✗'}")

# Testa Sell
entry_sell, sl_sell, tp_sell = analyzer._calculate_levels(df, triggers, "Sell", 101.0, 1.0)
if entry_sell and sl_sell and tp_sell:
    risk_sell = sl_sell - entry_sell
    reward_sell = entry_sell - tp_sell
    rr_sell = reward_sell / risk_sell if risk_sell > 0 else 0
    print(f"\n[SELL]")
    print(f"  Entry:  {entry_sell:.4f}")
    print(f"  SL:     {sl_sell:.4f}")
    print(f"  TP:     {tp_sell:.4f}")
    print(f"  Risk:   {risk_sell:.4f}")
    print(f"  Reward: {reward_sell:.4f}")
    print(f"  RR:     1:{rr_sell:.2f} {'✓' if abs(rr_sell - 3.0) < 0.1 else '✗'}")

print("\n" + "="*70)
print("Teste concluído!")
print("="*70 + "\n")
