# Kryten-LLM Implementation Plan

## Overview

This document breaks down the implementation of kryten-llm into 6 phases, each building on the previous phase. Each phase is independently testable and delivers functional value.

## Phase 0: Project Setup (Est: 2-3 hours)

**Goal**: Enhance existing project structure for LLM functionality

### Already Complete ✓

The project already has:
- ✅ Project structure with `kryten_llm/` package
- ✅ `pyproject.toml` with Poetry, pytest, linting tools
- ✅ Basic `Config` class in `config.py` (JSON loading)
- ✅ `LLMService` skeleton in `service.py` with NATS connection
- ✅ `__main__.py` entry point with CLI args (`--config`, `--log-level`)
- ✅ Logging configured (stdout, configurable level)
- ✅ Signal handlers (SIGTERM, SIGINT)
- ✅ `config.example.json` (basic NATS config)
- ✅ README with usage instructions
- ✅ Systemd service template

### Tasks

1. **Create Missing Directory Structure**
   ```bash
   cd kryten-llm
   mkdir -p kryten_llm/{components,models,utils}
   mkdir -p tests logs
   ```

2. **Enhance Configuration Management**
   - Create `models/config.py` with comprehensive data classes:
     - `NatsConfig`, `CyTubeConfig`, `PersonalityConfig`
     - `LLMProvider`, `Trigger`, `RateLimits`
     - `MessageProcessing`, `TestingConfig`, `ContextConfig`
   - Update `config.py` to use Pydantic models
   - Support environment variable overrides (e.g., `KRYTEN_LLM_NATS_URL`)
   - Add validation with helpful error messages

3. **Create Comprehensive config.example.json**
   - Add all configuration sections from requirements
   - Include personality configuration (Cynthia Rothrock defaults)
   - Add LLM provider examples (local, OpenRouter, fallback)
   - Add trigger configurations with probabilities
   - Add rate limiting settings
   - Add testing/dry-run settings

4. **Add Missing CLI Arguments**
   - Add `--dry-run` flag to `__main__.py`
   - Add `--validate-config` flag to test configuration
   - Update help text with better descriptions

5. **Update Dependencies**
   - Add to `pyproject.toml`:
     - `aiohttp` (for LLM API calls)
     - `pydantic >= 2.0` (for configuration)
     - `pydantic-settings` (for env var support)

6. **Update README**
   - Add LLM-specific features and architecture
   - Document configuration options
   - Add dry-run mode documentation
   - Add trigger system overview

### Deliverables

- [ ] Directory structure created (`components/`, `models/`, `utils/`, `tests/`, `logs/`)
- [ ] Pydantic-based configuration models
- [ ] Enhanced `config.example.json` with all sections
- [ ] CLI with `--dry-run` and `--validate-config` flags
- [ ] Dependencies updated (`aiohttp`, `pydantic`, `pydantic-settings`)
- [ ] README updated with LLM functionality
- [ ] Configuration validation working with helpful errors

### Testing

```bash
# Install dependencies
poetry install

# Validate configuration
poetry run kryten-llm --config config.json --validate-config

# Test dry-run startup
poetry run kryten-llm --config config.json --dry-run

# Test normal startup (connects to NATS)
poetry run kryten-llm --config config.json
```

Expected:
- `--validate-config`: Shows configuration is valid or lists errors
- `--dry-run`: Service starts, connects to NATS, indicates dry-run mode
- Normal mode: Service starts and listens to chat messages

---

## Phase 1: Message Listening & Basic Response (Est: 6-8 hours)

**Goal**: Listen to chat messages and respond to direct mentions

### Tasks

1. **Implement MessageListener**
   - Subscribe to `kryten.events.cytube.{channel}.chatmsg`
   - Filter spam and command messages
   - Queue valid messages for processing

2. **Create Simple Trigger Engine**
   - Detect direct bot name mentions
   - Extract and clean message
   - Return TriggerResult

3. **Implement Basic LLM Manager**
   - Single provider support (OpenAI-compatible)
   - Simple API call with error handling
   - Timeout handling

4. **Create Prompt Builder**
   - Build system prompt from personality config
   - Build user prompt with message
   - No context yet (just basic prompt)

5. **Implement Response Formatter**
   - Basic message formatting
   - Split on length (no sentence detection yet)
   - Remove common LLM artifacts

6. **Connect Processing Loop**
   - Wire all components together
   - Process messages from queue
   - Send responses to chat (or log in dry-run)

