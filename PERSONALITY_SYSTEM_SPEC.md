# Dynamic Personality and Configuration Management System

**Version:** 1.0.0  
**Date:** 2026-02-05  
**Status:** Draft  
**Target Service:** kryten-llm

---

## Overview

Implement a dynamic personality management system that allows real-time configuration updates, externalized personality profiles, dynamic emote integration from JetStream KV store, and humanized response timing.

### Goals

- Separate personality configuration from service configuration
- Enable hot-reload of personality without service restart
- Integrate dynamic emote lists from kryten-robot's JetStream store
- Add configurable response delays for human-like timing
- Provide PM-based admin commands for live tuning

---

## Features Summary

| ID | Feature | Priority | Dependencies |
|----|---------|----------|--------------|
| FEAT-001 | Externalized Personality Configuration | High | None |
| FEAT-002 | Dynamic Emote List Integration | High | FEAT-001 |
| FEAT-003 | Hot Reload via PM Commands | Medium | FEAT-001 |
| FEAT-004 | Humanized Response Timing | Medium | None |

---

## FEAT-001: Externalized Personality Configuration

### Description

Move all bot personality settings from the main `config.json` into a separate YAML file. This allows rapid iteration on personality without touching service configuration, and enables version control of different personality profiles.

### Requirements

#### REQ-001-01: Create separate YAML file format for personality profiles

**Acceptance Criteria:**
- Personality file is valid YAML
- Contains all current personality settings from config.json
- Includes template content inline or as references
- Supports multiple profiles (e.g., `personality-cynthia.yaml`)

#### REQ-001-02: Main config references personality file by path

**Acceptance Criteria:**
- Main config has `personality_file` setting
- Service loads personality from specified file on startup
- Falls back to inline config if file not found (backwards compatible)

#### REQ-001-03: Personality file contains template content

**Acceptance Criteria:**
- System prompt template included in personality file
- Trigger templates included in personality file
- Media change template included in personality file
- Templates support Jinja2 syntax as before

#### REQ-001-04: Support versioning and profiles

**Acceptance Criteria:**
- Personality files can be named/organized by version
- Easy to switch between profiles by changing config reference
- Example profiles provided (conservative, energetic, etc.)

### Configuration

#### Main Config Changes

```json
{
  "personality_file": "personalities/cynthia-rothbot-v1.yaml"
  // Fallback inline config still supported for backwards compatibility
}
```

#### Personality File Schema

**File Format:** YAML  
**Location:** `personalities/`  
**Naming Convention:** `{character}-{variant}-v{version}.yaml`

**Structure:**

```yaml
metadata:
  character_name: string
  character_description: string
  version: string
  author: string (optional)
  created_date: ISO date
  last_modified: ISO date

personality:
  traits: array of strings
  expertise: array of strings
  response_style: string
  name_variations: array of strings

templates:
  system_prompt: string (Jinja2 template)
  default_trigger: string (Jinja2 template)
  media_change: string (Jinja2 template)

context_hints:
  description: Optional context information for LLM
  example: array of example responses
```

### Example Personality File

**File:** `personalities/cynthia-rothbot-v1.yaml`

```yaml
metadata:
  character_name: CynthiaRothbot
  character_description: legendary martial artist and actress Cynthia Rothrock
  version: "1.0"
  created_date: "2026-02-05"
  last_modified: "2026-02-05"

personality:
  traits:
    - confident
    - action-oriented
    - pithy
    - martial arts expert
    - straight-talking
    - no-nonsense
  
  expertise:
    - kung fu
    - action movies
    - martial arts
    - B-movies
    - Hong Kong cinema
  
  response_style: "short and punchy"
  
  name_variations:
    - cynthia
    - rothrock
    - cynthiarothbot

templates:
  system_prompt: |
    You are {{character_name}}, {{character_description}}.
    
    Current date and time: {{meta.current_time}}
    
    Your personality traits: {{personality_traits|join(', ')}}
    Your areas of expertise: {{expertise|join(', ')}}
    Response style: {{response_style}}
    
    Guidelines:
    - Keep responses under 255 characters
    - Be {{response_style}}
    - Use your expertise when relevant
    - Emotes available: {{emotes|join(', ')}}
  
  default_trigger: |
    {% if current_media %}
    Current Media:
      Title: {{current_media.title}}
      Total Runtime: {{current_media.duration_str}}
      Time elapsed: {{current_media.position_str}}
      Time remaining: {{current_media.remaining_str}}
    {% endif %}
    
    Recent Chat:
    {% for msg in chat_history %}
    {{msg.username}}: {{msg.message}}
    {% endfor %}
    
    Respond naturally to the conversation.
  
  media_change: |
    New video just started: {{media.title}}
    {% if media.queued_by %}Queued by: {{media.queued_by}}{% endif %}
    
    Make a brief, enthusiastic comment about the video.
```

