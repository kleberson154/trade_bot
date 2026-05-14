"""
Conector com a API da Bybit (pybit v5)
"""

import asyncio
from typing import Optional, Dict, List, Any, Tuple
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
from pybit.unified_trading import HTTP
from utils.logger import setup_logger

logger = setup_logger("bybit_client")


class BybitClient:
    """Wrapper assíncrono para a API Bybit Unified Trading v5."""

    def __init__(self, api_key: str, api_secret: str, mode: str = "testnet"):
        # Validar modo e configurar HTTP corretamente
        if mode not in ["testnet", "demo", "real"]:
            raise ValueError(f"Mode deve ser 'testnet', 'demo' ou 'real', recebeu: {mode}")
        
        # pybit HTTP: testnet=True usa testnet, testnet=False usa produção
        # Para demo, precisamos usar testnet=False mas com URL customizada
        use_testnet = (mode == "testnet")
        
        self.session = HTTP(
            testnet=use_testnet,
            api_key=api_key,
            api_secret=api_secret,
        )
        
        # Se for demo, sobrescreve a URL da sessão
        if mode == "demo":
            self.session.endpoint = "https://api-demo.bybit.com"
        
        self.mode = mode
        logger.info(f"BybitClient iniciado | modo={mode} | endpoint={self.session.endpoint}")

    # ── Dados de Mercado ───────────────────────────────────────────────────────

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
    ) -> pd.DataFrame:
        """Retorna candles como DataFrame OHLCV."""
        try:
            resp = self.session.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
            raw = resp["result"]["list"]
            if not raw:
                return pd.DataFrame()

            df = pd.DataFrame(
                raw,
                columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"],
            )
            df = df.astype({
                "timestamp": "int64",
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
            })
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df
        except Exception as e:
            logger.error(f"Erro get_klines {symbol} {interval}: {e}")
            return pd.DataFrame()

    def get_orderbook(self, symbol: str, limit: int = 25) -> Dict:
        """Retorna orderbook do símbolo."""
        try:
            resp = self.session.get_orderbook(category="linear", symbol=symbol, limit=limit)
            return resp["result"]
        except Exception as e:
            logger.error(f"Erro get_orderbook {symbol}: {e}")
            return {}

    def get_ticker(self, symbol: str) -> Dict:
        """Retorna ticker do símbolo."""
        try:
            resp = self.session.get_tickers(category="linear", symbol=symbol)
            return resp["result"]["list"][0]
        except Exception as e:
            logger.error(f"Erro get_ticker {symbol}: {e}")
            return {}

    # ── Conta ──────────────────────────────────────────────────────────────────

    def get_wallet_balance(self) -> Dict:
        """Retorna saldo da conta (USDT)."""
        try:
            resp = self.session.get_wallet_balance(accountType="UNIFIED")
            account_list = resp["result"]["list"]
            
            # Processa conta UNIFIED
            for account in account_list:
                if account.get("accountType") == "UNIFIED":
                    coins = account["coin"]
                    for c in coins:
                        if c["coin"] == "USDT":
                            # Helper para converter com segurança
                            def safe_float(val, default=0.0):
                                if not val or val == "":
                                    return default
                                try:
                                    return float(val)
                                except (ValueError, TypeError):
                                    return default
                            
                            equity = safe_float(c.get("equity", 0))
                            total_position_im = safe_float(c.get("totalPositionIM", 0))
                            unrealised_pnl = safe_float(c.get("unrealisedPnl", 0))
                            
                            # Saldo disponível = Equity - Initial Margin comprometido nas posições
                            # Esta é a margem que pode ser usada para novas posições
                            available = max(0, equity - total_position_im)
                            
                            logger.debug(
                                f"Wallet: equity={equity:.2f}, totalPositionIM={total_position_im:.2f}, "
                                f"available={available:.2f}"
                            )
                            
                            return {
                                "equity": equity,
                                "available": available,
                                "unrealised_pnl": unrealised_pnl,
                            }
            
            return {"equity": 0, "available": 0, "unrealised_pnl": 0}
        except Exception as e:
            logger.error(f"Erro get_wallet_balance: {e}")
            return {"equity": 0, "available": 0, "unrealised_pnl": 0}

    def get_available_margin(self) -> float:
        """Retorna margem disponível (USDT) para novas posições."""
        try:
            wallet = self.get_wallet_balance()
            return wallet["available"]
        except Exception as e:
            logger.error(f"Erro get_available_margin: {e}")
            return 0.0

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Retorna posições abertas."""
        try:
            kwargs = {"category": "linear", "settleCoin": "USDT"}
            if symbol:
                kwargs["symbol"] = symbol
            resp = self.session.get_positions(**kwargs)
            return [p for p in resp["result"]["list"] if float(p.get("size", 0)) > 0]
        except Exception as e:
            logger.error(f"Erro get_positions: {e}")
            return []

    # ── Ordens ────────────────────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Define alavancagem do par."""
        try:
            self.session.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            return True
        except Exception as e:
            # Ignora erro se já estiver na alavancagem correta
            if "leverage not modified" in str(e).lower():
                return True
            logger.error(f"Erro set_leverage {symbol} {leverage}x: {e}")
            return False

    def get_instrument_info(self, symbol: str) -> Optional[Dict]:
        """Retorna informações do instrumento (min/max qty, precision, etc)."""
        try:
            resp = self.session.get_instruments_info(category="linear", symbol=symbol)
            if resp["result"]["list"]:
                return resp["result"]["list"][0]
            return None
        except Exception as e:
            logger.error(f"Erro get_instrument_info {symbol}: {e}")
            return None

    def validate_and_adjust_qty(self, symbol: str, qty: float) -> Tuple[float, str]:
        """
        Valida quantidade contra limites Bybit.
        Retorna (qty_ajustada, mensagem_status).
        """
        try:
            info = self.get_instrument_info(symbol)
            if not info:
                return qty, "aviso: info do instrumento não disponível"
            
            lot_size_filter = info.get("lotSizeFilter", {})
            min_qty = float(lot_size_filter.get("minOrderQty", 0))
            max_qty = float(lot_size_filter.get("maxOrderQty", 10000))
            qty_step = float(lot_size_filter.get("qtyStep", 0.01))
            
            qty_adjusted = qty
            adjustments = []
            
            # Valida mínimo
            if qty < min_qty:
                adjustments.append(f"qty<min({min_qty})")
                qty_adjusted = min_qty
            
            # Valida máximo
            if qty > max_qty:
                adjustments.append(f"qty>max({max_qty})")
                qty_adjusted = max_qty
            
            # Arredonda para qtyStep com precisão Decimal (evita floating point errors)
            if qty_step > 0:
                qty_before = qty_adjusted
                # Usa Decimal para aritmética exata
                qty_decimal = Decimal(str(qty_adjusted))
                step_decimal = Decimal(str(qty_step))
                # Divide, arredonda e multiplica de volta
                qty_adjusted = float(
                    (qty_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * step_decimal
                )
                if qty_before != qty_adjusted:
                    adjustments.append(f"step({qty_step})")
            
            msg = f"[min={min_qty}, max={max_qty}, step={qty_step}]"
            if adjustments:
                msg = f"ajustado({', '.join(adjustments)}) {msg}"
            else:
                msg = f"validado {msg}"
            
            return qty_adjusted, msg
        except Exception as e:
            logger.warning(f"Erro validar qty {symbol}: {e}, usando valor original")
            return qty, f"erro na validação: {e}"

    def place_market_order(
        self,
        symbol: str,
        side: str,          # "Buy" ou "Sell"
        qty: float,
        stop_loss: float,
        take_profit: float,
        leverage: int = 5,
    ) -> Optional[Dict]:
        """Abre ordem a mercado com SL e TP."""
        try:
            # Valida e ajusta quantidade
            qty_original = qty
            qty, qty_msg = self.validate_and_adjust_qty(symbol, qty)
            if qty != qty_original:
                logger.info(f"{symbol} qty ajustada: {qty_original} → {qty} ({qty_msg})")
            
            self.set_leverage(symbol, leverage)
            resp = self.session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                stopLoss=str(round(stop_loss, 4)),
                takeProfit=str(round(take_profit, 4)),
                tpslMode="Full",
                slTriggerBy="MarkPrice",
                tpTriggerBy="MarkPrice",
                reduceOnly=False,
            )
            order_id = resp["result"]["orderId"]
            logger.info(f"Ordem aberta: {symbol} {side} qty={qty} SL={stop_loss} TP={take_profit} | id={order_id}")
            return {"order_id": order_id, **resp["result"]}
        except Exception as e:
            logger.error(f"Erro place_market_order {symbol}: {e}")
            logger.debug(f"Tentou enviar: qty={qty}, SL={stop_loss}, TP={take_profit}")
            return None

    def close_position(self, symbol: str, side: str, qty: float) -> bool:
        """Fecha posição aberta."""
        try:
            close_side = "Sell" if side == "Buy" else "Buy"
            self.session.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=str(qty),
                reduceOnly=True,
            )
            logger.info(f"Posição fechada: {symbol}")
            return True
        except Exception as e:
            logger.error(f"Erro close_position {symbol}: {e}")
            return False

    def get_closed_pnl(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Retorna PnL dos trades fechados."""
        try:
            kwargs = {"category": "linear", "limit": limit}
            if symbol:
                kwargs["symbol"] = symbol
            resp = self.session.get_closed_pnl(**kwargs)
            return resp["result"]["list"]
        except Exception as e:
            logger.error(f"Erro get_closed_pnl: {e}")
            return []
