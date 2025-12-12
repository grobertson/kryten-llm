"""Configuration hot-reload support for kryten-llm.

Phase 6: Implements SIGHUP-based configuration reload without service restart.

Example:
    >>> reloader = ConfigReloader(config_path, on_reload=service.reload_config)
    >>> reloader.setup_signal_handler()
    >>> # Later: send SIGHUP to reload config
    >>> # kill -HUP <pid>
"""

import asyncio
import logging
import signal
from pathlib import Path
from typing import Callable, Optional

from kryten_llm.models.config import LLMConfig


logger = logging.getLogger(__name__)


class ConfigReloader:
    """Handles configuration reload on SIGHUP signal.
    
    Implements hot-reload for configuration changes without restarting
    the service. Only safe changes are applied; unsafe changes (like
    NATS URL or channel changes) are logged as warnings.
    
    Safe changes that can be hot-reloaded:
        - Trigger configurations (probabilities, patterns, enabled status)
        - Rate limits (global, per-user, per-trigger)
        - Personality settings (prompts, response styles)
        - Spam detection settings
        - Logging configuration
        - LLM provider settings (API keys, models, temperatures)
    
    Unsafe changes (require restart):
        - NATS connection settings
        - Channel configuration
        - Service name changes
    
    Attributes:
        config_path: Path to the configuration file
        on_reload: Callback function called with new config after reload
        current_config: Currently active configuration
    """
    
    def __init__(
        self,
        config_path: Path | str,
        on_reload: Optional[Callable[["LLMConfig"], None]] = None,
        current_config: Optional[LLMConfig] = None
    ):
        """Initialize the config reloader.
        
        Args:
            config_path: Path to the configuration JSON file
            on_reload: Async callback to invoke after successful reload
            current_config: Current configuration for change detection
        """
        self.config_path = Path(config_path) if isinstance(config_path, str) else config_path
        self.on_reload = on_reload
        self.current_config = current_config
        self._reload_lock = asyncio.Lock()
        self._reload_in_progress = False
        
        logger.debug(f"ConfigReloader initialized for {self.config_path}")
    
    def setup_signal_handler(self) -> bool:
        """Register SIGHUP handler for config reload (POSIX only).
        
        On Windows, SIGHUP is not available, so this method logs a warning
        and returns False.
        
        Returns:
            True if signal handler was registered, False otherwise
        """
        if not hasattr(signal, 'SIGHUP'):
            logger.warning(
                "SIGHUP not available on this platform (Windows). "
                "Hot-reload via signal is disabled. Use API endpoint instead."
            )
            return False
        
        # Get the current event loop to schedule async reload
        try:
            loop = asyncio.get_running_loop()
            
            def sighup_handler():
                """Handle SIGHUP signal by scheduling config reload."""
                logger.info("Received SIGHUP signal, initiating config reload...")
                asyncio.create_task(self.reload_config())
            
            loop.add_signal_handler(signal.SIGHUP, sighup_handler)
            logger.info(f"SIGHUP handler registered for config reload from {self.config_path}")
            return True
            
        except RuntimeError:
            # No running event loop
            logger.warning("No running event loop, cannot register SIGHUP handler")
            return False
    
    async def reload_config(self) -> dict:
        """Reload configuration from file.
        
        Steps:
        1. Load new configuration file
        2. Validate the new configuration
        3. Detect safe vs unsafe changes
        4. Apply new configuration if valid
        5. Call on_reload callback with new config
        
        Returns:
            Dictionary with:
                - success (bool): Whether reload succeeded
                - message (str): Human-readable result
                - changes (dict): What changed (field: "old -> new")
                - warnings (list): Unsafe changes that require restart
                - errors (list): Validation errors if failed
        """
        if self._reload_in_progress:
            return {
                "success": False,
                "message": "Reload already in progress",
                "changes": {},
                "warnings": [],
                "errors": ["Another reload operation is in progress"]
            }
        
        async with self._reload_lock:
            self._reload_in_progress = True
            try:
                return await self._do_reload()
            finally:
                self._reload_in_progress = False
    
    async def _do_reload(self) -> dict:
        """Internal reload implementation."""
        changes: dict[str, str] = {}
        warnings: list[str] = []
        errors: list[str] = []
        
        # Step 1: Load new config file
        try:
            logger.info(f"Loading configuration from {self.config_path}")
            new_config = LLMConfig.load(self.config_path)
        except FileNotFoundError:
            error_msg = f"Configuration file not found: {self.config_path}"
            logger.error(error_msg)
            return {
                "success": False,
                "message": "Configuration file not found",
                "changes": {},
                "warnings": [],
                "errors": [error_msg]
            }
        except Exception as e:
            error_msg = f"Failed to load configuration: {e}"
            logger.error(error_msg, exc_info=True)
            return {
                "success": False,
                "message": "Configuration validation failed",
                "changes": {},
                "warnings": [],
                "errors": [error_msg]
            }
        
        # Step 2: Detect changes
        if self.current_config:
            changes, warnings = self._detect_changes(self.current_config, new_config)
        
        # Step 3: Check for unsafe changes
        if warnings:
            logger.warning(f"Unsafe changes detected (require restart): {warnings}")
        
        # Step 4: Apply new configuration
        old_config = self.current_config
        self.current_config = new_config
        
        # Step 5: Call callback
        if self.on_reload:
            try:
                if asyncio.iscoroutinefunction(self.on_reload):
                    await self.on_reload(new_config)
                else:
                    self.on_reload(new_config)
            except Exception as e:
                # Rollback on callback error
                self.current_config = old_config
                error_msg = f"Reload callback failed: {e}"
                logger.error(error_msg, exc_info=True)
                return {
                    "success": False,
                    "message": "Reload callback failed, configuration rolled back",
                    "changes": {},
                    "warnings": warnings,
                    "errors": [error_msg]
                }
        
        # Log success
        if changes:
            logger.info(f"Configuration reloaded with changes: {changes}")
        else:
            logger.info("Configuration reloaded (no changes detected)")
        
        return {
            "success": True,
            "message": "Configuration reloaded successfully",
            "changes": changes,
            "warnings": warnings,
            "errors": []
        }
    
    def _detect_changes(
        self, 
        old_config: LLMConfig, 
        new_config: LLMConfig
    ) -> tuple[dict[str, str], list[str]]:
        """Detect changes between old and new configuration.
        
        Args:
            old_config: Previous configuration
            new_config: New configuration
            
        Returns:
            Tuple of (changes dict, warnings list)
        """
        changes: dict[str, str] = {}
        warnings: list[str] = []
        
        # Check unsafe changes (require restart)
        if old_config.nats.url != new_config.nats.url:
            warnings.append(
                f"nats.url changed ({old_config.nats.url} -> {new_config.nats.url}), "
                "requires restart to apply"
            )
        
        old_channels = old_config.channels
        new_channels = new_config.channels
        if old_channels != new_channels:
            warnings.append(
                "channels configuration changed, requires restart to apply"
            )
        
        if old_config.service_metadata.service_name != new_config.service_metadata.service_name:
            warnings.append(
                f"service_name changed, requires restart to apply"
            )
        
        # Check safe changes
        if old_config.default_provider != new_config.default_provider:
            changes["default_provider"] = f"{old_config.default_provider} -> {new_config.default_provider}"
        
        # Trigger changes
        old_trigger_names = {t.name for t in old_config.triggers}
        new_trigger_names = {t.name for t in new_config.triggers}
        
        added_triggers = new_trigger_names - old_trigger_names
        removed_triggers = old_trigger_names - new_trigger_names
        
        if added_triggers:
            changes["triggers_added"] = ", ".join(sorted(added_triggers))
        if removed_triggers:
            changes["triggers_removed"] = ", ".join(sorted(removed_triggers))
        
        # Rate limit changes
        if old_config.rate_limits != new_config.rate_limits:
            changes["rate_limits"] = "updated"
        
        # Spam detection changes
        if old_config.spam_detection != new_config.spam_detection:
            changes["spam_detection"] = "updated"
        
        # Personality changes
        if old_config.personality != new_config.personality:
            changes["personality"] = "updated"
        
        # LLM provider changes
        old_providers = set(old_config.llm_providers.keys())
        new_providers = set(new_config.llm_providers.keys())
        
        if old_providers != new_providers:
            added = new_providers - old_providers
            removed = old_providers - new_providers
            if added:
                changes["llm_providers_added"] = ", ".join(sorted(added))
            if removed:
                changes["llm_providers_removed"] = ", ".join(sorted(removed))
        
        return changes, warnings
