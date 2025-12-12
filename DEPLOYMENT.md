# Kryten LLM Production Deployment Guide

This guide covers deploying kryten-llm to a production Linux server.

## Prerequisites

- Linux server (Ubuntu 22.04+ or similar)
- Python 3.10+
- NATS server (running or accessible)
- kryten-py library installed
- LLM API access (OpenRouter, local LLM, etc.)

## Server Setup

### Create Service User

```bash
# Create kryten user with no login shell
sudo useradd -r -s /bin/false kryten

# Create directories
sudo mkdir -p /opt/kryten-llm
sudo mkdir -p /etc/kryten-llm
sudo mkdir -p /var/log/kryten-llm

# Set ownership
sudo chown -R kryten:kryten /opt/kryten-llm
sudo chown -R kryten:kryten /var/log/kryten-llm
```

### Install Application

```bash
# Clone or copy application
cd /opt/kryten-llm
sudo -u kryten git clone https://github.com/your-org/kryten-llm.git .

# Create virtual environment
sudo -u kryten python3 -m venv .venv

# Install dependencies
sudo -u kryten .venv/bin/pip install -e .
sudo -u kryten .venv/bin/pip install kryten-py
```

## Configuration

### Create Configuration File

```bash
# Copy example config
sudo cp /opt/kryten-llm/config.example.json /etc/kryten-llm/config.json

# Edit configuration
sudo nano /etc/kryten-llm/config.json
```

### Critical Configuration Settings

Update these settings for production:

```json
{
  "nats": {
    "url": "nats://your-nats-server:4222"
  },
  "channels": [
    {
      "domain": "cytu.be",
      "channel": "your-channel",
      "username": "YourBotName",
      "password": "your-password"
    }
  ],
  "testing": {
    "dry_run": false,
    "send_to_chat": true
  },
  "service_metadata": {
    "service_name": "kryten-llm",
    "enable_service_discovery": true
  }
}
```

### Environment File for Secrets

Create an environment file for API keys:

```bash
sudo nano /etc/kryten-llm/environment
```

Content:

```bash
OPENROUTER_API_KEY=sk-or-v1-your-api-key
# Add other secrets as needed
```

Secure the file:

```bash
sudo chmod 600 /etc/kryten-llm/environment
sudo chown kryten:kryten /etc/kryten-llm/environment
```

### Validate Configuration

```bash
sudo -u kryten /opt/kryten-llm/.venv/bin/python -m kryten_llm \
  --config /etc/kryten-llm/config.json \
  --validate-config
```

## Systemd Service

### Install Service File

```bash
sudo cp /opt/kryten-llm/kryten-llm.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### Enable and Start

```bash
# Enable on boot
sudo systemctl enable kryten-llm

# Start service
sudo systemctl start kryten-llm

# Check status
sudo systemctl status kryten-llm
```

### View Logs

```bash
# Follow live logs
sudo journalctl -u kryten-llm -f

# Last 100 lines
sudo journalctl -u kryten-llm -n 100

# Logs since boot
sudo journalctl -u kryten-llm -b
```

## Operations

### Reload Configuration

After editing `/etc/kryten-llm/config.json`:

```bash
# Trigger hot-reload via systemd
sudo systemctl reload kryten-llm

# Or send SIGHUP directly
sudo kill -HUP $(pgrep -f kryten_llm)
```

### Restart Service

```bash
sudo systemctl restart kryten-llm
```

### Stop Service

```bash
sudo systemctl stop kryten-llm
```

## Monitoring

### Health Checks

The service publishes heartbeats to NATS:

```
Subject: kryten.heartbeat.llm
```

Heartbeat payload includes:
- `uptime_seconds`: Service uptime
- `messages_processed`: Total messages processed
- `responses_sent`: Total responses sent
- `health`: Component health status

### Logs

Application logs go to:
- Systemd journal: `journalctl -u kryten-llm`
- Response logs: `/var/log/kryten-llm/responses.jsonl` (if configured)

### Metrics

Monitor these metrics:
- Service uptime
- Message processing rate
- LLM response latency
- Rate limit triggers
- Spam detection events

## Troubleshooting

### Service Won't Start

Check logs:

```bash
sudo journalctl -u kryten-llm -n 50
```

Common issues:
- Invalid configuration: Run `--validate-config`
- Missing API keys: Check `/etc/kryten-llm/environment`
- NATS not reachable: Check NATS server status
- Permission issues: Verify file ownership

### No Responses Being Sent

1. Check dry-run mode is disabled:
   ```json
   "testing": { "dry_run": false, "send_to_chat": true }
   ```

2. Check rate limits aren't blocking:
   - View logs for rate limit messages
   - Temporarily increase limits for testing

3. Verify triggers are enabled:
   - Check trigger `"enabled": true`
   - Check trigger probability > 0

### LLM Errors

1. Check API key is set correctly
2. Verify provider URL is accessible
3. Check model name is valid
4. Review LLM response in logs

### Hot-Reload Not Working

1. Check SIGHUP is being received:
   ```bash
   sudo journalctl -u kryten-llm | grep SIGHUP
   ```

2. Check for unsafe changes (require restart):
   - NATS URL
   - Channel configuration
   - Service name

## Security Considerations

### File Permissions

```bash
# Config file
sudo chmod 640 /etc/kryten-llm/config.json
sudo chown root:kryten /etc/kryten-llm/config.json

# Environment file (secrets)
sudo chmod 600 /etc/kryten-llm/environment
sudo chown kryten:kryten /etc/kryten-llm/environment
```

### Network

- Use TLS for NATS connections in production
- Consider firewall rules for NATS port
- Use environment variables for API keys

### Updates

```bash
# Stop service
sudo systemctl stop kryten-llm

# Update code
cd /opt/kryten-llm
sudo -u kryten git pull

# Update dependencies
sudo -u kryten .venv/bin/pip install -e .

# Validate new config schema
sudo -u kryten .venv/bin/python -m kryten_llm --validate-config

# Start service
sudo systemctl start kryten-llm
```

## Backup

### Configuration Backup

```bash
sudo cp /etc/kryten-llm/config.json /backup/kryten-llm-config-$(date +%Y%m%d).json
```

### Log Rotation

Create `/etc/logrotate.d/kryten-llm`:

```
/var/log/kryten-llm/*.jsonl {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 640 kryten kryten
}
```

## Quick Reference

| Action | Command |
|--------|---------|
| Start service | `sudo systemctl start kryten-llm` |
| Stop service | `sudo systemctl stop kryten-llm` |
| Restart service | `sudo systemctl restart kryten-llm` |
| Reload config | `sudo systemctl reload kryten-llm` |
| View status | `sudo systemctl status kryten-llm` |
| View logs | `sudo journalctl -u kryten-llm -f` |
| Validate config | `/opt/kryten-llm/.venv/bin/python -m kryten_llm --validate-config` |