### Implementation

#### Phase 1: YAML Schema and Loader
- Create PersonalityProfile model (Pydantic)
- Implement YAML loader with validation
- Add backwards compatibility for inline config
- Write unit tests for profile loading

#### Phase 2: Template Integration
- Extract template content from .j2 files to YAML
- Update PromptBuilder to use personality templates
- Preserve Jinja2 template functionality
- Migrate existing templates to new format

#### Phase 3: Multi-Profile Support
- Create example personality profiles
- Document profile creation guidelines
- Add profile validation on load

---

## FEAT-002: Dynamic Emote List Integration

### Description

Fetch the dynamic emote list from JetStream KV store (maintained by kryten-robot) and integrate it into LLM prompts. Implement blacklist functionality to prune problematic emotes that the model tends to overuse.

### Requirements

#### REQ-002-01: Fetch emote list from JetStream KV store

**Acceptance Criteria:**
- Connect to JetStream KV bucket containing emotes
- Parse emote array from kryten-robot's stored format
- Handle bucket not found / empty gracefully
- Cache emote list with configurable refresh interval

#### REQ-002-02: Implement emote blacklist filtering

**Acceptance Criteria:**
- Configurable blacklist in personality file
- Filter blacklisted emotes from fetched list
- Log when emotes are filtered
- Support regex patterns in blacklist

#### REQ-002-03: Inject emotes into prompt templates

**Acceptance Criteria:**
- Emotes available as `{{emotes}}` variable in templates
- Formatted appropriately for LLM consumption
- Updated on each request if cache expired
- Graceful fallback if emote list unavailable

#### REQ-002-04: Emote list refresh mechanism

**Acceptance Criteria:**
- Configurable cache TTL (default 300 seconds)
- Automatic refresh on cache expiry
- Manual refresh via command/PM
- Metrics for cache hit/miss rates

### Configuration

#### Emote Settings

```json
{
  "emotes": {
    "kv_bucket": "kryten_emotes",
    "kv_key": "cytu.be:420grindhouse:emotes",
    "cache_ttl_seconds": 300,
    "refresh_on_startup": true,
    "fallback_emotes": [":PogChamp:", ":Kappa:", ":KEKW:"]
  }
}
```

#### Personality File Additions

```yaml
emotes:
  blacklist:
    - ":KEK:"
    - ":OMEGALUL:"
    - "/.*KEKW.*/"  # Regex to block all KEKW variants
  
  formatting:
    max_emotes_in_prompt: 50  # Limit to avoid context bloat
    format_style: "compact"    # compact|verbose|hashtag
```

### JetStream Integration

**Bucket Name:** `kryten_emotes`  
**Key Format:** `{domain}:{channel}:emotes`

#### Expected Data Structure

Emote list stored by kryten-robot as JSON array of emote objects:

```json
[
  {
    "name": ":PogChamp:",
    "image": "https://example.com/emote.gif",
    "tags": ["hype", "excited"]
  },
  {
    "name": ":Kappa:",
    "image": "https://example.com/kappa.gif",
    "tags": ["sarcasm"]
  }
]
```

#### Error Handling

| Condition | Action |
|-----------|--------|
| Bucket not found | Log warning, use fallback_emotes |
| Key not found | Log warning, use fallback_emotes |
| Parse error | Log error, use fallback_emotes |
| Connection timeout | Use cached list if available, else fallback |

### Implementation