### Deliverables

- [ ] Bot listens to chat messages
- [ ] Bot responds when mentioned by name
- [ ] Responses are formatted correctly
- [ ] Dry-run mode works
- [ ] Basic error handling

### Testing

Manual testing in CyTube:
1. Start bot in dry-run mode
2. Mention bot name in chat
3. Verify response is logged but not sent
4. Disable dry-run, verify response is sent
5. Test with long responses (>255 chars)

---

## Phase 2: Trigger Words & Rate Limiting (Est: 8-10 hours)

**Goal**: Add trigger word system and rate limiting

### Tasks

1. **Enhance Trigger Engine**
   - Load triggers from config
   - Match trigger patterns (case-insensitive)
   - Implement probability checking
   - Return trigger context

2. **Implement Rate Limiter**
   - Global rate limiting (messages per minute/hour)
   - Per-user rate limiting
   - Per-trigger cooldowns
   - Admin multipliers (rank-based)
   - Track state in memory (deques and dicts)

3. **Integrate Rate Limiting**
   - Check rate limits before LLM call
   - Record responses after sending
   - Log rate limit decisions

4. **Add Response Logger**
   - Log all responses to JSONL
   - Include trigger info, rate limit status
   - Support analysis and evaluation

5. **Enhanced Testing Tools**
   - Script to analyze response logs
   - Trigger statistics
   - Rate limit visualization

### Deliverables

- [ ] Trigger words work with probabilities
- [ ] Rate limiting enforced correctly
- [ ] Admin users get cooldown multipliers
- [ ] All responses logged to JSONL
- [ ] Analysis script for logs

### Testing

Test scenarios:
1. Trigger word with 100% probability → always responds
2. Trigger word with 10% probability → responds ~10% of time
3. Spam mentions → rate limiting kicks in
4. Admin mentions → reduced cooldowns
5. Multiple users → independent cooldowns
6. Trigger cooldowns → prevent spam of specific triggers

Expected log format:
```json
{
  "timestamp": "2025-01-20T10:30:00Z",
  "trigger_type": "trigger_word",
  "trigger_name": "toddy",
  "username": "user123",
  "input_message": "praise toddy!",
  "llm_response": "The divine energy flows!",
  "response_sent": true,
  "rate_limit_status": {"allowed": true}
}
```

---

## Phase 3: Multi-Provider LLM & Context (Est: 6-8 hours)

**Goal**: Support multiple LLM providers with context awareness

### Tasks

1. **Enhance LLM Manager**
   - Support multiple provider types (OpenRouter, local)
   - Provider selection by trigger
   - Automatic fallback on failure
   - Retry logic with exponential backoff

2. **Implement Context Manager**
   - Subscribe to video changes (`changemedia`)
   - Track current video metadata
   - Maintain chat history buffer (20-50 messages)
   - Provide context dict for prompts

3. **Enhance Prompt Builder**
   - Include current video in prompts
   - Add recent chat history
   - Add trigger-specific context
   - Support different prompt templates per trigger

4. **Add Movie Trivia Support (Optional)**
   - Basic IMDB integration (if time permits)
   - Or just use context from current video

### Deliverables

- [ ] Multiple LLM providers configured
- [ ] Fallback between providers works
- [ ] Current video included in prompts
- [ ] Chat history included in prompts
- [ ] Trigger context injected correctly

### Testing

Test scenarios:
1. Primary provider fails → fallback works
2. Video changes → context updated
3. Trigger with specific context → injected into prompt
4. Responses reference current video
5. Responses reference recent chat

---

## Phase 4: Intelligent Formatting & Validation (Est: 4-6 hours)

**Goal**: Improve response quality with smart formatting

### Tasks

1. **Enhance Response Formatter**
   - Split on sentence boundaries (not mid-word)
   - Add continuation indicators (...)
   - Remove self-referential phrases
   - Emoji limiting (optional)

2. **Add Response Validation**
   - Check response relevance
   - Detect repetitive responses
   - Filter inappropriate content
   - Validate length before sending

3. **Add Spam Detection**
   - Track recent messages per user
   - Detect identical message spam
   - Exponential backoff on rapid mentions

4. **Improve Error Handling**
   - Graceful degradation on LLM failures
   - Fallback responses (optional)
   - Better error logging with context

### Deliverables

- [ ] Messages split intelligently
- [ ] Self-references removed
- [ ] Response validation working
- [ ] Spam detection active
- [ ] Comprehensive error handling

