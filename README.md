# Kryten LLM

AI-powered chat bot service for CyTube, part of the Kryten ecosystem.

## Features

- **Trigger-Based Responses**: Configurable trigger words with probabilities
- **Direct Mentions**: Responds when mentioned by name
- **LLM Integration**: Multiple LLM provider support (OpenAI, OpenRouter, local)
- **Rate Limiting**: Per-user, per-trigger, and global rate limits
- **Spam Detection**: Automatic spam detection with exponential backoff penalties
- **Context Awareness**: Tracks chat history and video context
- **Hot-Reload**: Reload configuration without restart (SIGHUP)
- **Service Discovery**: Publishes heartbeats and responds to discovery polls
- **Dry-Run Mode**: Test responses without sending to chat

## Requirements

- Python 3.10+
- Poetry
- NATS server
- kryten-py library

## Installation

### Using Poetry

```bash
# Install dependencies
poetry install

# Copy example configuration
cp config.example.json config.json

# Edit configuration with your settings
# See config.example.json for all options
```

### Using pip

```bash
pip install kryten-llm
```

## Configuration

Configuration is stored in a JSON file. See `config.example.json` for a complete example.

### Key Sections

| Section | Description |
|---------|-------------|
| `nats` | NATS connection settings |
| `channels` | CyTube channel connections |
| `personality` | Bot character and behavior |
| `llm_providers` | LLM API configurations |
| `triggers` | Trigger words with patterns and probabilities |
| `rate_limits` | Rate limiting rules |
| `spam_detection` | Spam detection settings |
| `testing` | Dry-run and logging options |

### Environment Variables

Override configuration with environment variables:

```bash
export OPENROUTER_API_KEY="your-api-key"
export KRYTEN_LLM_DRY_RUN="true"
```

## Usage

### Running the Service

```bash
# Using Poetry
poetry run kryten-llm --config config.json

# Direct Python execution
python -m kryten_llm --config config.json
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `--config PATH` | Path to configuration file (default: `config.json`) |
| `--log-level LEVEL` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `--dry-run` | Generate responses but don't send to chat |
| `--validate-config` | Validate configuration and exit |

### Validation Mode

Validate your configuration without starting the service:

```bash
poetry run kryten-llm --config config.json --validate-config
```

### Dry-Run Mode

Test responses without sending to chat:

```bash
poetry run kryten-llm --config config.json --dry-run
```

## Hot-Reload (POSIX)

Reload configuration without restarting the service:

```bash
# Send SIGHUP to reload configuration
kill -HUP $(pgrep -f kryten_llm)
```

Safe changes that can be hot-reloaded:
- Triggers (patterns, probabilities, enabled status)
- Rate limits
- Spam detection settings
- Personality configuration
- LLM provider settings

Unsafe changes (require restart):
- NATS connection settings
- Channel configuration
- Service name

## Production Deployment

### Systemd Service

Install the systemd service file:

```bash
# Copy service file
sudo cp kryten-llm.service /etc/systemd/system/

# Create config directory
sudo mkdir -p /etc/kryten-llm
sudo cp config.json /etc/kryten-llm/

# Create log directory
sudo mkdir -p /var/log/kryten-llm
sudo chown kryten:kryten /var/log/kryten-llm

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable kryten-llm
sudo systemctl start kryten-llm
```

### Service Management

```bash
# Check status
sudo systemctl status kryten-llm

# View logs
sudo journalctl -u kryten-llm -f

# Reload configuration
sudo systemctl reload kryten-llm

# Restart service
sudo systemctl restart kryten-llm
```

## Development

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=kryten_llm

# Run specific test file
poetry run pytest tests/test_trigger_engine.py -v
```

### Code Quality

```bash
# Linting
poetry run ruff check .

# Formatting
poetry run black .

# Type checking
poetry run mypy kryten_llm
```

## Architecture

The service processes messages through a pipeline:

```
Chat Message
    ↓
MessageListener (parse/filter)
    ↓
TriggerEngine (detect triggers/mentions)
    ↓
RateLimiter (check rate limits)
    ↓
SpamDetector (check spam)
    ↓
ContextManager (gather context)
    ↓
PromptBuilder (build LLM prompt)
    ↓
LLMManager (call LLM API)
    ↓
ResponseValidator (validate response)
    ↓
ResponseFormatter (format for chat)
    ↓
Send to Chat
```

## Service Discovery

The service publishes:

- **Startup event**: When service starts
- **Heartbeat**: Every 30s with health status
- **Shutdown event**: When service stops gracefully

Subscribe to service events:
- `kryten.lifecycle.llm.startup`
- `kryten.heartbeat.llm`
- `kryten.lifecycle.llm.shutdown`

## License

MIT License - see [LICENSE](LICENSE) for details.