#### Phase 1: JetStream KV Integration
- Add EmoteManager component
- Implement KV bucket connection
- Parse emote list from kryten-robot format
- Write unit tests with mocked KV

#### Phase 2: Blacklist and Filtering
- Implement blacklist configuration
- Add regex pattern support
- Create emote filtering logic
- Log filtered emotes for debugging

#### Phase 3: Template Integration
- Add emotes to PromptBuilder context
- Update template examples to use `{{emotes}}`
- Implement cache TTL mechanism
- Add refresh command

---

## FEAT-003: Hot Reload via PM Commands

### Description

Allow blessed users (developers) to reload personality configuration, templates, and emote lists via private message commands without restarting the kryten-llm service. This enables rapid iteration and live tuning.

### Requirements

#### REQ-003-01: PM command infrastructure

**Acceptance Criteria:**
- Service listens for PM events from CyTube
- Authenticates sender against blessed user list
- Responds to commands via PM
- Logs all PM commands for audit

#### REQ-003-02: Personality reload command

**Acceptance Criteria:**
- Command: `!reload personality`
- Reloads personality YAML file from disk
- Updates templates and personality settings
- Validates before applying (rolls back on error)
- Confirms success/failure via PM

#### REQ-003-03: Emote list refresh command

**Acceptance Criteria:**
- Command: `!reload emotes`
- Forces refresh from JetStream KV
- Bypasses cache
- Reports number of emotes loaded/filtered

#### REQ-003-04: Full config reload command

**Acceptance Criteria:**
- Command: `!reload all`
- Reloads personality + emotes
- Validates all components before applying
- Atomic operation (all or nothing)

#### REQ-003-05: Status/info commands

**Acceptance Criteria:**
- Command: `!info personality` - shows current personality metadata
- Command: `!info emotes` - shows emote list status
- Command: `!list emotes` - shows available emotes (paginated)

### Configuration

#### Blessed Users

```json
{
  "pm_commands": {
    "enabled": true,
    "blessed_users": ["grobertson", "admin_user"],
    "rank_requirement": 10,
    "command_prefix": "!",
    "rate_limit": {
      "max_commands_per_minute": 10,
      "max_commands_per_hour": 100
    }
  }
}
```

### Command Specification

#### `!reload personality [profile_name]`

Reload personality from file

**Parameters:**
- `profile_name` (optional) - If provided, switches to different profile

**Response:**
- Success: `✅ Personality reloaded: {character_name} v{version}`
- Error: `❌ Failed to reload: {error_message}`

**Side Effects:**
- Templates updated in PromptBuilder
- Personality traits refreshed
- Name variations updated in TriggerEngine

#### `!reload emotes`

Force refresh emote list from JetStream

**Response:**
- Success: `✅ Loaded {count} emotes ({filtered} filtered)`
- Error: `❌ Failed to reload emotes: {error_message}`

#### `!reload all`

Reload personality and emotes

**Response:**
- Success: `✅ Full reload complete`
- Error: `❌ Reload failed: {error_message}`

#### `!info personality`

Show current personality metadata

**Response:**
```
📋 Personality: {character_name}
Version: {version}
Modified: {last_modified}
Traits: {trait_count}
Emotes: {emote_count} ({blacklisted} blacklisted)
```

#### `!info emotes`

Show emote list status

**Response:**
```
🎭 Emotes: {count} available
Cached: {cache_age}s ago
Blacklisted: {blacklist_count}
Source: {kv_bucket}:{kv_key}
```

#### `!list emotes [page]`

List available emotes (paginated)

**Response:**
```
🎭 Emotes (page {page}/{total_pages}):
{emote_list}
```

### Implementation

#### Phase 1: PM Event Handling
- Subscribe to PM events (`kryten.events.{domain}.{channel}.pm`)
- Implement blessed user authentication
- Create PMCommandHandler component
- Add command parsing and routing

#### Phase 2: Reload Commands
- Implement `!reload personality`
- Implement `!reload emotes`
- Implement `!reload all`
- Add validation and rollback logic

#### Phase 3: Info Commands
- Implement `!info personality`
- Implement `!info emotes`
- Implement `!list emotes`
- Add pagination support

