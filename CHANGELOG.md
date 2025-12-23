# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2025-12-23

### Fixed

- **Missing Changelog Entry**: Added missing changelog entry for version 0.3.0
  - Version 0.3.0 was released without proper changelog documentation
  - This patch ensures all releases are properly documented

## [0.3.0] - 2025-12-23

### Fixed

- **KV Store JSON Serialization**: Fixed JSON parsing error in trigger engine state persistence
  - Added `as_json=True` parameter to `kv_put` call for proper serialization
  - Ensures media state is correctly saved and loaded from NATS JetStream KV store
- **NATS Subject Construction**: Addressed manual subject construction findings from audit report
  - Updated heartbeat.py to use `normalize_token` for service name normalization
  - Added subject_builder import to service.py for future lifecycle subject improvements
- **Service Shutdown**: Fixed RuntimeError on Ctrl+C shutdown
  - Wrapped metrics server stop in try/except block to handle unregistration errors

### Changed

- **Version Management**: Updated to version 0.3.0
  - pyproject.toml is now the single source of truth for version
  - Version automatically synced to __init__.py via manage_version.py script
  - Config files properly ignored by git (config.json, config-*.json)

## [0.2.6] - 2025-12-22

### Added

- **Media Change Triggers**: Added support for triggering responses on significant media changes
  - Configurable duration threshold (default 30 mins)
  - Context-aware prompts with previous media and chat history
  - State persistence across restarts
- **Context-Aware Triggers**: Added recent chat history to trigger contexts
  - Efficient deque-based message buffering
  - Configurable history depth
- **Version Management**: Centralized versioning in `pyproject.toml`
  - Automated sync to `__init__.py`
  - Version consistency verification tests

## [0.2.4] - 2025-12-13

### Fixed

- **ChannelConfig Access**: Fixed dict-style access `channel_config["channel"]` to attribute access `channel_config.channel`
  - Matches kryten-py's Pydantic ChannelConfig model
- **Logging Conflict**: Renamed `message` to `original_message` in error handler's log extra
  - Fixes `KeyError: "Attempt to overwrite 'message' in LogRecord"` error

## [0.2.3] - 2025-12-13

### Changed

- Re-release of 0.2.2 with version sync fix included in package

## [0.2.2] - 2025-12-13

### Fixed

- **Shutdown Flush Timeout**: Updated kryten-py dependency to >=0.9.4
  - Fixes "nats: flush timeout" error on service shutdown
  - kryten-py 0.9.1+ includes proper timeout handling in disconnect()
- **Version Sync**: Service version now sourced from `__version__` in `__init__.py`
  - Version reported to kryten-robot stays in sync with package version
  - Config version is overridden at runtime to match package version
  - Simplified version handling (removed VERSION file reading)

## [0.2.1] - 2025-12-13

### Fixed

- **Robot Startup Re-registration**: Now subscribes to `kryten.lifecycle.robot.startup`
  - Service re-announces itself when kryten-robot restarts
  - Fixes "Heartbeat from unregistered service" warnings
  - Handler already existed but subscription was missing

## [0.2.0] - 2025-12-12

### Fixed

- **Windows Signal Handling**: Added platform detection for proper signal handler registration
  - Uses `signal.signal()` on Windows instead of `loop.add_signal_handler()`
  - Prevents `NotImplementedError` on Windows startup

- **ChannelConfig Access**: Fixed attribute access for channel configuration
  - Changed from dict-style `channel_config['domain']` to attribute access `channel_config.domain`
  - Matches kryten-py's Pydantic model structure

- **NATS Anti-Pattern Removal**: Removed all direct NATS client access
  - Replaced `self.client._nats.subscribe()` with `self.client.subscribe()`
  - Updated ContextManager to accept KrytenClient instead of raw NATS client
  - All NATS operations now go through kryten-py wrappers

### Changed

- **kryten-py Dependency**: Updated to require kryten-py >= 0.9.0
  - Uses new `subscribe()` method from KrytenClient

## [0.1.1] - Unreleased

### Added
- Initial skeleton implementation
- Basic service structure with KrytenClient integration
- Event handlers for `chatMsg` and `addUser` events
- Configuration management system
- CI workflow with Python 3.10, 3.11, and 3.12 support
- PyPI publishing workflow with trusted publishing
- Startup scripts for PowerShell and Bash
- Systemd service manifest
- Documentation structure
