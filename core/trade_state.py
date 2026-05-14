"""
Gerenciador de Estado dos Trades
- Rastreia trades abertos e fechados
- Calcula estatísticas (wins, losses, PnL)
- Persiste estado em JSON local
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from utils.logger import setup_logger

logger = setup_logger("trade_state")


@dataclass
class Trade:
    id: str
    symbol: str
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    qty: float
    leverage: int
    risk_usdt: float
    rr_ratio: float
    confidence: float
    triggers: List[str]
    contexts: List[str]
    ai_reasoning: str
    opened_at: str
    closed_at: Optional[str] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    status: str = "open"   # open | closed_tp | closed_sl | closed_manual
    order_id: Optional[str] = None


class TradeStateManager:
    """Persiste e recupera estado dos trades."""

    STATE_FILE = Path("data/trade_state.json")

    def __init__(self):
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._trades: Dict[str, Trade] = {}
        self._load()

    # ── Persistência ──────────────────────────────────────────────────────────

    def _load(self):
        """Carrega estado do arquivo JSON."""
        if self.STATE_FILE.exists():
            try:
                with open(self.STATE_FILE, "r") as f:
                    raw = json.load(f)
                self._trades = {k: Trade(**v) for k, v in raw.items()}
                logger.info(f"Estado carregado: {len(self._trades)} trades")
            except Exception as e:
                logger.error(f"Erro ao carregar estado: {e}")
                self._trades = {}

    def _save(self):
        """Salva estado no arquivo JSON."""
        try:
            with open(self.STATE_FILE, "w") as f:
                json.dump({k: asdict(v) for k, v in self._trades.items()}, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")

    # ── CRUD de Trades ────────────────────────────────────────────────────────

    def open_trade(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        qty: float,
        leverage: int,
        risk_usdt: float,
        rr_ratio: float,
        confidence: float,
        triggers: List[str],
        contexts: List[str],
        ai_reasoning: str,
        order_id: Optional[str] = None,
    ) -> Trade:
        """Registra novo trade aberto."""
        trade_id = str(uuid.uuid4())[:8]
        trade = Trade(
            id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            qty=qty,
            leverage=leverage,
            risk_usdt=risk_usdt,
            rr_ratio=rr_ratio,
            confidence=confidence,
            triggers=triggers,
            contexts=contexts,
            ai_reasoning=ai_reasoning,
            opened_at=datetime.now().isoformat(),
            order_id=order_id,
        )
        self._trades[trade_id] = trade
        self._save()
        logger.info(f"Trade registrado: {trade_id} | {symbol} {side}")
        return trade

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        reason: str = "manual",
    ) -> Optional[Trade]:
        """Fecha um trade e calcula PnL."""
        trade = self._trades.get(trade_id)
        if not trade:
            return None

        pnl_per_unit = (exit_price - trade.entry_price) if trade.side == "Buy" else (trade.entry_price - exit_price)
        pnl = pnl_per_unit * trade.qty
        pnl_pct = (pnl / trade.risk_usdt) * 100 if trade.risk_usdt > 0 else 0

        trade.closed_at = datetime.now().isoformat()
        trade.exit_price = exit_price
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = round(pnl_pct, 2)
        trade.status = reason

        self._save()
        logger.info(f"Trade fechado: {trade_id} | PnL={pnl:+.4f} USDT")
        return trade

    def get_open_trades(self) -> List[Trade]:
        """Retorna trades abertos."""
        return [t for t in self._trades.values() if t.status == "open"]

    def get_open_trade_by_symbol(self, symbol: str) -> Optional[Trade]:
        """Retorna trade aberto para um símbolo."""
        for t in self.get_open_trades():
            if t.symbol == symbol:
                return t
        return None

    # ── Estatísticas ──────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Calcula estatísticas globais."""
        closed = [t for t in self._trades.values() if t.status != "open"]
        wins = [t for t in closed if (t.pnl or 0) > 0]
        losses = [t for t in closed if (t.pnl or 0) <= 0]

        total_pnl = sum(t.pnl or 0 for t in closed)
        win_rate = len(wins) / len(closed) if closed else 0

        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate * 100, 1),
            "total_pnl": round(total_pnl, 4),
            "open_trades": len(self.get_open_trades()),
        }

    def get_daily_pnl(self) -> float:
        """PnL do dia atual."""
        today = datetime.now().date().isoformat()
        daily = [
            t.pnl or 0
            for t in self._trades.values()
            if t.status != "open" and (t.closed_at or "")[:10] == today
        ]
        return round(sum(daily), 4)

    # ── Importar posições da exchange ───────────────────────────────────────
    def import_positions(self, positions: List[Dict]):
        """Importa posições abertas da exchange para o estado local.

        Para cada posição não representada no estado, cria um registro "open"
        com campos mínimos para rastreamento (order_id, symbol, qty, entry_price).
        """
        added = 0
        for p in positions:
            # tenta extrair um order id
            order_id = None
            for key in ("orderId", "order_id", "orderID", "id"):
                if key in p and p.get(key):
                    order_id = str(p.get(key))
                    break

            # já existe trade com o mesmo order_id?
            exists = False
            if order_id:
                for t in self._trades.values():
                    if t.order_id and str(t.order_id) == order_id and t.status == "open":
                        exists = True
                        break

            # fallback: existe trade aberto para mesmo símbolo e tamanho aproximado?
            if not exists:
                size = float(p.get("size", 0))
                for t in self.get_open_trades():
                    if t.symbol == p.get("symbol") and abs(t.qty - size) < 1e-6:
                        exists = True
                        break

            if exists:
                continue

            # cria trade mínimo para rastrear
            try:
                side = p.get("side", "Buy")
                symbol = p.get("symbol")
                entry_price = float(p.get("avgPrice", 0)) or float(p.get("entryPrice", 0)) or 0.0
                stop_loss = float(p.get("stopLoss", 0)) if p.get("stopLoss") else 0.0
                take_profit = float(p.get("takeProfit", 0)) if p.get("takeProfit") else 0.0
                qty = float(p.get("size", 0))
                leverage = int(p.get("leverage", 1)) if p.get("leverage") else 1

                # registra com campos mínimos
                self.open_trade(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    qty=qty,
                    leverage=leverage,
                    risk_usdt=0.0,
                    rr_ratio=0.0,
                    confidence=0.0,
                    triggers=[],
                    contexts=[],
                    ai_reasoning="imported",
                    order_id=order_id,
                )
                added += 1
            except Exception as e:
                logger.debug(f"Falha ao importar posição {p.get('symbol')}: {e}")

        if added:
            logger.info(f"Importadas {added} posições da exchange para o estado local")