### Testing

Test scenarios:
1. Long response → splits at sentence boundary
2. Response with "As Cynthia Rothrock, " → prefix removed
3. Repetitive message detection
4. User spams mentions → exponential backoff
5. All LLM providers fail → graceful error

---

## Phase 5: Service Discovery & Monitoring (Est: 3-4 hours)

**Goal**: Integrate with kryten ecosystem monitoring

### Tasks

1. **Implement Service Discovery**
   - Publish on `kryten.service.discovery` at startup
   - Include service metadata (name, version, features)

2. **Implement Heartbeats**
   - Publish on `kryten.service.heartbeat` every 5-10 seconds
   - Include health status (healthy/degraded/failing)
   - Report component statuses

3. **Add Health Checks**
   - NATS connection status
   - LLM provider availability
   - Rate limiter status
   - Overall health determination

4. **Handle Re-registration**
   - Listen to `kryten.lifecycle.robot.startup`
   - Listen to `kryten.service.discovery.poll`
   - Re-publish discovery on both events

5. **Add Lifecycle Events**
   - Publish `kryten.lifecycle.llm.startup`
   - Publish `kryten.lifecycle.llm.shutdown`
   - Publish `kryten.lifecycle.llm.connected`
   - Handle graceful shutdown

### Deliverables

- [ ] Service discovery working
- [ ] Heartbeats publishing
- [ ] Health status accurate
- [ ] Re-registration on robot restart
- [ ] Graceful shutdown

### Testing

```bash
# Monitor service discovery
nats sub "kryten.service.discovery"

# Monitor heartbeats
nats sub "kryten.service.heartbeat"

# Trigger re-registration
nats pub "kryten.service.discovery.poll" ""

# Check robot registry (if kryten-robot Phase 0 done)
nats kv get kryten_services llm
```

---

## Phase 6: Refinement & Optimization (Est: 4-6 hours)

**Goal**: Polish features and optimize performance

### Tasks

1. **Optimize Performance**
   - Profile hot paths
   - Optimize regex matching
   - Cache compiled patterns
   - Reduce memory usage

2. **Improve Configuration**
   - Hot-reload configuration (optional)
   - Validate config on load
   - Better error messages for config issues
   - Document all config options

3. **Enhanced Logging**
   - Structured logging with correlation IDs
   - Log LLM token usage
   - Performance metrics
   - Debug mode with verbose output

4. **Testing & Documentation**
   - Unit tests for critical components
   - Integration tests
   - User documentation
   - Deployment guide

5. **Production Readiness**
   - Systemd service file
   - Environment variable support
   - Secret management
   - Monitoring alerts

### Deliverables

- [ ] Performance optimized
- [ ] Configuration validated
- [ ] Comprehensive logging
- [ ] Test coverage >70%
- [ ] Production deployment guide

### Testing

- Run load tests with rapid messages
- Test configuration validation with invalid configs
- Verify logging includes all required fields
- Run unit tests with pytest
- Deploy to production environment

---

## Development Guidelines

### Code Quality

- Follow PEP 8 style guidelines
- Type hints for all functions
- Docstrings for public APIs
- Meaningful variable names
- Keep functions small and focused

### Testing Strategy

- Unit tests for components
- Integration tests for workflows
- Manual testing in CyTube channel
- Dry-run mode for safe testing
- Log analysis for evaluation

### Git Workflow

Each phase should be a separate branch:
```bash
git checkout -b phase-0-setup
# Complete phase 0
git commit -m "Phase 0: Project setup complete"
git checkout main
git merge phase-0-setup

git checkout -b phase-1-basic-response
# etc...
```

### Configuration Management

Test with multiple personalities:
```json
{
  "personalities": {
    "cynthia": { "character_name": "CynthiaRothbot", ... },
    "testing": { "character_name": "TestBot", ... }
  }
}
```

Switch personalities without code changes.

---

## Timeline Estimate

| Phase | Description | Hours | Dependencies |
|-------|-------------|-------|--------------|
| 0 | Project Setup (Enhanced) | 2-3 | None |
| 1 | Basic Response | 6-8 | Phase 0 |
| 2 | Triggers & Rate Limits | 8-10 | Phase 1 |
| 3 | Multi-Provider & Context | 6-8 | Phase 2 |
| 4 | Intelligent Formatting | 4-6 | Phase 3 |
| 5 | Service Discovery | 3-4 | Phase 4 |
| 6 | Refinement | 4-6 | Phase 5 |
| **Total** | | **33-45 hours** | |