#### Phase 4: Safety and Logging
- Add rate limiting for PM commands
- Audit log for all command executions
- Add command cooldowns
- Implement permission checks

---

## FEAT-004: Humanized Response Timing

### Description

Add configurable and variable delays before sending responses to make the bot's timing appear more human and natural. Delays should be context-aware (shorter for quick reactions, longer for thoughtful responses).

### Requirements

#### REQ-004-01: Configurable base delay

**Acceptance Criteria:**
- Min and max delay configurable in seconds
- Random delay between min/max applied before responses
- Different delay ranges for different trigger types

#### REQ-004-02: Context-aware delay calculation

**Acceptance Criteria:**
- Mentions get shorter delays (quick reaction)
- Trigger words get medium delays
- Media changes get configurable delays
- Auto-participation gets longer delays (thoughtful)

#### REQ-004-03: Message length simulation

**Acceptance Criteria:**
- Delay scales with response length (typing simulation)
- Configurable characters per second rate
- Optional "is typing" indicator support (future)

#### REQ-004-04: Delay bypasses and overrides

**Acceptance Criteria:**
- Blessed users can request immediate responses
- Emergency/high-priority triggers bypass delay
- Dry-run mode shows delay without waiting

### Configuration

```json
{
  "response_timing": {
    "enabled": true,
    
    "base_delays": {
      "mention": {
        "min_seconds": 0.5,
        "max_seconds": 2.0
      },
      "trigger_word": {
        "min_seconds": 1.0,
        "max_seconds": 4.0
      },
      "media_change": {
        "min_seconds": 2.0,
        "max_seconds": 5.0
      },
      "auto_participation": {
        "min_seconds": 3.0,
        "max_seconds": 8.0
      }
    },
    
    "typing_simulation": {
      "enabled": true,
      "characters_per_second": 15.0,
      "min_typing_delay": 1.0,
      "max_typing_delay": 10.0,
      "variability": 0.2
    },
    
    "bypasses": {
      "blessed_users_instant": true,
      "emergency_triggers": [],
      "max_delay_cap": 30.0
    }
  }
}
```

### Delay Calculation Algorithm

```
1. Determine trigger type (mention, word, media, auto)
2. Get base delay range for trigger type
3. Calculate base_delay = random(min, max)
4. If typing simulation enabled:
   - typing_delay = len(response) / chars_per_second
   - typing_delay = clamp(typing_delay, min_typing, max_typing)
   - typing_delay *= random(1 - variability, 1 + variability)
   - total_delay = base_delay + typing_delay
5. Apply cap: total_delay = min(total_delay, max_delay_cap)
6. Check bypasses: if blessed_user, total_delay = 0
7. Return total_delay
```

### Implementation

#### Phase 1: Delay Infrastructure
- Create ResponseTimingManager component
- Implement delay calculation algorithm
- Add configuration schema
- Write unit tests for timing logic

#### Phase 2: Service Integration
- Integrate delays into message send pipeline
- Add async delay before sending to chat
- Log actual delays for analysis
- Add metrics for delay distribution

#### Phase 3: Context-Aware Delays
- Pass trigger type to timing manager
- Implement typing simulation
- Add blessed user bypass
- Test with various message types

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Features:**
- FEAT-001: Externalized Personality Configuration
- FEAT-004: Humanized Response Timing

**Justification:**  
These are independent features that can be implemented in parallel. FEAT-001 is foundational for FEAT-002 and FEAT-003. FEAT-004 is standalone and provides immediate UX improvement.

### Phase 2: Dynamic Data Integration (Week 2)

**Features:**
- FEAT-002: Dynamic Emote List Integration

**Dependencies:**
- FEAT-001 (Needs personality file format for blacklist config)

**Justification:**  
Emote integration builds on personality file infrastructure. Requires coordination with kryten-robot team for KV store format.

### Phase 3: Live Administration (Week 3)

**Features:**
- FEAT-003: Hot Reload via PM Commands

**Dependencies:**
- FEAT-001 (Needs personality reload capability)
- FEAT-002 (Needs emote refresh capability)

