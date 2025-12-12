"""Main entry point for kryten-llm service."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Callable

from kryten_llm.components import ConfigReloader
from kryten_llm.config import load_config, validate_config_file
from kryten_llm.service import LLMService


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the service."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kryten LLM Service - AI-powered chat bot for CyTube"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.json"), help="Path to configuration file"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Generate responses but don't send to chat"
    )
    parser.add_argument(
        "--validate-config", action="store_true", help="Validate configuration file and exit"
    )
    return parser.parse_args()


async def main_async() -> None:
    """Main async entry point."""
    args = parse_args()
    setup_logging(args.log_level)

    logger = logging.getLogger(__name__)

    # Validate config mode
    if args.validate_config:
        logger.info(f"Validating configuration: {args.config}")
        is_valid, errors = validate_config_file(args.config)

        if is_valid:
            logger.info("✓ Configuration is valid")
            sys.exit(0)
        else:
            logger.error("✗ Configuration validation failed:")
            for error in errors:
                logger.error(f"  {error}")
            sys.exit(1)

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Override dry-run from CLI
    if args.dry_run:
        config.testing.dry_run = True
        config.testing.send_to_chat = False
        logger.info("Dry-run mode enabled via --dry-run flag")

    logger.info("Starting Kryten LLM Service")

    # Initialize service
    service = LLMService(config=config)

    # Phase 6: Setup config reloader for hot-reload support
    config_reloader = ConfigReloader(
        config_path=args.config, on_reload=service.reload_config, current_config=config
    )

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def signal_handler(sig: int) -> None:
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(service.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):

        def _make_handler(sig_num: int) -> Callable[[], None]:
            return lambda: signal_handler(sig_num)

        loop.add_signal_handler(sig, _make_handler(sig))

    # Phase 6: Setup SIGHUP handler for config reload (POSIX only)
    if hasattr(signal, "SIGHUP"):

        def sighup_handler() -> None:
            logger.info("Received SIGHUP, reloading configuration...")
            asyncio.create_task(config_reloader.reload_config())

        loop.add_signal_handler(signal.SIGHUP, sighup_handler)
        logger.info("SIGHUP handler registered for config hot-reload")

    try:
        await service.start()
        await service.wait_for_shutdown()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await service.stop()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
