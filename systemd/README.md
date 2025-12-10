# Systemd Service Files

This directory contains systemd service unit files for running kryten-llm as a system service.

## Installation

1. Copy the service file to systemd directory:
```bash
sudo cp systemd/kryten-llm.service /etc/systemd/system/
```

2. Reload systemd daemon:
```bash
sudo systemctl daemon-reload
```

3. Enable the service to start on boot:
```bash
sudo systemctl enable kryten-llm
```

4. Start the service:
```bash
sudo systemctl start kryten-llm
```

## Service Management

Check service status:
```bash
sudo systemctl status kryten-llm
```

View logs:
```bash
sudo journalctl -u kryten-llm -f
```

Stop the service:
```bash
sudo systemctl stop kryten-llm
```

Restart the service:
```bash
sudo systemctl restart kryten-llm
```

## Configuration

The service expects:
- Installation directory: `/opt/kryten-llm`
- Configuration file: `/etc/kryten/llm/config.json`
- User/Group: `kryten`
- Log directory: `/var/log/kryten-llm`

Make sure to create these directories and the kryten user before starting the service.
