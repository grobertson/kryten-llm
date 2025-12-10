"# Kryten LLM

Kryten LLM integration service - provides AI chat responses and interactions for CyTube.

## Features

- Real-time chat message monitoring
- User tracking and management
- Event-driven architecture using NATS
- Extensible moderation rules

## Installation

### Prerequisites

- Python 3.10 or higher
- Poetry
- NATS server running
- kryten-py library

### Setup

1. Install dependencies:
```bash
poetry install
```

2. Copy the example configuration:
```bash
cp config.example.json config.json
```

3. Edit `config.json` with your settings:
```json
{
  "nats_url": "nats://localhost:4222",
  "nats_subject_prefix": "cytube",
  "service_name": "kryten-llm"
}
```

## Usage

### Running the Service

Using Poetry:
```bash
poetry run kryten-llm --config config.json
```

Using the startup script (PowerShell):
```powershell
.\start-llm.ps1
```

Using the startup script (Bash):
```bash
./start-llm.sh
```

### Command Line Options

- `--config PATH`: Path to configuration file (default: `/etc/kryten/llm/config.json`)
- `--log-level LEVEL`: Set logging level (DEBUG, INFO, WARNING, ERROR)

## Event Handling

The service currently listens for:

- **chatMsg**: Chat messages to generate AI responses

## Development

### Running Tests

```bash
poetry run pytest
```

### Linting

```bash
poetry run ruff check .
```

### Formatting

```bash
poetry run black .
```

## License

MIT License - see LICENSE file for details
" 
