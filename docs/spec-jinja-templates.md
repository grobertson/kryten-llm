# Specification: Jinja2 Template System for LLM Prompts

## 1. Overview
This specification outlines the refactoring of the `kryten-llm` prompt generation system to use **Jinja2** templates. Currently, prompts are constructed using Python f-strings and hardcoded logic within `PromptBuilder`. Moving to Jinja2 will allow for flexible, user-configurable prompts without code changes, and enable complex logic (loops, conditionals) within the prompts themselves.

## 2. Goals
- **Separation of Concerns**: Decouple prompt structure from Python code.
- **Configurability**: Allow users to customize prompts via template files.
- **Rich Context**: Expose all available system state (video, queue, chat history, user stats, triggers) to the templates.
- **Consistency**: Use a unified context structure for all prompt types.

## 3. Template Management

### 3.1 Template Storage
Templates will be stored in a dedicated directory (default: `templates/`) relative to the application root.
The configuration will specify the template names to use for different scenarios.

**Default Directory Structure:**
```
templates/
  ├── system.j2            # The system prompt (personality, rules)
  ├── chat_response.j2     # Standard chat response prompt
  └── media_change.j2      # Media transition prompt
```

### 3.2 Configuration Changes
The `config.json` (and `LLMConfig` model) will be updated to include a `templates` section:

```json
"templates": {
  "dir": "templates",
  "system": "system.j2",
  "default_trigger": "trigger.j2",
  "media_change": "media_change.j2"
}
```

### 3.3 Dynamic Template Selection (Hierarchy)
For user prompts triggered by specific events, the system will search for templates in the following order of precedence. The first file found in the `templates/` directory will be used.

1.  **Fully Specific**: `trigger-{type}-{name}.j2`
    *   Example: `trigger-mention-kryten.j2`
    *   Example: `trigger-keyword-toddy.j2`
2.  **Type Specific**: `trigger-{type}.j2`
    *   Example: `trigger-mention.j2`
    *   Example: `trigger-auto_participation.j2`
3.  **Generic Fallback**: `trigger.j2` (Configurable via `default_trigger`)

This allows for highly specific prompting for unique triggers (like specific games or characters) while maintaining a safe fallback.

## 4. The Jinja Context
The following data structure will be passed to **every** template render call, ensuring consistent access to data.

### 4.1 Global Context Structure
```json
{
  "bot": {
    "name": "KrytenBot",
    "description": "...",
    "traits": ["trait1", "trait2"],
    "expertise": ["topic1", "topic2"],
    "style": "...",
    "rules": ["rule1", "rule2"]
  },
  "current_media": {
    "title": "Movie Title",
    "duration": 7200,      # seconds
    "duration_str": "2h, 0m, 0s",
    "position": 3600,      # seconds
    "position_str": "1h, 0m, 0s",
    "type": "movie",
    "queued_by": "User1"
  },
  "next_media": {
    "title": "Next Movie",
    "duration": 5400,
    "duration_str": "1h, 30m, 0s",
    "type": "movie",
    "queued_by": "User2"
  },
  "chat_history": [
    {
      "username": "User1",
      "message": "Hello",
      "timestamp": "ISO-8601...",
      "time_ago": "5s"
    }
  ],
  "trigger": {
    "type": "mention",     # or "keyword", "auto_participation"
    "name": "kryten",
    "pattern": "kryten",
    "context": "..."       # specific trigger context if defined
  },
  "user": {
    "username": "SenderName",
    "message": "The triggering message text",
    "rank": 1
  },
  "event": {
    "type": "chat",        # or "media_change"
    "transition_explanation": "..." # Only for media_change
  },
  "meta": {
    "time": "HH:MM:SS",
    "date": "YYYY-MM-DD"
  }
}
```

## 5. Implementation Plan

### 5.1 Dependencies
- Add `jinja2` to project dependencies.

