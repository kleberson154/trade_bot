"""
AI Trade Bot - Bybit Futures
Entry point principal do bot
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

from core.bot import TradingBot
from utils.logger import setup_logger
from utils.config import Config

logger = setup_logger("main")


async def main():
    """Função principal do bot"""
    config = Config()

    logger.info("=" * 60)
    logger.info("  AI TRADE BOT - Bybit Futures")
    logger.info("  Versão 1.0.0")
    logger.info("=" * 60)

    bot = TradingBot(config)

    # Handler para shutdown gracioso
    def signal_handler(sig, frame):
        logger.info("Sinal de shutdown recebido. Encerrando bot...")
        asyncio.create_task(bot.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário.")
    except Exception as e:
        logger.error(f"Erro fatal: {e}", exc_info=True)
    finally:
        await bot.shutdown()
        logger.info("Bot encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
