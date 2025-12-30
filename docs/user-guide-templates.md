# User Guide: Customizing LLM Prompts with Templates

The `kryten-llm` service uses **Jinja2** templates to construct prompts for the Large Language Model. This allows you to fully customize how the bot responds to different events without writing code.

## 1. Template Location
By default, templates are stored in the `templates/` directory in the root of the project.
You can configure this location in `config.json` under `templates.dir`.

## 2. Template Hierarchy (How Templates are Selected)
When an event occurs (like a user mentioning the bot), the system looks for the most specific template available.

**Selection Order:**
1.  **Fully Specific**: `trigger-{type}-{name}.j2`
    *   Matches a specific trigger name.
    *   *Example:* `trigger-mention-kryten.j2` (Only for mentions of "Kryten")
    *   *Example:* `trigger-keyword-chess.j2` (Only for the "chess" keyword trigger)
2.  **Type Specific**: `trigger-{type}.j2`
    *   Matches any trigger of a certain type.
    *   *Example:* `trigger-mention.j2` (For any mention)
    *   *Example:* `trigger-keyword.j2` (For any keyword)
3.  **Default Fallback**: `trigger.j2`
    *   Used if no specific template is found.
    *   Configurable via `templates.default_trigger` in `config.json`.

**System Prompts:**
*   `system.j2`: Defines the bot's personality and core rules. Used for every request.

**Media Events:**
*   `media_change.j2`: Used when the video/media changes.

## 3. Available Context Data
The following data variables are available in **all** templates.

### `bot` (Bot Configuration)
| Field | Type | Description |
| :--- | :--- | :--- |
| `bot.name` | string | Character name (e.g., "KrytenBot") |
| `bot.description` | string | Short description |
| `bot.traits` | list[str] | Personality traits |
| `bot.expertise` | list[str] | Areas of expertise |
| `bot.style` | string | Response style guide |
| `bot.rules` | list[str] | System rules (e.g., "Keep it short") |

### `user` (The Sender)
| Field | Type | Description |
| :--- | :--- | :--- |
| `user.username` | string | Name of the user who triggered the event |
| `user.message` | string | The message text (cleaned) |

### `trigger` (Trigger Details)
| Field | Type | Description |
| :--- | :--- | :--- |
| `trigger.type` | string | Type of trigger (e.g., "mention", "keyword") |
| `trigger.name` | string | Name of the trigger (e.g., "kryten", "toddy") |
| `trigger.context` | string | Additional context defined in config |

### `current_media` (Currently Playing)
*Values are `null` if nothing is playing.*

| Field | Type | Description |
| :--- | :--- | :--- |
| `current_media.title` | string | Title of the video |
| `current_media.duration_str` | string | Formatted duration (e.g., "1h, 30m, 0s") |
| `current_media.position_str` | string | Current playback position (e.g., "0h, 45m, 10s") |
| `current_media.queued_by` | string | User who queued the video |
| `current_media.type` | string | Media type (e.g., "youtube") |

### `next_media` (Up Next)
*Values are `null` if queue is empty.*

| Field | Type | Description |
| :--- | :--- | :--- |
| `next_media.title` | string | Title of the next video |
| `next_media.duration_str` | string | Formatted duration |
| `next_media.queued_by` | string | User who queued it |

### `chat_history` (Recent Messages)
A list of recent chat messages (usually last 30).

| Field | Type | Description |
| :--- | :--- | :--- |
| `msg.username` | string | Sender name |
| `msg.message` | string | Message text |

### `meta` (System Info)
| Field | Type | Description |
| :--- | :--- | :--- |
| `meta.time` | string | Current time (HH:MM:SS) |
| `meta.date` | string | Current date (YYYY-MM-DD) |

---

## 4. Examples

### Example 1: Basic Chat Response (`trigger.j2`)
```jinja
{{ user.username }} says: {{ user.message }}

{% if current_media %}
Currently watching: {{ current_media.title }}
{% endif %}

Recent chat:
{% for msg in chat_history[-5:] %}
- {{ msg.username }}: {{ msg.message }}
{% endfor %}
```

### Example 2: Specific Game Trigger (`trigger-keyword-chess.j2`)
*Use this for a trigger named "chess" in `config.json`.*

```jinja
User {{ user.username }} is asking about chess: "{{ user.message }}"

The current game state is: {{ trigger.context }}

Please analyze the board and suggest the best move in the style of a grandmaster.
```

### Example 3: Time-Aware Greeting (`trigger-mention.j2`)
```jinja
{% if meta.time > "18:00:00" %}
It is late evening. {{ user.username }} asks: {{ user.message }}
{% else %}
{{ user.username }} asks: {{ user.message }}
{% endif %}
```

### Example 4: Admin Recognition
```jinja
{{ user.username }} says: {{ user.message }}

{% if user.username == "AdminUser" %}
(Note: This user is an administrator. Be extra helpful.)
{% endif %}
```
