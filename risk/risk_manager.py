"""
Gerenciamento de Risco
- 2% de risco por trade
- RR mínimo 1:3
- Stop diário
- Alavancagem dinâmica por confiança
"""

from dataclasses import dataclass
from typing import Optional, Tuple
from utils.logger import setup_logger
from utils.config import Config

logger = setup_logger("risk_manager")


@dataclass
class TradeParams:
    symbol: str
    side: str                  # "Buy" / "Sell"
    entry_price: float
    stop_loss: float
    take_profit: float
    qty: float
    leverage: int
    risk_usdt: float
    rr_ratio: float
    confidence: float


class RiskManager:
    """Gerencia risco e dimensionamento de posição."""

    def __init__(self, config: Config):
        self.cfg = config
        self.daily_loss: float = 0.0
        self.daily_start_equity: float = 0.0

    # ── Validação de RR ───────────────────────────────────────────────────────

    def validate_rr(
        self,
        entry: float,
        stop_loss: float,
        take_profit: float,
        side: str,
    ) -> Tuple[bool, float]:
        """Valida se o RR mínimo (1:3) é satisfeito."""
        if side == "Buy":
            risk = entry - stop_loss
            reward = take_profit - entry
        else:
            risk = stop_loss - entry
            reward = entry - take_profit

        if risk <= 0 or reward <= 0:
            return False, 0.0

        rr = reward / risk
        valid = rr >= self.cfg.MIN_RR_RATIO
        if not valid:
            logger.debug(f"RR inválido: {rr:.2f} < {self.cfg.MIN_RR_RATIO}")
        return valid, round(rr, 2)

    # ── Cálculo de Tamanho ────────────────────────────────────────────────────

    def calculate_position_size(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        side: str,
        leverage: int,
    ) -> Tuple[float, float]:
        """
        Calcula quantidade e risco em USDT.
        
        Fórmula:
        - Risco = 2% do equity total
        - distância_sl = |entry - stop_loss|
        - qty = risco_usdt / distância_sl
        
        Exemplo:
        - equity=100, risco=2 USDT
        - entry=10, SL=9 → distância=1
        - qty = 2/1 = 2 contratos
        - Se preço cai para SL, perde 1*2=2 USDT (exato!)
        """
        risk_usdt = equity * self.cfg.RISK_PER_TRADE

        if side == "Buy":
            sl_distance = entry_price - stop_loss
        else:
            sl_distance = stop_loss - entry_price

        if sl_distance <= 0:
            logger.warning(f"SL inválido: entry={entry_price}, SL={stop_loss}, side={side}")
            return 0.0, 0.0

        # Cálculo direto: quantidade = risco / distância por unidade
        qty = risk_usdt / sl_distance
        qty = round(qty, 8)  # Arredonda para 8 casas (padrão Bybit)

        return qty, round(risk_usdt, 2)

    # ── Alavancagem por Confiança ─────────────────────────────────────────────

    def get_leverage(self, confidence: float) -> int:
        """Mapeia score de confiança para alavancagem."""
        if confidence >= 0.85:
            return self.cfg.CONFIDENCE_LEVERAGE_MAP["very_high"]
        elif confidence >= 0.75:
            return self.cfg.CONFIDENCE_LEVERAGE_MAP["high"]
        elif confidence >= self.cfg.MIN_CONFLUENCE_SCORE:
            return self.cfg.CONFIDENCE_LEVERAGE_MAP["medium"]
        else:
            return self.cfg.CONFIDENCE_LEVERAGE_MAP["low"]

    # ── Stop Diário ───────────────────────────────────────────────────────────

    def check_daily_drawdown(self, current_equity: float) -> bool:
        """Verifica se o stop diário foi atingido."""
        if self.daily_start_equity <= 0:
            return False

        daily_pnl_pct = (current_equity - self.daily_start_equity) / self.daily_start_equity
        if daily_pnl_pct <= -self.cfg.MAX_DAILY_LOSS:
            logger.warning(
                f"STOP DIÁRIO atingido: {daily_pnl_pct:.2%} | "
                f"Limit={-self.cfg.MAX_DAILY_LOSS:.2%}"
            )
            return True
        return False

    def reset_daily(self, equity: float):
        """Reseta contadores diários."""
        self.daily_start_equity = equity
        self.daily_loss = 0.0
        logger.info(f"Contadores diários resetados | Equity={equity:.2f} USDT")

    # ── Montagem do Trade ─────────────────────────────────────────────────────

    def build_trade(
        self,
        symbol: str,
        side: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        equity: float,
    ) -> Optional[TradeParams]:
        """
        Valida e monta os parâmetros completos de um trade.
        Retorna None se qualquer validação falhar.
        """
        # 1. Valida RR
        rr_ok, rr_ratio = self.validate_rr(entry, stop_loss, take_profit, side)
        if not rr_ok:
            return None

        # 2. Confiança mínima
        if confidence < self.cfg.MIN_CONFLUENCE_SCORE:
            logger.debug(f"{symbol} confiança insuficiente: {confidence:.2f}")
            return None

        # 3. Alavancagem
        leverage = self.get_leverage(confidence)
        leverage = min(leverage, self.cfg.MAX_LEVERAGE)

        # 4. Tamanho da posição
        qty, risk_usdt = self.calculate_position_size(equity, entry, stop_loss, side, leverage)
        if qty <= 0:
            return None

        return TradeParams(
            symbol=symbol,
            side=side,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            qty=qty,
            leverage=leverage,
            risk_usdt=risk_usdt,
            rr_ratio=rr_ratio,
            confidence=confidence,
        )
