# Installation Guide

## Prerequisites

- Python 3.10 or higher
- Poetry (Python package manager)
- NATS server (running and accessible)
- Git

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/grobertson/kryten-llm.git
cd kryten-llm
```

### 2. Install Dependencies

```bash
poetry install
```

### 3. Configure the Service

Copy the example configuration:

```bash
cp config.example.json config.json
```

Edit `config.json` with your settings:

```json
{
  "nats_url": "nats://localhost:4222",
  "nats_subject_prefix": "cytube",
  "service_name": "kryten-llm"
}
```

### 4. Run the Service

**Development mode:**

```bash
poetry run kryten-llm --config config.json --log-level DEBUG
```

**Using startup script (PowerShell):**

```powershell
.\start-llm.ps1
```

**Using startup script (Bash):**

```bash
./start-llm.sh
```

## Production Installation

### System User Setup

Create a dedicated system user:

```bash
sudo useradd -r -s /bin/false -d /opt/kryten-llm kryten
```

### Installation Directory

```bash
sudo mkdir -p /opt/kryten-llm
sudo chown kryten:kryten /opt/kryten-llm
```

### Configuration Directory

```bash
sudo mkdir -p /etc/kryten/llm
sudo chown kryten:kryten /etc/kryten/llm
sudo cp config.example.json /etc/kryten/llm/config.json
sudo chown kryten:kryten /etc/kryten/llm/config.json
sudo chmod 600 /etc/kryten/llm/config.json
```

Edit the configuration:

```bash
sudo nano /etc/kryten/llm/config.json
```

### Log Directory

```bash
sudo mkdir -p /var/log/kryten-llm
sudo chown kryten:kryten /var/log/kryten-llm
```

### Install Application

```bash
cd /opt/kryten-llm
sudo -u kryten git clone https://github.com/grobertson/kryten-llm.git .
sudo -u kryten poetry install --no-dev
```

### Systemd Service

Install the systemd service:

```bash
sudo cp systemd/kryten-llm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kryten-llm
sudo systemctl start kryten-llm
```

Check service status:

```bash
sudo systemctl status kryten-llm
sudo journalctl -u kryten-llm -f
```

## Updating

### Development

```bash
git pull
poetry install
```

### Production

```bash
cd /opt/kryten-llm
sudo systemctl stop kryten-llm
sudo -u kryten git pull
sudo -u kryten poetry install --no-dev
sudo systemctl start kryten-llm
```

## Troubleshooting

### Check NATS Connection

Ensure NATS server is running:

```bash
# Check if NATS is listening
netstat -tuln | grep 4222
```

### View Logs

```bash
# Systemd service logs
sudo journalctl -u kryten-llm -f

# Check for errors
sudo journalctl -u kryten-llm --since "1 hour ago" | grep -i error
```

### Test Configuration

```bash
# Validate JSON syntax
python -m json.tool config.json

# Test connection manually
poetry run kryten-llm --config config.json --log-level DEBUG
```

### Permissions Issues

Ensure correct ownership:

```bash
sudo chown -R kryten:kryten /opt/kryten-llm
sudo chown -R kryten:kryten /etc/kryten/llm
sudo chown -R kryten:kryten /var/log/kryten-llm
```

## Uninstalling

### Stop and Disable Service

```bash
sudo systemctl stop kryten-llm
sudo systemctl disable kryten-llm
sudo rm /etc/systemd/system/kryten-llm.service
sudo systemctl daemon-reload
```

### Remove Files

```bash
sudo rm -rf /opt/kryten-llm
sudo rm -rf /etc/kryten/llm
sudo rm -rf /var/log/kryten-llm
```

### Remove User

```bash
sudo userdel kryten
```
