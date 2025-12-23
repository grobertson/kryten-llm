# Deployment Guide

This document outlines the steps to deploy and update the Kryten LLM service.

## Prerequisites

- **Python**: 3.10 or higher
- **Ollama**: (Optional) For local model support
- **API Keys**: OpenAI, Anthropic, etc. (if using cloud providers)

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repo_url>
   cd kryten-llm
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. **Environment Variables:**
   Create a `.env` file in the root directory:
   ```env
   OPENAI_API_KEY=sk-...
   ANTHROPIC_API_KEY=sk-...
   # Add other provider keys as needed
   ```

2. **Service Configuration:**
   Edit `kryten_llm/config.yaml` to customize:
   - **Providers**: Enable/disable providers and set order.
   - **Validation**: Adjust strictness (length, repetition).
   - **System Prompt**: Define the persona.

## Running the Service

### Development Mode
```bash
python -m kryten_llm.main
```

### Production Mode
For production, it is recommended to run the service as a background process or using a process manager like systemd or Supervisor.

**Example Systemd Unit (`/etc/systemd/system/kryten-llm.service`):**
```ini
[Unit]
Description=Kryten LLM Service
After=network.target

[Service]
User=kryten
WorkingDirectory=/opt/kryten-llm
ExecStart=/opt/kryten-llm/.venv/bin/python -m kryten_llm.main
Restart=always
EnvironmentFile=/opt/kryten-llm/.env

[Install]
WantedBy=multi-user.target
```

## Updating

1. **Pull latest changes:**
   ```bash
   git pull origin main
   ```

2. **Update dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run tests:**
   ```bash
   python -m pytest
   ```

4. **Restart service:**
   ```bash
   # If using systemd
   sudo systemctl restart kryten-llm
   ```

## Verification

After deployment, verify operation:
1. Check logs for startup messages.
2. Trigger a media change event (if connected to CyTube) or send a test request.
3. Monitor for "Provider initialized" and "Response generated" logs.

## Performance Tuning

- **Local Models:** Ensure Ollama is using GPU acceleration.
- **Concurrency:** The service uses `asyncio`. Increase worker count if running behind a WSGI/ASGI server (if applicable in future).
- **Validation:** Disable `check_relevance` for faster response times if context checks are not critical.
