# Kryten-LLM Requirements

## Overview

A CyTube chat bot service powered by LLM (Large Language Model) that provides entertaining, useful, and contextually aware responses to a grindhouse movie community. The bot impersonates a configurable personality (default: Cynthia Rothrock as "CynthiaRothbot") and interacts with chat users in a fun, non-intrusive manner.

## Core Purpose

The kryten-llm service monitors CyTube chat messages and selectively responds based on:
- Direct mentions of the bot's name
- Configurable trigger words/phrases (inside jokes, cultural references)
- Movie-related queries and trivia opportunities
- Contextual awareness of channel activity and content

**Key Principle**: Be fun, funny, or useful - never annoying.

## Channel Context

### Audience & Culture

- **Content Focus**: Grindhouse cinema, B-movies, cult classics
  - Friday-Sunday: Peak grindhouse programming
  - Kung fu films, slasher/horror, 1980s direct-to-video action
  - 1960s drive-in commercials (e.g., "Toddy" beverage ads)
- **Inside Jokes & Running Gags**:
  - "Toddy": Evolved from vintage commercial to mock religion/philosophy
  - Example: "Toddy is your NEW god. Worship Toddy at the church of your choice!"
  - Many other cultural references unique to the community
- **Activity Patterns**:
  - Highly variable user count and engagement
  - Weekend peaks during grindhouse programming
  - Synchronized viewing creates real-time shared experience

### Bot Personality

**Default: CynthiaRothbot (Cynthia Rothrock)**
- Martial arts legend and action star persona
- Pithy, confident, action-oriented responses
- Knowledgeable about action films and martial arts
- Short, punchy communication style (befitting her screen persona)

**Configurable Personality System**:
- Personality profiles stored in configuration
- System prompts tailored to character
- Different characters for different use cases
- Ability to reference character's expertise (movies, martial arts, etc.)

## Functional Requirements

### 1. Message Monitoring & Filtering

#### Chat Message Ingestion

- Subscribe to `kryten.events.cytube.{channel}.chatmsg` via kryten-py
- Filter spam, commands, and bot messages
- Extract message metadata:
  - Username
  - User rank (0=guest, 1=user, 2=moderator, 3=admin, 4+=owner)
  - Message text
  - Timestamp
  - Correlation ID (for tracing)

#### Message Qualification

Determine if bot should respond based on:
1. **Direct Mentions**: Bot name appears in message
2. **Trigger Words**: Configured phrases/keywords detected
3. **Cooldown State**: User and global rate limits not exceeded
4. **Context**: Recent chat activity, current video, time of day

### 2. Response Triggering System

#### Mention Detection

**Direct Name Mentions**:
- Bot responds when its CyTube username appears in message
- Case-insensitive matching
- Partial matches configurable (e.g., "Cynthia" vs "CynthiaRothbot")
- Strip bot name from message before LLM processing
- Higher priority than trigger words

**Mention Behavior**:
- Extract question/statement after name removal
- Pass to LLM with full context
- Optional: Special MCP tools available for mentions
- Optional: Inject additional context (user stats, current video info)

#### Trigger Word System

**Trigger Configuration**:
```json
{
  "triggers": [
    {
      "name": "toddy",
      "patterns": ["toddy", "worship toddy", "church of toddy"],
      "probability": 0.15,
      "cooldown_seconds": 300,
      "context": "Toddy is a vintage beverage from 1960s drive-in commercials. In this chat, it's become a running joke about being a religion/way of life rather than just a drink.",
      "response_style": "brief_playful",
      "max_responses_per_hour": 3
    },
    {
      "name": "kung_fu",
      "patterns": ["kung fu", "martial arts", "karate"],
      "probability": 0.25,
      "cooldown_seconds": 180,
      "context": "User mentioned martial arts - Cynthia Rothrock is a martial arts expert.",
      "response_style": "knowledgeable",
      "max_responses_per_hour": 5
    }
  ]
}
```

**Trigger Matching**:
- Regex or substring matching
- Case-insensitive by default
- Multiple patterns per trigger
- Probability-based activation (0.0-1.0)
- Per-trigger cooldown timers
- Global and per-user rate limiting