### 5.2 Refactor `PromptBuilder`
- Initialize `jinja2.Environment` with a `FileSystemLoader`.
- Replace `build_system_prompt()`, `build_user_prompt()`, and `build_media_change_prompt()` logic.
- Implement `_select_template(trigger_result)` method to resolve the hierarchy:
    1. Check `trigger-{type}-{name}.j2`
    2. Check `trigger-{type}.j2`
    3. Fallback to `trigger.j2`
- Gather the `context` dictionary and call `template.render(**context)`.

### 5.3 Default Templates
Create default Jinja2 templates that replicate the current behavior.

**`templates/system.j2`**
```jinja
You are {{ bot.name }}, {{ bot.description }}.

Personality traits: {{ bot.traits|join(', ') }}
Areas of expertise: {{ bot.expertise|join(', ') }}

Response style: {{ bot.style }}

Important rules:
{% for rule in bot.rules %}
- {{ rule }}
{% endfor %}
- Keep responses under 240 characters
- Stay in character
- Be natural and conversational
- Do not use markdown formatting
- Do not start responses with your character name
```

**`templates/trigger.j2`** (Generic Fallback)
```jinja
{{ user.username }} says: {{ user.message }}

{% if current_media %}
Currently playing: {{ current_media.title }} (Current position: {{ current_media.position_str }} / {{ current_media.duration_str }}) (queued by {{ current_media.queued_by }})
{% endif %}

{% if next_media %}
Next Playing: {{ next_media.title }}, ({{ next_media.duration_str }})
{% endif %}

{% if chat_history %}
Recent conversation:
{% for msg in chat_history[-30:] %}
- {{ msg.username }}: {{ msg.message }}
{% endfor %}
{% endif %}

{% if trigger.context %}
Context: {{ trigger.context }}
{% endif %}
```

**`templates/trigger-mention.j2`** (Example Specialization)
```jinja
{{ user.username }} mentioned you: {{ user.message }}
... (rest of context) ...
```

## 6. Migration Steps
1.  Create `templates/` directory and populate with default templates.
2.  Update `config.py` / `LLMConfig` to support template configuration.
3.  Modify `PromptBuilder` to load templates.
4.  Update `service.py` or `ContextManager` to ensure all context data (especially formatted time strings) is prepared before calling the builder.
5.  Run tests to ensure prompt output matches expectations.

## 7. Developer Guide

### 7.1 Adding New Triggers
To add a new trigger type (e.g., a new game integration or specialized response):

1.  **Define Trigger**: Add the trigger configuration in `config.json`.
    ```json
    "triggers": [
      {
        "name": "chess_move",
        "patterns": ["e4", "d4", "knight to"],
        ...
      }
    ]
    ```

2.  **Create Template**: Create a template file in `templates/` matching the naming convention.
    *   **Best Practice**: Create `templates/trigger-keyword-chess_move.j2` for maximum specificity.
    *   **Content**:
        ```jinja
        The user {{ user.username }} just made a chess move: "{{ user.message }}"
        
        Current game state: {{ trigger.context }}
        
        Analyze the move and comment on it in the style of a grandmaster.
        ```

3.  **Verify**: The `PromptBuilder` will automatically find this template when the trigger fires, because the trigger type is `keyword` and the name is `chess_move`.

### 7.2 Advanced Template Usage
Jinja2 allows for complex logic within templates.

**Conditionals based on Time:**
```jinja
{% if meta.time > "18:00:00" %}
Good evening {{ user.username }}!
{% else %}
Hello {{ user.username }}!
{% endif %}
```

**Looping through History with Filters:**
```jinja
{% for msg in chat_history if msg.username != 'KrytenBot' %}
  User said: {{ msg.message }}
{% endfor %}
```

**Using User Stats (if available):**
```jinja
{% if user.rank > 2 %}
  (Addressing a VIP/Admin)
{% endif %}
```

**Accessing Custom Trigger Context:**
If your trigger provides JSON context (e.g., game state, API result), you can access it directly:
```jinja
The weather in {{ trigger.context.city }} is {{ trigger.context.temp }} degrees.
```

