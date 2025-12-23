# Media Change Trigger System

## Overview
The Media Change Trigger System enables the LLM bot to autonomously comment on media playback transitions. It monitors `changemedia` events, filters them based on duration thresholds, and generates context-aware commentary referencing the previous significant media item.

## Configuration API

The feature is configured via the `media_change` section in `config.json` (or `LLMConfig`):

```json
{
  "media_change": {
    "enabled": true,
    "min_duration_minutes": 30,
    "chat_context_depth": 3,
    "transition_explanation": "The media has just changed."
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Master toggle for the feature. |
| `min_duration_minutes` | integer | `30` | Minimum duration (1-240 mins) for a media item to trigger an event. |
| `chat_context_depth` | integer | `3` | Number of recent chat messages (1-10) to include in the prompt context. |
| `transition_explanation` | string | "..." | Text describing the event to the LLM (max 140 chars). |

## Technical Specification

### Event Flow
1. **Event Reception**: `LLMService` receives `kryten.events.cytube.{channel}.changemedia` via NATS.
2. **Context Update**: `ContextManager` updates the current video state.
3. **Trigger Check**: `TriggerEngine.check_media_change()` is called.
   - Validates `duration >= min_duration_minutes * 60`.
   - If valid, updates `last_qualifying_media` state.
4. **State Persistence**: State is saved to KV store (see Schema).
5. **Prompt Generation**: `PromptBuilder` constructs a prompt with:
   - Current media title & duration.
   - Previous qualifying media title.
   - Recent chat history.
6. **Response**: LLM generates a response, which is validated, formatted, and sent to the channel.

### KV Store Schema
The system uses the `kryten-py` KV store interface.

- **Bucket**: `kryten_llm_trigger_state`
- **Key**: `last_qualifying_media`
- **Value**: JSON Object
  ```json
  {
    "title": "Movie Title",
    "duration": 3600
  }
  ```

### Message Template
The system uses an internal template for prompt generation (managed by `PromptBuilder`). It injects the following variables:
- `Current Media`: Title and duration.
- `Previous Qualifying Media`: Title of the last media that met the threshold.
- `Event`: The configured `transition_explanation`.
- `Recent chat`: The last `chat_context_depth` messages.

## Operational Guide

### Feature Activation
To enable, set `media_change.enabled` to `true` in your configuration.

### Threshold Tuning
- **Short thresholds (e.g., 5-10 mins)**: Will trigger on most TV shows and long music videos. May result in frequent interruptions.
- **Long thresholds (e.g., 60+ mins)**: Best for movie nights. Will ignore TV episodes and shorts.

### Troubleshooting
- **No Trigger**:
  - Check if `enabled` is true.
  - Check if media duration exceeds `min_duration_minutes`.
  - Check logs for "Media duration X below threshold Y".
- **Wrong Previous Media**:
  - The "previous" media is only updated when a *new* media meets the threshold. Short items are ignored and do not overwrite the "previous" state.
  - Check KV store connectivity if state is lost after restart.