**Trigger Context Injection**:
- Trigger-specific context added to LLM prompt
- Explains the inside joke/reference
- Guides response style and tone
- Helps LLM understand cultural nuance

### 3. Rate Limiting & Cooldowns

#### Global Rate Limits

- **Max responses per minute**: 2 (configurable)
- **Max responses per hour**: 20 (configurable)
- **Cooldown between any responses**: 15 seconds minimum

#### Per-User Rate Limits

- **Max responses to same user per hour**: 5 (configurable)
- **Cooldown per user**: 60 seconds minimum
- **Mention cooldown per user**: 120 seconds
- **Trigger cooldown per user per trigger**: Based on trigger config

#### Admin/Moderator Exceptions

Users with rank >= 2 (moderator+):
- Reduced cooldowns (50% of normal)
- Higher response limits (2x normal)
- Can bypass certain rate limits (configurable)
- Useful for testing and bot interaction

#### Spam Prevention

- Detect repeated identical messages (ignore after 1st)
- Detect rapid-fire mentions (exponential backoff)
- Ignore messages during floods (>10 messages/10 seconds)

### 4. LLM Integration

#### Multi-Provider Support

**Supported APIs**:
- OpenAI-compatible endpoints (local or cloud)
- OpenRouter API
- Anthropic API (optional)
- Custom endpoint support

**Provider Configuration**:
```json
{
  "llm_providers": {
    "default": {
      "name": "local",
      "type": "openai_compatible",
      "base_url": "http://192.168.1.100:8000/v1",
      "api_key": "local-key",
      "model": "llama-3-8b-instruct",
      "max_tokens": 150,
      "temperature": 0.8
    },
    "fallback": {
      "name": "openrouter",
      "type": "openrouter",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key": "sk-or-...",
      "model": "anthropic/claude-3-haiku",
      "max_tokens": 150,
      "temperature": 0.7
    },
    "trivia": {
      "name": "specialized",
      "type": "openai_compatible",
      "base_url": "http://192.168.1.100:8000/v1",
      "model": "mixtral-8x7b-instruct",
      "max_tokens": 200,
      "temperature": 0.5
    }
  }
}
```

**Provider Selection**:
- Default provider for general chat
- Trigger-specific providers (e.g., "trivia" trigger uses specialized model)
- Mention-specific providers (e.g., complex queries use larger model)
- Automatic fallback on provider failure

#### Prompt Engineering

**System Prompt Template**:
```
You are {character_name}, {character_description}.

Personality traits: {personality_traits}

Context: You are chatting in a CyTube channel dedicated to grindhouse and B-movies. The audience loves cult classics, kung fu films, horror, and 1980s action movies.

Current situation: {current_context}

Guidelines:
- Keep responses SHORT (under 200 characters ideally)
- Be pithy, entertaining, and in-character
- Reference your expertise when relevant
- Match the casual, fun tone of the chat
- Don't be preachy or overly helpful
- Embrace the absurd and humorous

{trigger_context}

Respond to the following message from user {username}:
{message}
```

**Context Variables**:
- `character_name`: Bot personality (e.g., "Cynthia Rothrock")
- `character_description`: Brief character bio
- `personality_traits`: Key characteristics (confident, action-oriented, etc.)
- `current_context`: Current video title, recent chat topics, time of day
- `trigger_context`: Trigger-specific context (if triggered)
- `username`: Who is being responded to
- `message`: The actual message (name-stripped if mention)

**Prompt Variants**:
- Default chat response
- Movie trivia query
- Trigger word response
- Direct question to bot
- Configurable per trigger/situation

### 5. Response Generation & Formatting

#### Length Constraints

- **CyTube limit**: ~255 characters per message
- **Target length**: 150-200 characters (comfortable margin)
- **Message splitting**: If LLM response exceeds limit, split intelligently:
  - Split on sentence boundaries
  - Split on punctuation (. ! ? ,)
  - Avoid mid-word splits
  - Add ellipsis (...) to indicate continuation
  - Send parts with 2-3 second delay between

#### Response Filtering

- **Content moderation**: Remove offensive content (configurable thresholds)
- **Self-reference removal**: Strip "As Cynthia Rothrock, I..." prefixes
- **Emoji handling**: Limit emoji usage (configurable)
- **URL sanitization**: Check for unexpected URLs

