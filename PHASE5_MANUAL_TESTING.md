# Phase 5 Manual Testing Guide

This guide provides instructions for manually testing Phase 5 (Service Discovery & Monitoring) with a real NATS server.

## Prerequisites

1. **NATS Server**: Install and run NATS server locally
   ```powershell
   # Using Docker
   docker run -p 4222:4222 -p 8222:8222 nats:latest
   
   # Or using NATS CLI
   nats-server
   ```

2. **NATS CLI Tools**: Install for monitoring
   ```powershell
   # Using winget
   winget install synadia.nats
   
   # Or download from https://github.com/nats-io/natscli
   ```

3. **Configure kryten-llm**: Update `config.json` with service metadata
   ```json
   {
     "service_metadata": {
       "service_name": "llm",
       "service_version": "1.0.0",
       "heartbeat_interval_seconds": 10,
       "enable_service_discovery": true,
       "enable_heartbeats": true,
       "graceful_shutdown_timeout_seconds": 30
     }
   }
   ```

## Test Scenarios

### Test 1: Service Discovery on Startup

**Objective**: Verify service announces itself on startup.

**Steps**:
1. Start NATS monitoring in one terminal:
   ```powershell
   nats sub "kryten.service.>" --translate "jq ."
   ```

2. Start kryten-llm in another terminal:
   ```powershell
   cd D:\Devel\kryten-llm
   poetry run python -m kryten_llm
   ```

**Expected Results**:
- Discovery announcement on `kryten.service.discovery`:
  ```json
  {
    "service": "llm",
    "version": "1.0.0",
    "hostname": "<your-hostname>",
    "timestamp": "<iso-timestamp>"
  }
  ```
- Startup event on `kryten.lifecycle.llm.startup`:
  ```json
  {
    "service": "llm",
    "version": "1.0.0",
    "event": "startup",
    "timestamp": "<iso-timestamp>"
  }
  ```

### Test 2: Heartbeat Publishing

**Objective**: Verify heartbeats published at configured interval.

**Steps**:
1. Monitor heartbeat subject:
   ```powershell
   nats sub "kryten.service.heartbeat.llm" --translate "jq ."
   ```

2. Start kryten-llm (if not already running)

3. Observe heartbeats for at least 30 seconds

**Expected Results**:
- Heartbeat published every 10 seconds on `kryten.service.heartbeat.llm`
- Heartbeat payload includes:
  ```json
  {
    "service": "llm",
    "version": "1.0.0",
    "hostname": "<your-hostname>",
    "timestamp": "<iso-timestamp>",
    "uptime_seconds": <number>,
    "health": "healthy",
    "status": {
      "messages_processed": 0,
      "responses_sent": 0,
      "errors": 0,
      "llm_providers": {},
      "components": {
        "nats": {
          "healthy": true,
          "message": "Connected",
          "last_check": "<iso-timestamp>"
        },
        "rate_limiter": {
          "healthy": true,
          "message": "Initialized",
          "last_check": "<iso-timestamp>"
        },
        "spam_detector": {
          "healthy": true,
          "message": "Initialized",
          "last_check": "<iso-timestamp>"
        }
      }
    }
  }
  ```

### Test 3: Health State Changes

**Objective**: Verify heartbeat reflects health state changes.

**Steps**:
1. Monitor heartbeats:
   ```powershell
   nats sub "kryten.service.heartbeat.llm" --translate "jq .health"
   ```

2. Send chat messages to trigger LLM processing:
   ```powershell
   nats pub "kryten.chat.llm" '{"user":"testuser","message":"Hello","channel":"test"}'
   ```

3. Observe heartbeats showing provider status changes

**Expected Results**:
- Initial heartbeats show `"health": "healthy"`
- After LLM requests, `llm_providers` shows provider status:
  - `"ok"` for successful requests
  - `"failed"` for failed requests
- Health state changes to `"degraded"` if all providers fail
- Metrics increase: `messages_processed`, `responses_sent`, `errors`

### Test 4: Discovery Poll Re-registration

**Objective**: Verify service re-announces on discovery poll.

