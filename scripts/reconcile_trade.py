#!/usr/bin/env python3
"""Tenta reconciliar trades fechados locais com os registros de PnL fechados da Bybit.

Procura trades no `data/trade_state.json` que estejam fechados e, para cada um,
consulta `get_closed_pnl(symbol=...)` para tentar encontrar um match por preço/qtd/pnl.
"""
import json
from pathlib import Path
from utils.config import Config
from data.bybit_client import BybitClient


def load_trade_state(path: Path):
    with open(path, "r") as f:
        return json.load(f)


def approx_equal(a, b, rel_tol=1e-3, abs_tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))
    except Exception:
        return False


def main():
    cfg = Config()
    client = BybitClient(api_key=cfg.BYBIT_API_KEY, api_secret=cfg.BYBIT_API_SECRET, mode=cfg.BYBIT_MODE)

    state_path = Path("data/trade_state.json")
    state = load_trade_state(state_path)

    # encontra trades fechados
    closed_trades = [t for t in state.values() if t.get("status") and t.get("status") != "open"]
    if not closed_trades:
        print("Nenhum trade fechado encontrado no trade_state.json")
        return

    for t in closed_trades:
        print(f"\nProcurando correspondência para trade id={t.get('id')} symbol={t.get('symbol')}")
        symbol = t.get("symbol")
        exit_price = t.get("exit_price")
        qty = t.get("qty")
        pnl = t.get("pnl")

        candidates = client.get_closed_pnl(symbol=symbol, limit=200)
        print(f"  {len(candidates)} registros fechados obtidos da exchange para {symbol}")

        # imprime resumo dos candidatos para inspeção manual
        for i, c in enumerate(candidates, 1):
            c_exit = c.get("closePrice") or c.get("exit_price") or c.get("exitPrice") or c.get("price")
            c_qty = c.get("size") or c.get("qty") or c.get("execQty") or c.get("close_qty")
            c_pnl = c.get("realisedPnl") or c.get("pnl") or c.get("profit")
            c_order = None
            for key in ("orderId", "order_id", "orderID", "id"):
                if c.get(key):
                    c_order = c.get(key)
                    break

            print(f"  [{i}] exit={c_exit} qty={c_qty} pnl={c_pnl} order_id={c_order}")

        matches = []
        for c in candidates:
            c_exit = c.get("closePrice") or c.get("exit_price") or c.get("exitPrice") or c.get("price")
            c_pnl = c.get("realisedPnl") or c.get("pnl") or c.get("profit")
            if (approx_equal(c_exit, exit_price, rel_tol=2e-3) or approx_equal(c_pnl, pnl, rel_tol=2e-3)):
                matches.append({"candidate": c, "reason": "price_or_pnl_close"})

        if matches:
            print(f"  Encontrado {len(matches)} possíveis correspondências:")
            for m in matches:
                print(json.dumps(m["candidate"], indent=2, default=str))
        else:
            print("  Nenhuma correspondência direta encontrada (preço/pnl).")


if __name__ == "__main__":
    main()