#### Response Validation

- Ensure response is on-topic
- Verify response matches personality
- Check for repetition (don't repeat recent responses)
- Validate response isn't just echoing the input

### 6. Testing & Development Mode

#### Dry-Run Mode

**Configuration**:
```json
{
  "testing": {
    "dry_run": true,
    "log_responses": true,
    "log_file": "logs/llm-responses.jsonl",
    "send_to_chat": false,
    "notify_admins": false
  }
}
```

**Dry-Run Behavior**:
- Process messages normally
- Generate LLM responses
- Log everything but DON'T send to chat
- Output to console and log file
- Include trigger analysis, rate limit status, LLM response

#### Response Logging

**Log Format** (JSONL):
```json
{
  "timestamp": "2025-12-10T15:30:00Z",
  "message_id": "correlation-id-123",
  "trigger_type": "mention",
  "trigger_name": "direct_mention",
  "username": "MovieFan42",
  "user_rank": 1,
  "input_message": "Hey CynthiaRothbot, what's your favorite kung fu movie?",
  "llm_provider": "local",
  "llm_model": "llama-3-8b-instruct",
  "llm_response_raw": "Great question! For me, it's got to be 'Yes, Madam!' (1985) - that final fight scene is legendary. What's yours?",
  "llm_response_processed": "Great question! For me, it's got to be 'Yes, Madam!' (1985) - that final fight scene is legendary. What's yours?",
  "response_sent": false,
  "dry_run": true,
  "rate_limit_status": {
    "global_ok": true,
    "user_ok": true,
    "cooldown_remaining": 0
  }
}
```

**Evaluation Tools**:
- Review logged responses for quality
- Analyze trigger effectiveness
- Tune probabilities and cooldowns
- Adjust prompts based on actual responses

### 7. Movie Trivia & Knowledge

#### Trivia Database Integration

**Sources**:
- IMDB data (via API or local database)
- Grindhouse/cult film databases
- User-contributed trivia (stored in NATS KV)
- LLM knowledge (for well-known films)

**Trivia Triggers**:
- Detect questions: "what movie...", "who directed...", "what year..."
- Current video context: Provide trivia about playing film
- Actor/director mentions: Share relevant facts

**Trivia Prompts**:
```
You are responding to a movie trivia question. Use your knowledge of grindhouse, B-movies, and cult classics to provide a brief, accurate answer.

Current movie playing: {current_video_title}

Question: {message}

Provide a short, informative response (under 200 characters).
```

### 8. Context Awareness

#### Video Context

- Subscribe to `kryten.events.cytube.{channel}.changemedia`
- Track current video title and metadata
- Inject into LLM prompts when relevant
- Enable video-specific responses

**Current Video Context**:
```json
{
  "title": "Enter the Ninja (1981)",
  "type": "yt",
  "id": "dQw4w9WgXcQ",
  "duration": 5940,
  "added_by": "MovieFan42"
}
```

#### Chat History Context

- Maintain rolling buffer of recent messages (last 20-50)
- Detect conversation threads
- Understand references to recent topics
- Avoid repeating information just mentioned

#### User Context (Optional)

- Integration with kryten-userstats
- User's favorite genres, activity patterns
- Personalize responses (sparingly)
- Remember past interactions (optional, privacy-sensitive)

### 9. MCP Tools Integration (Future)

#### Tool-Augmented Responses

For direct mentions, bot could invoke MCP tools:
- **Movie lookup**: Search IMDB, get details
- **User stats**: Query kryten-userstats for user info
- **Weather**: If bot personality supports it
- **Calculator**: For specific queries
- **Web search**: For obscure trivia (rate-limited)

**Tool Configuration**:
```json
{
  "mcp_tools": {
    "enabled": true,
    "available_tools": ["movie_lookup", "user_stats"],
    "tool_timeout_seconds": 5,
    "fallback_on_timeout": true
  }
}
```

### 10. Configuration Management

#### Configuration File

**Location**: `config.json` (or `config.{channel}.json` for multi-channel)

**Structure**:
```json
{
  "nats": {
    "url": "nats://localhost:4222",
    "credentials": "/path/to/nats.creds"
  },
  "cytube": {
    "domain": "cytu.be",
    "channel": "420grindhouse",
    "username": "CynthiaRothbot"
  },
  "personality": {
    "character_name": "Cynthia Rothrock",
    "character_description": "Martial arts legend and action movie star",
    "personality_traits": [
      "confident",
      "action-oriented",
      "martial arts expert",
      "pithy communicator",
      "grindhouse enthusiast"
    ],
    "expertise": ["martial arts", "action films", "stunt work", "kung fu cinema"],
    "response_style": "short, punchy, in-character"
  },
  "llm_providers": { ... },
  "triggers": [ ... ],
  "rate_limits": {
    "global_max_per_minute": 2,
    "global_max_per_hour": 20,
    "global_cooldown_seconds": 15,
    "user_max_per_hour": 5,
    "user_cooldown_seconds": 60,
    "mention_cooldown_seconds": 120,
    "admin_cooldown_multiplier": 0.5,
    "admin_limit_multiplier": 2.0
  },
  "message_processing": {
    "max_message_length": 240,
    "split_long_messages": true,
    "split_delay_seconds": 2.5,
    "filter_emoji": false,
    "max_emoji_per_message": 2
  },
  "testing": {
    "dry_run": false,
    "log_responses": true,
    "log_file": "logs/llm-responses.jsonl"
  },
  "context": {
    "track_current_video": true,
    "chat_history_buffer": 30,
    "use_user_stats": false
  }
}
```

#### Hot Reload

- Monitor config file for changes
- Reload configuration without restart
- Validate config before applying
- Log config changes

## Non-Functional Requirements

### Performance

- **Response Time**: Generate and send response within 3-5 seconds
- **Message Processing**: Handle 100+ messages/minute during peak
- **Memory Usage**: Stay under 500MB RAM
- **LLM Latency**: Fallback to alternative provider if >10 seconds

### Reliability

- **Uptime**: 99.9% availability
- **Error Handling**: Graceful degradation on LLM failures
- **Reconnection**: Auto-reconnect to NATS/LLM on disconnect
- **Logging**: Comprehensive error and event logging

### Security

- **API Keys**: Secure storage (environment variables or encrypted config)
- **Input Validation**: Sanitize all user inputs before LLM
- **Output Validation**: Moderate LLM outputs before sending
- **Rate Limiting**: Prevent abuse and spam

### Observability

- **Metrics**: Track response counts, trigger activations, LLM usage
- **Logging**: Structured logs for debugging and analysis
- **Health**: Publish service health and heartbeats
- **Tracing**: Use correlation IDs for message flow tracking

## Out of Scope

- ❌ Image/video generation
- ❌ Voice/audio synthesis
- ❌ Persistent conversation memory (long-term)
- ❌ Multi-language support (English only)
- ❌ User commands (!commands style)
- ❌ Moderation actions (kick/ban/mute)
- ❌ Playlist management

## Success Metrics

### Engagement

- Users interact with bot mentions (replies to bot messages)
- Positive sentiment in reactions
- Bot responses get laughs/engagement (measured by follow-up messages)

### Non-Annoyance

- No complaints about spam
- Bot doesn't dominate conversation (<5% of messages)
- Trigger responses feel natural, not forced

### Quality

- Responses are on-topic and in-character
- Low rate of nonsensical/irrelevant responses
- Trivia responses are accurate

### Technical

- Response time < 5 seconds (95th percentile)
- LLM success rate > 95%
- Service uptime > 99.9%

## Future Enhancements

- **Multi-Channel Support**: Run on multiple CyTube channels
- **Personality Switching**: Change personality based on content/time
- **Learning**: Improve responses based on user feedback
- **Advanced Tools**: More MCP tools for richer interactions
- **Voice Cloning**: Audio responses (if CyTube supports)
- **Image Recognition**: React to video stills/screenshots
- **Collaborative Features**: Interact with other bots

## Conclusion

The kryten-llm service aims to be a delightful, non-intrusive chat companion for grindhouse movie enthusiasts. By combining LLM intelligence with careful rate limiting, trigger configuration, and personality customization, it provides entertainment and movie knowledge without overwhelming the community. The focus on short, punchy responses and cultural awareness ensures the bot fits naturally into the existing chat culture.
