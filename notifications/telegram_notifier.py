"""
Sistema de Notificações via Telegram
- Trade aberto
- Trade fechado
- Status da banca
"""

import asyncio
import aiohttp
from datetime import datetime
from typing import Optional, Dict
from utils.logger import setup_logger

logger = setup_logger("telegram")


class TelegramNotifier:
    """Envia notificações para o Telegram via Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.url = self.BASE_URL.format(token=token)

    async def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """Envia mensagem assíncrona."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram não configurado. Mensagem não enviada.")
            return False
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return True
                    else:
                        logger.error(f"Telegram erro HTTP {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Erro ao enviar Telegram: {e}")
            return False

    # ── Templates de Mensagem ─────────────────────────────────────────────────

    async def notify_trade_open(
        self,
        symbol: str,
        side: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        qty: float,
        leverage: int,
        risk_usdt: float,
        rr_ratio: float,
        confidence: float,
        triggers: list,
        contexts: list,
        ai_reasoning: str,
        trade_strength: str = "BASE ✓",
        advanced_techniques: str = "",
        validation_notes: str = "",
    ):
        emoji_side = "🟢📈" if side == "Buy" else "🔴📉"
        side_text = "LONG" if side == "Buy" else "SHORT"

        text = (
            f"{emoji_side} <b>TRADE ABERTO — {trade_strength}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 Par: <b>{symbol}</b>\n"
            f"📊 Direção: <b>{side_text}</b>\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Entrada: <code>{entry:.4f}</code>\n"
            f"🛑 Stop Loss: <code>{stop_loss:.4f}</code>\n"
            f"🎯 Take Profit: <code>{take_profit:.4f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Quantidade: <code>{qty}</code>\n"
            f"⚡ Alavancagem: <code>{leverage}x</code>\n"
            f"💸 Risco: <code>{risk_usdt:.2f} USDT</code>\n"
            f"📐 RR: <code>1:{rr_ratio:.1f}</code>\n"
            f"🤖 Confiança: <code>{confidence:.0%}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Gatilhos: <i>{', '.join(triggers)}</i>\n"
            f"🌐 Contextos: <i>{', '.join(contexts)}</i>\n"
            f"🧠 IA: <i>{ai_reasoning[:120]}...</i>\n"
        )
        if advanced_techniques:
            text += f"🔍 Técnicas: <i>{advanced_techniques[:180]}</i>\n"
        if validation_notes:
            text += f"🧪 Validações: <i>{validation_notes[:180]}</i>\n"
        await self.send(text)

    async def notify_trade_close(
        self,
        symbol: str,
        side: str,
        entry: float,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        reason: str,
    ):
        won = pnl > 0
        emoji = "✅💰" if won else "❌💸"
        result = "WIN" if won else "LOSS"
        sign = "+" if pnl > 0 else ""

        text = (
            f"{emoji} <b>TRADE FECHADO — {result}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 Par: <b>{symbol}</b>\n"
            f"📊 Direção: <b>{'LONG' if side == 'Buy' else 'SHORT'}</b>\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 Entrada: <code>{entry:.4f}</code>\n"
            f"📤 Saída: <code>{exit_price:.4f}</code>\n"
            f"💵 PnL: <code>{sign}{pnl:.2f} USDT ({sign}{pnl_pct:.2f}%)</code>\n"
            f"📋 Motivo: <i>{reason}</i>\n"
        )
        await self.send(text)

    async def notify_status(
        self,
        equity: float,
        available: float,
        unrealised_pnl: float,
        daily_pnl: float,
        wins: int,
        losses: int,
        open_trades: int,
        total_pnl: float = 0.0,
        last_7d_pnl: float = 0.0,
    ):
        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        sign = "+" if daily_pnl >= 0 else ""

        text = (
            f"📊 <b>STATUS DA BANCA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 Equity: <code>{equity:.2f} USDT</code>\n"
            f"💵 Disponível: <code>{available:.2f} USDT</code>\n"
            f"📂 Trades Abertos: <code>{open_trades}</code>\n"
            f"💹 PnL não realizado: <code>{unrealised_pnl:+.2f} USDT</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{pnl_emoji} PnL do Dia: <code>{sign}{daily_pnl:.2f} USDT</code>\n"
            f"📅 PnL 7d: <code>{last_7d_pnl:+.2f} USDT</code>\n"
            f"📚 PnL Total (fechados): <code>{total_pnl:+.2f} USDT</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Wins: <code>{wins}</code>\n"
            f"❌ Losses: <code>{losses}</code>\n"
            f"🎯 Win Rate: <code>{win_rate:.1f}%</code>\n"
            f"📈 Total Trades: <code>{total_trades}</code>\n"
        )
        await self.send(text)

    async def notify_daily_stop(self, equity: float, loss_pct: float):
        text = (
            f"🚨 <b>STOP DIÁRIO ATINGIDO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📉 Perda do dia: <code>{loss_pct:.2%}</code>\n"
            f"💼 Equity atual: <code>{equity:.2f} USDT</code>\n"
            f"⏸ Bot pausado até amanhã. Descanse e volte mais forte! 💪\n"
        )
        await self.send(text)

    async def notify_startup(self, symbols: list, testnet: bool):
        mode = "🧪 TESTNET" if testnet else "🔴 MAINNET"
        text = (
            f"🤖 <b>BOT INICIADO</b> — {mode}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"📋 Pares monitorados: <code>{len(symbols)}</code>\n"
            f"🎯 RR mínimo: <code>1:3</code>\n"
            f"💸 Risco por trade: <code>2%</code>\n"
            f"🛡 Stop diário: <code>6%</code>\n"
        )
        await self.send(text)