**Estimated completion**: 4-6 full days of development

**Note**: Phase 0 reduced from 4-6 hours to 2-3 hours because project skeleton already exists with basic service structure, Poetry setup, CLI, and NATS connection working.

---

## Risk Mitigation

### Risk: LLM API Failures

**Mitigation**:
- Multiple provider support with fallback
- Retry logic with exponential backoff
- Graceful degradation
- Local provider as backup

### Risk: Rate Limiting Too Aggressive

**Mitigation**:
- Configurable rate limits
- Easy adjustment without code changes
- Response logging for tuning
- Admin exceptions for testing

### Risk: Bot Becomes Annoying

**Mitigation**:
- Low default trigger probabilities
- Conservative rate limits
- Dry-run mode for testing
- Easy disable via config

### Risk: Context Window Issues

**Mitigation**:
- Limit chat history buffer
- Truncate long video titles
- Monitor token usage
- Fallback to shorter prompts

---

## Success Metrics

After implementation, track:

1. **Technical Metrics**
   - Response time <5 seconds (p95)
   - LLM success rate >95%
   - Service uptime >99.9%
   - Error rate <1%

2. **Engagement Metrics**
   - Responses per hour
   - Trigger activations by type
   - User interactions per day
   - Repeated users

3. **Quality Metrics**
   - Response length distribution
   - Rate limit hits per hour
   - Admin interventions
   - User feedback (if available)

4. **Non-Annoyance Metrics**
   - Bot messages <5% of total chat
   - No user complaints
   - Trigger cooldowns respected
   - Rate limits effective

---

## Post-Launch

After initial deployment:

1. **Monitor for 1 week**
   - Collect response logs
   - Analyze trigger effectiveness
   - Identify annoying patterns

2. **Tune Configuration**
   - Adjust trigger probabilities
   - Refine rate limits
   - Update system prompts

3. **Evaluate Responses**
   - Review JSONL logs
   - Rate response quality
   - Identify failure patterns

4. **Plan Enhancements**
   - Additional triggers
   - Specialized providers
   - MCP tools integration
   - Advanced context awareness

---

## Future Enhancements (Post-MVP)

### Phase 7: Advanced Features
- MCP tools integration (movie lookup, web search)
- User stats integration
- Sentiment analysis
- Dynamic personality adjustment

### Phase 8: Learning & Adaptation
- Response quality feedback loop
- Automatic trigger probability tuning
- User preference learning
- Context-aware response style

### Phase 9: Multi-Channel Support
- Support multiple CyTube channels
- Channel-specific personalities
- Cross-channel context (optional)

### Phase 10: Advanced Analytics
- Metrics dashboard
- A/B testing framework
- Response quality scoring
- Engagement analytics

---

## Appendix: Quick Start Commands

```bash
# Phase 0: Setup (project already has Poetry setup)
cd kryten-llm

# Install dependencies using Poetry
poetry install

# Create config from example
cp config.example.json config.json
# Edit config.json with your settings (NATS URL, LLM providers, personality, etc.)

# Validate configuration
poetry run kryten-llm --config config.json --validate-config

# Test basic startup in dry-run mode
poetry run kryten-llm --config config.json --dry-run

# Phase 1: Test basic response
python -m kryten_llm --config config.json --dry-run
# Mention bot in chat, check logs

# Phase 2: Test triggers
# Edit config.json, set trigger probability to 1.0
python -m kryten_llm --config config.json --dry-run
# Say trigger word in chat, check logs

# Phase 3: Test multi-provider
# Add fallback provider to config
# Disable primary provider, verify fallback

# Phase 5: Test service discovery
nats sub "kryten.service.>"
python -m kryten_llm --config config.json

# Phase 6: Run tests
pytest tests/ -v

# Production deployment
sudo cp llm.service /etc/systemd/system/
sudo systemctl enable llm.service
sudo systemctl start llm.service
sudo systemctl status llm.service
```

---

## Notes

- **Dry-run mode is your friend**: Use it extensively during development
- **Log everything**: Response logs are invaluable for tuning
- **Start conservative**: Low trigger probabilities, high cooldowns
- **Test with real users**: Nothing beats real chat testing
- **Iterate quickly**: Small adjustments can have big impact

---

*This implementation plan provides a clear roadmap from setup to production deployment. Each phase builds on the previous, allowing for incremental testing and validation.*
