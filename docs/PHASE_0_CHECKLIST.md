# Phase 0 Checklist - kryten-llm

Use this checklist to track Phase 0 completion.

## ✅ Pre-existing (No Action Needed)

- [x] Git repository initialized
- [x] `.gitignore` configured
- [x] `LICENSE` file (MIT)
- [x] `VERSION` file
- [x] `CHANGELOG.md`
- [x] `README.md` (needs updating)
- [x] `CONTRIBUTING.md`
- [x] `INSTALL.md`
- [x] `pyproject.toml` with Poetry
- [x] Development tools configured (pytest, black, ruff, mypy)
- [x] `kryten_llm/__init__.py` with version reading
- [x] `kryten_llm/__main__.py` with CLI and signal handling
- [x] `kryten_llm/config.py` with basic JSON loading
- [x] `kryten_llm/service.py` with NATS connection
- [x] `config.example.json` (basic, needs expansion)
- [x] Start/stop scripts (PowerShell and Bash)
- [x] Systemd service template (needs renaming)

## 🔨 Phase 0 Tasks

### 1. Directory Structure

- [ ] Create `kryten_llm/components/` directory
- [ ] Create `kryten_llm/models/` directory  
- [ ] Create `kryten_llm/utils/` directory
- [ ] Create `tests/` directory
- [ ] Ensure `logs/` directory or `.gitignore` entry

**Command**:
```bash
mkdir -p kryten_llm/{components,models,utils} tests logs
```

### 2. Dependencies

- [ ] Add `aiohttp ^3.9.0` to pyproject.toml
- [ ] Add `pydantic ^2.0.0` to pyproject.toml
- [ ] Add `pydantic-settings ^2.0.0` to pyproject.toml
- [ ] Run `poetry install` to update lock file

**Command**:
```bash
poetry add aiohttp pydantic pydantic-settings
```

### 3. Configuration Models

Create `kryten_llm/models/config.py`:

- [ ] `NatsConfig` class with URL and credentials
- [ ] `CyTubeConfig` class with domain, channel, username
- [ ] `PersonalityConfig` class with character details
- [ ] `LLMProvider` class with API configuration
- [ ] `Trigger` class with patterns and probabilities
- [ ] `RateLimits` class with cooldown settings
- [ ] `MessageProcessing` class with formatting rules
- [ ] `TestingConfig` class with dry-run settings
- [ ] `ContextConfig` class with history buffer size
- [ ] Main `Config` class inheriting from `BaseSettings`
- [ ] Environment variable support (prefix: `KRYTEN_LLM_`)

### 4. Event Models

Create `kryten_llm/models/events.py`:

- [ ] `TriggerResult` dataclass
- [ ] Other event types as needed

Create `kryten_llm/models/__init__.py`:

- [ ] Export all models

### 5. Enhanced Configuration File

Update `config.example.json` with sections:

- [ ] `nats` - Connection settings
- [ ] `cytube` - Channel connection
- [ ] `personality` - Bot character (Cynthia Rothrock defaults)
- [ ] `llm_providers` - Multiple providers with fallback
- [ ] `triggers` - Trigger words with probabilities and context
- [ ] `rate_limits` - Global, per-user, per-trigger settings
- [ ] `message_processing` - Max length, split settings
- [ ] `testing` - Dry-run, logging settings
- [ ] `context` - Chat history buffer size
- [ ] Add comments explaining each field

### 6. Update Existing Config Loader

Update `kryten_llm/config.py`:

- [ ] Import Pydantic models from `models/config.py`
- [ ] Replace dict-based Config with Pydantic `BaseSettings`
- [ ] Add `model_validate_json()` for JSON loading
- [ ] Add environment variable overrides
- [ ] Add validation error handling with helpful messages
- [ ] Add `validate()` method for `--validate-config` flag

### 7. CLI Enhancements

Update `kryten_llm/__main__.py`:

- [ ] Add `--dry-run` argument (store_true)
- [ ] Add `--validate-config` argument (store_true)
- [ ] If `--validate-config`, load config, validate, print result, exit
- [ ] Pass dry-run flag to service initialization
- [ ] Update help text for clarity

### 8. Service Updates

Update `kryten_llm/service.py`:

- [ ] Accept `dry_run` parameter in `__init__`
- [ ] Store `self.dry_run = dry_run`
- [ ] Log dry-run status at startup
- [ ] Update config loading to use new Pydantic models
- [ ] Add TODO comments for Phase 1 components

### 9. Documentation Updates

Update `README.md`:

- [ ] Remove "moderation" references
- [ ] Add LLM functionality description
- [ ] Document personality system
- [ ] Document trigger word system
- [ ] Document rate limiting
- [ ] Document dry-run mode
- [ ] Add configuration examples
- [ ] Update usage examples

### 10. File Naming Cleanup

- [ ] Rename `start-moderator.ps1` → `start-llm.ps1`
- [ ] Rename `start-moderator.sh` → `start-llm.sh`
- [ ] Rename `systemd/kryten-moderator.service` → `systemd/kryten-llm.service`
- [ ] Update service file contents for LLM service

### 11. Testing

- [ ] Create `tests/__init__.py`
- [ ] Create `tests/test_config.py` with basic config loading tests
- [ ] Create `tests/conftest.py` with pytest fixtures
- [ ] Run `poetry run pytest` to verify test setup

### 12. Validation

- [ ] Create a valid `config.json` from `config.example.json`
- [ ] Run `poetry run kryten-llm --config config.json --validate-config`
- [ ] Verify validation passes or shows helpful errors
- [ ] Run `poetry run kryten-llm --config config.json --dry-run`
- [ ] Verify service starts in dry-run mode
- [ ] Verify NATS connection works
- [ ] Verify logging is clear and informative

## 📋 Completion Criteria

Phase 0 is complete when:

- ✅ All directories created
- ✅ Dependencies installed
- ✅ Pydantic configuration models working
- ✅ Comprehensive `config.example.json` created
- ✅ CLI has `--dry-run` and `--validate-config` flags
- ✅ Configuration validation works with helpful errors
- ✅ Service starts in dry-run mode successfully
- ✅ README updated with LLM functionality
- ✅ Basic test structure in place
- ✅ File names consistent (no "moderator" references)

## ⏱️ Time Estimate

**Total Phase 0 effort**: 2-3 hours

- Directory structure: 5 minutes
- Dependencies: 5 minutes
- Configuration models: 45-60 minutes
- Enhanced config.example.json: 30 minutes
- Config loader updates: 20 minutes
- CLI enhancements: 15 minutes
- Service updates: 10 minutes
- README updates: 20 minutes
- File renaming: 10 minutes
- Test setup: 15 minutes
- Validation & testing: 15 minutes

## 🚀 Ready for Phase 1

Once Phase 0 is complete, you're ready to begin Phase 1 (Message Listening & Basic Response).

Phase 1 will build:
- `components/listener.py` - MessageListener
- `components/trigger_engine.py` - TriggerEngine (mentions only)
- `components/llm_manager.py` - LLMManager (single provider)
- `components/prompt_builder.py` - PromptBuilder
- `components/formatter.py` - ResponseFormatter

See `IMPLEMENTATION_PLAN.md` for Phase 1 details.