**Steps**:
1. Monitor discovery subject:
   ```powershell
   nats sub "kryten.service.discovery" --translate "jq ."
   ```

2. Publish discovery poll:
   ```powershell
   nats pub "kryten.service.discovery.poll" '{}'
   ```

**Expected Results**:
- Service publishes discovery announcement immediately after poll
- Announcement identical to startup announcement

### Test 5: Robot Startup Re-registration

**Objective**: Verify service re-announces on robot startup event.

**Steps**:
1. Monitor discovery subject:
   ```powershell
   nats sub "kryten.service.discovery" --translate "jq ."
   ```

2. Simulate robot startup:
   ```powershell
   nats pub "kryten.lifecycle.robot.startup" '{"service":"robot","event":"startup"}'
   ```

**Expected Results**:
- Service publishes discovery announcement after robot startup
- Logs show "Robot startup detected, re-registering service"

### Test 6: Graceful Shutdown

**Objective**: Verify graceful shutdown with final metrics.

**Steps**:
1. Monitor lifecycle events:
   ```powershell
   nats sub "kryten.lifecycle.llm.>" --translate "jq ."
   ```

2. Start kryten-llm and send some messages

3. Stop service gracefully (Ctrl+C or SIGTERM):
   ```powershell
   # In the kryten-llm terminal, press Ctrl+C
   ```

**Expected Results**:
- Shutdown event on `kryten.lifecycle.llm.shutdown`:
  ```json
  {
    "service": "llm",
    "version": "1.0.0",
    "event": "shutdown",
    "timestamp": "<iso-timestamp>",
    "reason": "<shutdown-reason>",
    "metrics": {
      "messages_processed": <number>,
      "responses_sent": <number>,
      "errors": <number>,
      "uptime_seconds": <number>
    }
  }
  ```
- Heartbeats stop immediately
- Log shows "Graceful shutdown initiated"

### Test 7: Group Restart Coordination

**Objective**: Verify delayed shutdown on group restart.

**Steps**:
1. Monitor shutdown events:
   ```powershell
   nats sub "kryten.lifecycle.llm.shutdown" --translate "jq ."
   ```

2. Publish group restart:
   ```powershell
   nats pub "kryten.lifecycle.group.restart" '{"group":"default","initiator":"robot","delay_seconds":10}'
   ```

3. Observe timing of shutdown

**Expected Results**:
- Log shows "Group restart requested, shutting down in 10 seconds"
- Service continues operating during delay
- Heartbeats continue during delay
- Shutdown event published after ~10 seconds
- Service stops after delay

### Test 8: Multiple Service Instances

**Objective**: Verify multiple instances can coexist.

**Steps**:
1. Monitor all service messages:
   ```powershell
   nats sub "kryten.>" --translate "jq ."
   ```

2. Start first instance with default config

3. Start second instance with different service name:
   ```json
   {
     "service_metadata": {
       "service_name": "llm-backup"
     }
   }
   ```

**Expected Results**:
- Each instance publishes to its own heartbeat subject:
  - `kryten.service.heartbeat.llm`
  - `kryten.service.heartbeat.llm-backup`
- Discovery announcements show different service names
- No conflicts or errors

### Test 9: Configuration Toggles

**Objective**: Verify service discovery and heartbeats can be disabled.

**Test 9a - Disable Service Discovery**:
1. Update config:
   ```json
   {
     "service_metadata": {
       "enable_service_discovery": false
     }
   }
   ```

2. Monitor discovery subject:
   ```powershell
   nats sub "kryten.service.discovery" --translate "jq ."
   ```

3. Start kryten-llm

**Expected Results**:
- NO discovery announcement
- Lifecycle events still published
- Heartbeats still published

**Test 9b - Disable Heartbeats**:
1. Update config:
   ```json
   {
     "service_metadata": {
       "enable_heartbeats": false
     }
   }
   ```

2. Monitor heartbeat subject:
   ```powershell
   nats sub "kryten.service.heartbeat.llm" --translate "jq ."
   ```

3. Start kryten-llm

