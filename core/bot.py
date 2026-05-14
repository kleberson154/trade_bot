"""
Orquestrador principal do Trading Bot
Coordena: dados → contexto → gatilhos → IA → risco → ordem → notificação
"""

import asyncio
from datetime import datetime, time as dtime
from typing import Optional
from utils.config import Config
from utils.logger import setup_logger
from data.bybit_client import BybitClient
from strategies.indicators import analyze_volume, add_atr, find_swing_highs_lows
from contexts.context_analyzer import ContextAnalyzer
from triggers.trigger_analyzer import TriggerAnalyzer
from strategies.ai_analyzer import AIAnalyzer
from risk.risk_manager import RiskManager
from core.trade_state import TradeStateManager
from notifications.telegram_notifier import TelegramNotifier

logger = setup_logger("bot")


class TradingBot:
    """Bot principal de trading."""

    def __init__(self, config: Config):
        self.cfg = config
        self.running = False

        # Inicializa componentes
        self.exchange = BybitClient(
            api_key=config.BYBIT_API_KEY,
            api_secret=config.BYBIT_API_SECRET,
            mode=config.BYBIT_MODE,
        )
        self.context_analyzer = ContextAnalyzer()
        self.trigger_analyzer = TriggerAnalyzer(config=config)
        self.ai_analyzer = AIAnalyzer(groq_key=config.GROQ_API_KEY)
        self.risk_manager = RiskManager(config)
        self.state = TradeStateManager()
        self.telegram = TelegramNotifier(
            token=config.TELEGRAM_BOT_TOKEN,
            chat_id=config.TELEGRAM_CHAT_ID,
        )

        # Reconciliação inicial: importa posições abertas da exchange para o estado local
        try:
            positions = self.exchange.get_positions()
            if positions:
                self.state.import_positions(positions)
        except Exception as e:
            logger.debug(f"Falha na reconciliação inicial de posições: {e}")

        self._last_status_time: Optional[datetime] = None
        self._daily_reset_done: bool = False

    # ── Cálculo de Confiança com Bônus ────────────────────────────────────────

    def _calculate_bonus_metrics(
        self,
        context_count: int,
        trigger_count: int,
    ) -> tuple[float, bool, str]:
        """
        Calcula o bônus total e classifica a força da trade.
        
        Retorna: (bonus_total, is_strong_trade, trade_type)
        
        Classificação:
        - Trade Base: bônus = 0 (1 contexto + 1 gatilho)
        - Trade Forte: bônus >= 0.08 (2+ contextos OU 2+ gatilhos)
        - Trade Fortíssima: bônus >= 0.13 (2+ contextos E 2+ gatilhos)
        """
        bonus_contexts = max(0, (context_count - 1)) * 0.08
        bonus_triggers = max(0, (trigger_count - 1)) * 0.05
        bonus_total = bonus_contexts + bonus_triggers
        
        # Classificação da trade
        if bonus_total >= 0.13:
            trade_type = "FORTÍSSIMA 💎"
            is_strong = True
        elif bonus_total >= 0.08:
            trade_type = "FORTE 🔥"
            is_strong = True
        else:
            trade_type = "BASE ✓"
            is_strong = False
        
        return bonus_total, is_strong, trade_type

    def _can_open_strong_trade(self, risk_usdt: float) -> tuple[bool, str]:
        """
        Verifica se há margin disponível para abrir uma trade FORTE/FORTÍSSIMA.
        
        Retorna: (pode_abrir, motivo)
        """
        margin_available = self.exchange.get_available_margin()
        
        # Precisamos de margin buffer (mínimo 5% acima do risco)
        required_margin = risk_usdt * 1.05
        margin_threshold = 10.0  # Mínimo de 10 USDT de margin disponível
        
        if margin_available < margin_threshold:
            return False, f"Margin insuficiente: {margin_available:.2f} USDT (mín {margin_threshold:.2f})"
        
        if margin_available < required_margin:
            return False, f"Margin insuficiente para risco {risk_usdt:.2f}: disponível {margin_available:.2f}, requerido {required_margin:.2f}"
        
        return True, f"Margin OK: {margin_available:.2f} USDT"

    def _calculate_confidence_with_bonus(
        self,
        context_score: float,
        trigger_score: float,
        ai_confidence: float,
        context_count: int,
        trigger_count: int,
    ) -> float:
        """
        Calcula confiança final com bônus baseado em múltiplos contextos/gatilhos.
        
        Lógica:
        - Base: context_score(25%) + trigger_score(35%) + ai_confidence(40%)
        - Bônus contextos: (context_count - 1) * 0.08 (máx +0.16 para 3 contextos)
        - Bônus gatilhos: (trigger_count - 1) * 0.05 (máx +0.10 para 3 gatilhos)
        - Máximo final: 1.0
        
        Exemplos:
        - 1 contexto + 1 gatilho: base apenas
        - 2 contextos + 1 gatilho: base + 0.08
        - 1 contexto + 2 gatilhos: base + 0.05
        - 2 contextos + 2 gatilhos: base + 0.08 + 0.05 = base + 0.13
        """
        base_confidence = (
            context_score * 0.25 +
            trigger_score * 0.35 +
            ai_confidence * 0.40
        )
        
        # Bônus por múltiplos contextos (começa em 1)
        bonus_contexts = max(0, (context_count - 1)) * 0.08
        
        # Bônus por múltiplos gatilhos (começa em 1)
        bonus_triggers = max(0, (trigger_count - 1)) * 0.05
        
        final_confidence = min(base_confidence + bonus_contexts + bonus_triggers, 1.0)
        
        logger.debug(
            f"Confiança: {base_confidence:.3f} (base) "
            f"+ {bonus_contexts:.3f} (contextos) "
            f"+ {bonus_triggers:.3f} (gatilhos) "
            f"= {final_confidence:.3f}"
        )
        
        return final_confidence

    # ── Ciclo Principal ───────────────────────────────────────────────────────

    async def start(self):
        """Inicia o bot."""
        self.running = True
        logger.info("Bot iniciado.")

        # Inicializa equity diária
        wallet = self.exchange.get_wallet_balance()
        self.risk_manager.reset_daily(wallet["equity"])

        await self.telegram.notify_startup(self.cfg.SYMBOLS, self.cfg.BYBIT_TESTNET)

        while self.running:
            try:
                await self._main_loop()
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}", exc_info=True)
            await asyncio.sleep(self.cfg.SCAN_INTERVAL)

    async def _main_loop(self):
        """Uma iteração do loop principal."""
        wallet = self.exchange.get_wallet_balance()
        equity = wallet["equity"]
        available_margin = self.exchange.get_available_margin()

        # Reset diário
        await self._check_daily_reset(equity)

        # Verifica stop diário (pode ser ignorado para trades fortes)
        daily_stop_hit = self.risk_manager.check_daily_drawdown(equity)
        if daily_stop_hit:
            logger.warning("Stop diário atingido. Apenas trades fortes com margin serão executadas.")

        # Status periódico
        await self._maybe_send_status(wallet)

        # Monitora posições abertas
        await self._monitor_open_positions()

        # Conta trades abertas (para logs)
        open_trades = self.state.get_open_trades()
        base_trades = sum(1 for t in open_trades if not hasattr(t, 'trade_strength') or t.get('trade_strength') == 'BASE ✓')
        strong_trades = len(open_trades) - base_trades
        
        logger.debug(
            f"Trades: {len(open_trades)} total ({base_trades} BASE, {strong_trades} FORTE/FORTÍSSIMA) | "
            f"Margin: {available_margin:.2f} USDT"
        )

        # Escaneia oportunidades (sem bloqueio por limite de trades)
        for symbol in self.cfg.SYMBOLS:
            if not self.running:
                break
            
            # Pula símbolo com trade aberto
            if self.state.get_open_trade_by_symbol(symbol):
                continue
            
            try:
                # Determina se deve aceitar apenas trades fortes
                # Regras:
                # 1. Se daily stop atingido: apenas FORTE/FORTÍSSIMA
                # 2. Se trades >= MAX_OPEN_TRADES: apenas FORTE/FORTÍSSIMA
                # 3. Sempre verificar margin para trades FORTE/FORTÍSSIMA
                force_strong_only = daily_stop_hit or (len(open_trades) >= self.cfg.MAX_OPEN_TRADES)
                
                await self._analyze_symbol(
                    symbol=symbol,
                    equity=equity,
                    available_margin=available_margin,
                    force_strong_only=force_strong_only,
                )
                await asyncio.sleep(1)  # Rate limit básico
            except Exception as e:
                logger.error(f"Erro ao analisar {symbol}: {e}")

    # ── Análise de Símbolo ────────────────────────────────────────────────────

    async def _analyze_symbol(
        self,
        symbol: str,
        equity: float,
        available_margin: float,
        force_strong_only: bool = False,
    ):
        """
        Pipeline completo de análise para um símbolo.
        
        Se force_strong_only=True:
        - Rejeita trades BASE
        - Aceita trades FORTE/FORTÍSSIMA se houver margin
        """

        # 1. Busca dados OHLCV
        df_primary = self.exchange.get_klines(symbol, self.cfg.PRIMARY_TF, self.cfg.CANDLES_LOOKBACK)
        df_macro = self.exchange.get_klines(symbol, self.cfg.MACRO_TF, 100)
        df_micro = self.exchange.get_klines(symbol, self.cfg.MICRO_TF, 100)

        if df_primary.empty or len(df_primary) < 50:
            return

        # 2. Análise de contextos
        context_result = self.context_analyzer.analyze_all(df_primary, df_macro, df_micro, advanced=True)

        if context_result["active_count"] == 0:
            return
        
        # NOVO: Análises Avançadas (10 pontos)
        advanced_analysis = context_result.get("contexts", {}).get("advanced", {})
        advanced_bonus = advanced_analysis.get("bonuses", 0.0)
        logger.debug(f"{symbol} | Análises Avançadas: bonus={advanced_bonus:+.1%}")
        
        # NOVO: Análise Macro do Bitcoin (Dominância + Trend)
        btc_macro_analysis = {}
        btc_macro_bonus = 0.0
        if symbol != "BTCUSDT":  # Só analisar BTC macro para altcoins
            try:
                df_btc = self.exchange.get_klines("BTCUSDT", self.cfg.PRIMARY_TF, 100)
                if not df_btc.empty and len(df_btc) >= 50:
                    btc_macro_analysis = self.context_analyzer.analyze_btc_macro(df_btc, trigger_result.get("direction", "buy"))
                    btc_macro_bonus = btc_macro_analysis.get("total_bonus", 0.0)
                    logger.debug(f"{symbol} | BTC Macro: {btc_macro_analysis.get('recommendation', '')} (bonus={btc_macro_bonus:+.1%})")
            except Exception as e:
                logger.debug(f"{symbol} | Erro análise BTC macro: {e}")

        direction_bias = context_result["direction"]

        # 3. Gatilhos de entrada
        trigger_result = self.trigger_analyzer.analyze(df_primary, direction_bias)

        if not trigger_result["valid"]:
            return

        logger.info(
            f"{symbol} | Contextos: {context_result['active_contexts']} | "
            f"Gatilhos: {trigger_result['triggers']} | "
            f"Dir: {trigger_result['direction']}"
        )

        # 4. Dados de mercado para IA
        vol_data = analyze_volume(df_primary)
        ticker = self.exchange.get_ticker(symbol)
        current_price = float(ticker.get("lastPrice", df_primary["close"].iloc[-1]))

        market_data = {
            "price": current_price,
            "volume_spike": vol_data["is_spike"],
            "volume_delta_bullish": vol_data["delta_bullish"],
        }

        # 5. Análise de IA
        ai_result = self.ai_analyzer.analyze_opportunity(
            symbol=symbol,
            direction=trigger_result["direction"],
            context_data=context_result,
            trigger_data=trigger_result,
            market_data=market_data,
        )

        if ai_result["recommendation"] != "trade":
            logger.debug(f"{symbol} | IA recomenda skip: {ai_result['reasoning'][:80]}")
            return

        # Calcula bônus e classifica força da trade
        bonus_total, is_strong_trade, trade_type = self._calculate_bonus_metrics(
            context_count=context_result["active_count"],
            trigger_count=trigger_result["trigger_count"],
        )
        
        # Lógica de aceitação:
        # 1. Se force_strong_only=True (limite de trades OU daily stop):
        #    - Rejeita trades BASE
        #    - Aceita FORTE/FORTÍSSIMA APENAS com margin suficiente
        # 2. Se force_strong_only=False (condição normal):
        #    - Aceita trades BASE normalmente
        #    - Aceita FORTE/FORTÍSSIMA com margin suficiente
        
        if force_strong_only and not is_strong_trade:
            logger.debug(
                f"{symbol} | Trade BASE rejeitada: limites atingidos, apenas FORTE/FORTÍSSIMA"
            )
            return
        
        # Para trades FORTE/FORTÍSSIMA, sempre verificar margin
        if is_strong_trade:
            can_open, margin_msg = self._can_open_strong_trade(risk_usdt=0)  # Estima 0 por enquanto
            if not can_open:
                logger.debug(f"{symbol} | Trade {trade_type} rejeitada: {margin_msg}")
                return

        # Confiança final: média ponderada + bônus por múltiplos contextos/gatilhos + ANÁLISES AVANÇADAS
        confidence = self._calculate_confidence_with_bonus(
            context_score=context_result["context_score"],
            trigger_score=trigger_result["trigger_score"],
            ai_confidence=ai_result["confidence"],
            context_count=context_result["active_count"],
            trigger_count=trigger_result["trigger_count"],
        )
        
        # NOVO: Aplicar bonuses das análises avançadas
        confidence += advanced_bonus
        
        # NOVO: Aplicar bonuses da análise BTC macro
        confidence += btc_macro_bonus
        confidence = min(max(confidence, 0.0), 1.0)  # Limita entre 0 e 1
        
        # NOVO: 7. Validar com Plano Operacional Diário
        plan_validation = self.context_analyzer.validate_with_daily_plan(
            symbol=symbol,
            direction=trigger_result["direction"],
            entry=trigger_result["entry"]
        )
        if not plan_validation["is_valid"]:
            logger.warning(f"{symbol} | {plan_validation['reason']}")
            confidence -= plan_validation["penalty"]
        
        # NOVO: 11. Validação Demand/Supply Breakout (Sem demanda/Sem oferta)
        ds_bonus = 0.0
        ds_validation = None
        try:
            # Buscar último swing high/low como POI
            swings = find_swing_highs_lows(df_primary, lookback=10)
            if not swings["swing_high"].empty or not swings["swing_low"].empty:
                if trigger_result["direction"] == "sell":
                    # Rompeu POI de demanda (compra)
                    poi_level = df_primary[swings["swing_low"]]["low"].iloc[-1]
                else:
                    # Rompeu POI de oferta (venda)
                    poi_level = df_primary[swings["swing_high"]]["high"].iloc[-1]
                
                ds_validation = self.context_analyzer.validate_demand_supply_breakout(
                    df_primary, poi_level, trigger_result["direction"]
                )
                ds_bonus = ds_validation.get("bonus", 0.0)
                if ds_validation["is_legitimate"]:
                    logger.info(f"{symbol} | Validação D/S: {ds_validation['reason']} (bonus={ds_bonus:+.1%})")
                else:
                    logger.warning(f"{symbol} | Rompimento FAKE: {ds_validation['reason']} (penalidade={ds_bonus:+.1%})")
                confidence += ds_bonus
        except Exception as e:
            logger.debug(f"{symbol} | Erro na validação D/S: {e}")
        
        # NOVO: 12. Validação Order Block Legitimidade (OB é consolidação?)
        ob_bonus = 0.0
        ob_validation = None
        try:
            ob_validation = self.context_analyzer.validate_order_block_legitimacy(
                df_macro, df_primary, trigger_result["entry"], trigger_result["direction"]
            )
            ob_bonus = ob_validation.get("bonus", 0.0)
            if ob_validation["is_legitimate"]:
                logger.info(f"{symbol} | OB {ob_validation['validity_level']}: {ob_validation['reason']} (bonus={ob_bonus:+.1%})")
            else:
                logger.warning(f"{symbol} | OB FAKE: {ob_validation['reason']} (penalidade={ob_bonus:+.1%})")
            confidence += ob_bonus
        except Exception as e:
            logger.debug(f"{symbol} | Erro na validação OB: {e}")

        if confidence < self.cfg.MIN_CONFLUENCE_SCORE:
            logger.debug(f"{symbol} | Confiança insuficiente: {confidence:.2f}")
            return

        # 6. Gerenciamento de risco e montagem do trade
        trade_params = self.risk_manager.build_trade(
            symbol=symbol,
            side=trigger_result["direction"],
            entry=trigger_result["entry"],
            stop_loss=trigger_result["stop_loss"],
            take_profit=trigger_result["take_profit"],
            confidence=confidence,
            equity=equity,
        )

        if trade_params is None:
            return

        # Verificar margin disponível para trades FORTE/FORTÍSSIMA
        if is_strong_trade:
            can_open, margin_msg = self._can_open_strong_trade(risk_usdt=trade_params.risk_usdt)
            if not can_open:
                logger.warning(f"{symbol} | Trade {trade_type} rejeitada: {margin_msg}")
                return

        logger.info(
            f"[{trade_type}] {symbol} {trade_params.side} | "
            f"conf={confidence:.2f} ({advanced_bonus:+.1%} avançadas) | "
            f"lev={trade_params.leverage}x | RR=1:{trade_params.rr_ratio}"
        )

        # 7. Executa ordem
        await self._execute_trade(
            params=trade_params,
            context_result=context_result,
            trigger_result=trigger_result,
            ai_result=ai_result,
            trade_strength=trade_type,
            advanced_analysis=advanced_analysis,
            ds_validation=ds_validation,
            ob_validation=ob_validation,
        )

    # ── Execução de Trade ─────────────────────────────────────────────────────

    async def _execute_trade(self, params, context_result, trigger_result, ai_result, trade_strength: str = "BASE ✓", advanced_analysis: dict = None, ds_validation: dict = None, ob_validation: dict = None):
        """Executa a ordem na Bybit e registra o trade."""
        if advanced_analysis is None:
            advanced_analysis = {}
        if ds_validation is None:
            ds_validation = {}
        if ob_validation is None:
            ob_validation = {}
            
        order = self.exchange.place_market_order(
            symbol=params.symbol,
            side=params.side,
            qty=params.qty,
            stop_loss=params.stop_loss,
            take_profit=params.take_profit,
            leverage=params.leverage,
        )

        if not order:
            logger.error(f"Falha ao abrir ordem: {params.symbol}")
            return

        # Registra no state manager
        trade = self.state.open_trade(
            symbol=params.symbol,
            side=params.side,
            entry_price=params.entry_price,
            stop_loss=params.stop_loss,
            take_profit=params.take_profit,
            qty=params.qty,
            leverage=params.leverage,
            risk_usdt=params.risk_usdt,
            rr_ratio=params.rr_ratio,
            confidence=params.confidence,
            triggers=trigger_result["triggers"],
            contexts=context_result["active_contexts"],
            ai_reasoning=ai_result["reasoning"],
            order_id=order.get("order_id"),
        )

        # Notifica Telegram (com análises avançadas)
        advanced_desc = advanced_analysis.get("description", "")
        
        # Validações extras (D/S e OB)
        validation_desc = ""
        if ds_validation and ds_validation.get("is_legitimate"):
            validation_desc += f"✓ {ds_validation.get('reason', '')} | "
        if ob_validation and ob_validation.get("is_legitimate"):
            validation_desc += f"✓ OB {ob_validation.get('validity_level', '')} | "
        
        await self.telegram.notify_trade_open(
            symbol=params.symbol,
            side=params.side,
            entry=params.entry_price,
            stop_loss=params.stop_loss,
            take_profit=params.take_profit,
            qty=params.qty,
            leverage=params.leverage,
            risk_usdt=params.risk_usdt,
            rr_ratio=params.rr_ratio,
            confidence=params.confidence,
            triggers=trigger_result["triggers"],
            contexts=context_result["active_contexts"],
            ai_reasoning=ai_result["reasoning"],
            trade_strength=trade_strength,
            advanced_techniques=advanced_desc,
            validation_notes=validation_desc,
        )

    # ── Monitoramento de Posições ─────────────────────────────────────────────

    async def _monitor_open_positions(self):
        """Verifica posições abertas e detecta fechamentos."""
        open_trades = self.state.get_open_trades()
        if not open_trades:
            return

        # Agrupa posições da exchange por símbolo (pode haver múltiplas posições/ordens por símbolo)
        exchange_positions: dict[str, list] = {}
        for p in self.exchange.get_positions():
            sym = p.get("symbol")
            exchange_positions.setdefault(sym, []).append(p)

        for trade in open_trades:
            positions = exchange_positions.get(trade.symbol, [])

            # Se trade tem order_id registrado, checar especificamente por essa ordem
            matched = False
            if trade.order_id:
                for p in positions:
                    # possíveis chaves que contenham o id da ordem
                    for key in ("orderId", "order_id", "orderID", "id"):
                        if p.get(key) and str(p.get(key)) == str(trade.order_id):
                            matched = True
                            break
                    if matched:
                        break

            # Se não houver order_id ou não foi possível achar por id, considerar a posição existente se houver qualquer posição aberta no símbolo
            if not trade.order_id and positions:
                matched = True

            # Se não encontrou posição correspondente na exchange → foi fechada (SL ou TP)
            if not matched:
                await self._handle_closed_position(trade)

    async def _handle_closed_position(self, trade):
        """Trata posição fechada na exchange."""
        # Busca PnL real da Bybit
        closed_pnl_list = self.exchange.get_closed_pnl(symbol=trade.symbol, limit=5)
        exit_price = trade.take_profit  # fallback
        pnl = 0.0
        reason = "closed_sl"

        for item in closed_pnl_list:
            if item.get("symbol") == trade.symbol:
                pnl = float(item.get("closedPnl", 0))
                exit_price = float(item.get("avgExitPrice", trade.take_profit))
                reason = "closed_tp" if pnl > 0 else "closed_sl"
                break

        closed = self.state.close_trade(trade.id, exit_price, reason)
        if closed:
            await self.telegram.notify_trade_close(
                symbol=trade.symbol,
                side=trade.side,
                entry=trade.entry_price,
                exit_price=exit_price,
                pnl=pnl,
                pnl_pct=closed.pnl_pct or 0,
                reason="Take Profit ✅" if pnl > 0 else "Stop Loss ❌",
            )

    # ── Status e Utilidades ───────────────────────────────────────────────────

    async def _maybe_send_status(self, wallet: dict):
        """Envia status periódico."""
        now = datetime.now()
        if (
            self._last_status_time is None
            or (now - self._last_status_time).total_seconds() >= self.cfg.STATUS_INTERVAL
        ):
            stats = self.state.get_stats()
            daily_pnl = self.state.get_daily_pnl()
            await self.telegram.notify_status(
                equity=wallet["equity"],
                available=wallet["available"],
                unrealised_pnl=wallet["unrealised_pnl"],
                daily_pnl=daily_pnl,
                wins=stats["wins"],
                losses=stats["losses"],
                open_trades=stats["open_trades"],
            )
            self._last_status_time = now

    async def _check_daily_reset(self, equity: float):
        """Reseta contadores diários à meia-noite."""
        now = datetime.now()
        if now.hour == 0 and not self._daily_reset_done:
            self.risk_manager.reset_daily(equity)
            self._daily_reset_done = True
            logger.info("Reset diário realizado.")
        elif now.hour != 0:
            self._daily_reset_done = False

    async def shutdown(self):
        """Encerra o bot graciosamente."""
        self.running = False
        logger.info("Shutdown iniciado.")
        stats = self.state.get_stats()
        logger.info(f"Stats finais: {stats}")