**Justification:**  
PM commands tie together the reload capabilities from previous phases. Enables rapid iteration on personality and emotes.

---

## Testing Strategy

### Unit Tests
- PersonalityProfile model validation
- YAML loading and parsing
- Emote blacklist filtering
- Delay calculation algorithms
- PM command parsing and routing
- Blessed user authentication

### Integration Tests
- Personality file reload workflow
- JetStream KV emote fetching
- Template rendering with dynamic emotes
- PM command execution end-to-end
- Response timing in message pipeline

### Manual Testing
- Switch between personality profiles
- Test emote blacklist effectiveness
- Verify PM commands from blessed user
- Measure response timing variance
- Test reload rollback on invalid config

---

## Migration Strategy

### Backwards Compatibility
- Existing inline personality config still works
- `personality_file` is optional in main config
- If `personality_file` missing, use inline config
- Existing templates in `templates/` directory still work
- New YAML templates take precedence if present

### Migration Steps

1. **Create default personality file from current config**
   ```bash
   python -m kryten_llm.tools.export_personality config.json personalities/default.yaml
   ```

2. **Update main config to reference personality file**
   - Add `personality_file: personalities/default.yaml` to config

3. **Test personality reload**
   - Verify service starts successfully with external personality file

4. **Optional: Remove inline personality config**
   - Keep inline config as fallback for first iteration

---

## Configuration Examples

### Main Config (`config.json`)

```json
{
  "personality_file": "personalities/cynthia-rothbot-v1.yaml",
  
  "emotes": {
    "kv_bucket": "kryten_emotes",
    "kv_key": "cytu.be:420grindhouse:emotes",
    "cache_ttl_seconds": 300,
    "refresh_on_startup": true,
    "fallback_emotes": [":PogChamp:", ":Kappa:", ":KEKW:"]
  },
  
  "response_timing": {
    "enabled": true,
    "base_delays": {
      "mention": {"min_seconds": 0.5, "max_seconds": 2.0},
      "trigger_word": {"min_seconds": 1.0, "max_seconds": 4.0},
      "media_change": {"min_seconds": 2.0, "max_seconds": 5.0},
      "auto_participation": {"min_seconds": 3.0, "max_seconds": 8.0}
    },
    "typing_simulation": {
      "enabled": true,
      "characters_per_second": 15.0
    }
  },
  
  "pm_commands": {
    "enabled": true,
    "blessed_users": ["grobertson"],
    "rank_requirement": 10
  }
}
```

### Personality File (`personalities/cynthia-rothbot-v1.yaml`)

See example in FEAT-001 section above.

---

## Metrics and Monitoring

### Personality Metrics
- `personality_reload_count`
- `personality_reload_errors`
- `personality_load_duration_seconds`
- `active_personality_version`

### Emote Metrics
- `emote_list_size`
- `emote_cache_hits`
- `emote_cache_misses`
- `emote_blacklist_filter_count`
- `emote_refresh_duration_seconds`

### PM Command Metrics
- `pm_commands_received_total`
- `pm_commands_by_user`
- `pm_commands_by_type`
- `pm_command_errors`
- `unauthorized_pm_attempts`

### Response Timing Metrics
- `response_delay_seconds` (histogram)
- `response_delay_by_trigger_type`
- `typing_simulation_duration_seconds`
- `delayed_responses_total`

---

## Security Considerations

### PM Commands
- Strict authentication against blessed user list
- Require minimum CyTube rank (owner by default)
- Rate limiting to prevent command spam
- Audit logging of all command executions
- Command validation before execution

### Personality Reload
- Validate YAML syntax before loading
- Rollback to previous config on error
- Sanitize template content (prevent code injection)
- Limit file size to prevent DoS

### Emote Blacklist
- Validate regex patterns to prevent ReDoS
- Limit blacklist size
- Log all filtering actions

---

## Future Enhancements

- Multiple personality profiles loaded simultaneously
- Per-user personality overrides
- Personality A/B testing
- LLM-based personality adaptation
- Emote usage analytics and auto-blacklisting
- Advanced PM commands (parameter tuning, testing modes)
- Web UI for personality editing
- Personality marketplace/sharing