**Expected Results**:
- NO heartbeats published
- Discovery announcement still works
- Lifecycle events still published

### Test 10: NATS Disconnection

**Objective**: Verify health state changes on NATS disconnect.

**Steps**:
1. Start kryten-llm with NATS running

2. Monitor heartbeats in separate terminal

3. Stop NATS server:
   ```powershell
   docker stop <nats-container-id>
   ```

4. Restart NATS after 30 seconds

**Expected Results**:
- Before disconnect: `"health": "healthy"`
- After disconnect: Health monitor detects NATS failure
- Service attempts reconnection per config
- After reconnect: `"health": "healthy"` resumes
- Heartbeats resume after reconnection

## Monitoring Tools

### View All Service Traffic
```powershell
nats sub "kryten.>" --translate "jq ."
```

### View Only Heartbeats
```powershell
nats sub "kryten.service.heartbeat.>" --translate "jq ."
```

### View Only Lifecycle Events
```powershell
nats sub "kryten.lifecycle.>" --translate "jq ."
```

### View Discovery Traffic
```powershell
nats sub "kryten.service.discovery*" --translate "jq ."
```

### Filter by Health State
```powershell
nats sub "kryten.service.heartbeat.llm" --translate "jq 'select(.health == \"degraded\")'"
```

### Count Messages per Minute
```powershell
nats sub "kryten.service.heartbeat.llm" | measure-object -Line
```

## Validation Checklist

- [ ] Discovery announcement on startup
- [ ] Lifecycle startup event published
- [ ] Heartbeats publishing at configured interval
- [ ] Heartbeat payload structure correct
- [ ] Health state reflects component status
- [ ] Provider status tracked (ok/failed/unknown)
- [ ] Metrics tracked correctly
- [ ] Re-registration on discovery poll works
- [ ] Re-registration on robot startup works
- [ ] Graceful shutdown publishes final metrics
- [ ] Heartbeats stop on shutdown
- [ ] Group restart delays shutdown correctly
- [ ] Service discovery can be disabled
- [ ] Heartbeats can be disabled
- [ ] Multiple instances coexist
- [ ] NATS reconnection works

## Troubleshooting

### No Messages Appearing

**Check NATS Connection**:
```powershell
nats server check
```

**Verify kryten-llm Connected**:
- Check logs for "NATS connected" message
- Check config has correct NATS URL

### Heartbeats Not Publishing

**Check Configuration**:
- Verify `enable_heartbeats: true`
- Check `heartbeat_interval_seconds` is reasonable (e.g., 10)

**Check Logs**:
- Look for "Heartbeat publisher started" message
- Look for any heartbeat errors

### Discovery Not Working

**Check Configuration**:
- Verify `enable_service_discovery: true`

**Check Logs**:
- Look for "Service registered" message
- Look for any publish errors

### Wrong Subject Names

**Verify Service Name**:
- Check `service_name` in config
- Subjects include service name: `kryten.service.heartbeat.<service_name>`

## Performance Metrics

During testing, observe:

1. **Heartbeat Timing**: Should be consistent at configured interval (±0.5s)
2. **Payload Size**: Typical heartbeat ~500-1000 bytes
3. **CPU Usage**: Heartbeat loop should be negligible (<1% CPU)
4. **Memory**: No memory leaks over 10+ minutes
5. **NATS Messages**: ~6 messages/minute for 10s heartbeat interval

## Success Criteria

Phase 5 is successfully implemented if:

1. ✅ All test scenarios pass
2. ✅ No errors in logs during normal operation
3. ✅ Heartbeats consistently published at configured interval
4. ✅ Health state accurately reflects service status
5. ✅ Metrics are accurate and complete
6. ✅ Graceful shutdown works cleanly
7. ✅ Configuration toggles work correctly
8. ✅ No performance degradation from Phase 5 features
9. ✅ All NATS subjects follow naming conventions
10. ✅ Service can run continuously for extended periods

## Next Steps

After completing manual testing:

1. Document any issues found
2. Update configuration examples if needed
3. Add monitoring dashboards (future phase)
4. Update user documentation
5. Create operational runbook
