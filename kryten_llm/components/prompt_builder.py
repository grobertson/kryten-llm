"""Prompt builder for LLM requests."""

import logging
import os
import re
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from kryten_llm.models.config import LLMConfig

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Constructs prompts for LLM generation using Jinja2 templates.

    Phase 6: Replaces f-string construction with Jinja2 templates.
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration and Jinja2 environment.

        Args:
            config: LLM configuration containing personality and template settings
        """
        self.config = config
        self.personality = config.personality

        # Initialize Jinja2 environment
        template_dir = config.templates.dir
        # Ensure template dir exists, if not use default relative to package
        if not os.path.exists(template_dir):
            logger.warning(f"Template directory '{template_dir}' not found, using defaults")
            # Fallback or create? For now assume it exists or user configured it.
            # In a real package we might have internal defaults.

        self.env = Environment(
            loader=FileSystemLoader(template_dir), trim_blocks=True, lstrip_blocks=True
        )

        logger.info(f"PromptBuilder initialized with templates from: {template_dir}")

    def build_system_prompt(self) -> str:
        """Build system prompt from template.

        Returns:
            System prompt text
        """
        template_name = self.config.templates.system
        try:
            template = self.env.get_template(template_name)

            # Build context
            context = {
                "bot": {
                    "name": self.personality.character_name,
                    "description": self.personality.character_description,
                    "traits": self.personality.personality_traits,
                    "expertise": self.personality.expertise,
                    "style": self.personality.response_style,
                    "rules": [
                        "Keep responses under 240 characters",
                        "Stay in character",
                        "Be natural and conversational",
                        "Do not use markdown formatting",
                        f"Do not start responses with your character name ({self.personality.character_name})",
                    ],
                }
            }

            prompt = template.render(**context)
            logger.debug(f"Built system prompt ({len(prompt)} chars)")
            return prompt

        except Exception as e:
            logger.error(f"Failed to build system prompt from template {template_name}: {e}")
            # Fallback to hardcoded prompt if template fails
            return self._fallback_system_prompt()

    def _fallback_system_prompt(self) -> str:
        """Hardcoded fallback system prompt."""
        traits = ", ".join(self.personality.personality_traits)
        expertise = ", ".join(self.personality.expertise)
        return f"""You are {self.personality.character_name}, {self.personality.character_description}.
Personality traits: {traits}
Areas of expertise: {expertise}
Response style: {self.personality.response_style}
Important rules:
- Keep responses under 240 characters
- Stay in character"""

    def _format_time(self, seconds: float) -> str:
        """Format seconds into HHh, MMm, SSs string."""
        if not seconds:
            return "0s"
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h}h, {m}m, {s}s"
        elif m > 0:
            return f"{m}m, {s}s"
        else:
            return f"{s}s"

    def _select_template(self, trigger_type: str, trigger_name: str) -> str:
        """Select the most specific template available.

        Hierarchy:
        1. trigger-{type}-{name}.j2
        2. trigger-{type}.j2
        3. default_trigger (trigger.j2)
        """
        # 1. Specific: trigger-{type}-{name}.j2
        specific_name = f"trigger-{trigger_type}-{trigger_name}.j2"
        try:
            if specific_name in self.env.list_templates():
                return specific_name
        except Exception:
            pass  # list_templates might fail or be slow, relying on get_template try/except is often better?
            # Actually get_template raises TemplateNotFound.

        # 2. Type: trigger-{type}.j2
        type_name = f"trigger-{trigger_type}.j2"
        try:
            self.env.get_template(type_name)  # Check existence
            return type_name
        except Exception:
            pass

        # 3. Fallback
        return self.config.templates.default_trigger

    def build_user_prompt(
        self,
        username: str,
        message: str,
        trigger_context: str | dict | None = None,
        context: dict | None = None,
        trigger_result: dict | None = None,  # Pass full trigger result if available
    ) -> str:
        """Build user prompt using Jinja2 templates.

        Args:
            username: Username of message sender
            message: Cleaned message text
            trigger_context: Optional context from trigger
            context: Optional context dict from ContextManager
            trigger_result: Optional dict containing trigger type/name for template selection

        Returns:
            User prompt text
        """
        # Determine template
        if trigger_result:
            trigger_type = trigger_result.get("trigger_type", "unknown")
            trigger_name = trigger_result.get("trigger_name", "unknown")
            template_name = self._select_template(trigger_type, trigger_name)
        else:
            template_name = self.config.templates.default_trigger

        try:
            template = self.env.get_template(template_name)

            # Prepare data for template
            data = {
                "user": {
                    "username": username,
                    "message": message,
                    # "rank": ... passed in context?
                },
                "trigger": {
                    "context": trigger_context,
                    "type": trigger_result.get("trigger_type") if trigger_result else None,
                    "name": trigger_result.get("trigger_name") if trigger_result else None,
                },
                "meta": {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                },
                "chat_history": [],
                "current_media": None,
                "next_media": None,
            }

            # Enrich with context data
            if context:
                if context.get("current_video"):
                    vid = context["current_video"]
                    data["current_media"] = {
                        "title": vid.get("title"),
                        "duration": vid.get("duration"),
                        "duration_str": self._format_time(vid.get("duration", 0)),
                        "position": vid.get("position", 0),
                        "position_str": self._format_time(vid.get("position", 0)),
                        "type": vid.get("type"),
                        "queued_by": vid.get("queued_by"),
                    }

                if context.get("next_video"):
                    vid = context["next_video"]
                    data["next_media"] = {
                        "title": vid.get("title"),
                        "duration": vid.get("duration"),
                        "duration_str": self._format_time(vid.get("duration", 0)),
                        "type": vid.get("type"),
                        "queued_by": vid.get("queued_by"),
                    }

                if context.get("recent_messages"):
                    data["chat_history"] = context["recent_messages"]

            prompt = template.render(**data)

            # Clean up excessive newlines (max 2) and trim
            prompt = re.sub(r"\n{3,}", "\n\n", prompt).strip()

            # REQ-018: Manage prompt length (Simple truncation still applies)
            max_chars = self.config.context.context_window_chars
            if len(prompt) > max_chars:
                logger.warning(f"Prompt too long ({len(prompt)} chars), truncating")
                prompt = prompt[:max_chars]

            return prompt

        except Exception as e:
            logger.error(f"Failed to build user prompt from template {template_name}: {e}")
            return f"{username} says: {message}"  # Minimal fallback

    def build_media_change_prompt(self, template_data: dict, chat_history: list[dict]) -> str:
        """Build prompt for media change event using template.

        Args:
            template_data: Dict with media change info
            chat_history: List of recent chat messages

        Returns:
            User prompt text
        """
        template_name = self.config.templates.media_change
        try:
            template = self.env.get_template(template_name)

            data = {
                "event": {
                    "transition_explanation": template_data.get("transition_explanation"),
                    "previous_media_title": template_data.get("previous_media_title"),
                },
                "current_media": {
                    "title": template_data.get("current_media_title"),
                    "duration_str": template_data.get(
                        "current_media_duration"
                    ),  # Already formatted in TriggerEngine?
                },
                "chat_history": chat_history,
                "meta": {"time": datetime.now().strftime("%H:%M:%S")},
            }

            return template.render(**data)

        except Exception as e:
            logger.error(f"Failed to build media change prompt: {e}")
            return f"Event: Media Changed. Title: {template_data.get('current_media_title')}"
