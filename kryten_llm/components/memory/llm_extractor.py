"""LLM-driven fact extractor (Phase 7f, REQ-010 to REQ-015).

The :class:`LLMFactExtractor` sends a short look-back window of chat to a
*dedicated* :class:`~kryten_llm.components.llm_manager.LLMManager` and asks it
to emit paraphrased, attributed, scored candidate facts as strict JSON. It is a
**pure transform** — no datastore reads/writes, no ``novelty``/``importance``
(those are the provider's job, REQ-010/REQ-032). It never raises into the
caller: on unrecoverable output it drops the batch and logs (fail-open).
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader

from kryten_llm.components.memory.extractor import (
    FACT_CATEGORIES,
    ExtractedFact,
    register_extractor,
)
from kryten_llm.models.phase3 import LLMRequest

if TYPE_CHECKING:
    from kryten_llm.components.llm_manager import LLMManager
    from kryten_llm.models.config import ExtractorConfig

# ---------------------------------------------------------------------------
# JSON output contract (REQ-012)
# ---------------------------------------------------------------------------

#: JSON schema used for native structured output (REQ-014, json_schema mode).
FACTS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_user": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": sorted(FACT_CATEGORIES),
                    },
                    "summary": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "sentiment": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_message_index": {"type": "integer", "minimum": 0},
                },
                "required": [
                    "target_user",
                    "category",
                    "summary",
                    "confidence",
                    "sentiment",
                    "evidence_message_index",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}

#: Maximum characters kept in a fact ``summary`` (GUD-002).
MAX_SUMMARY_LENGTH = 120

_TEMPLATE_SYSTEM = "fact_extraction_system.j2"
_TEMPLATE_USER = "fact_extraction_user.j2"
_TEMPLATE_REPAIR = "fact_extraction_repair.j2"

# Inline fallback used only when templates cannot be loaded at runtime.
_SYSTEM_PROMPT_FALLBACK = (
    "You extract durable, paraphrased facts about chat users from a "
    "short window of multi-user chat. Extract facts about ANY user visible in "
    "the window. Reply with ONLY strict JSON: "
    '{"facts": [{"target_user": str, "category": str, "summary": str, '
    '"confidence": float, "sentiment": float, "evidence_message_index": int}]}. '
    'Emit "NO FACTS" if none are present.'
)


def _response_format() -> dict[str, Any]:
    """Return the OpenAI-compatible ``response_format`` for json_schema mode."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "fact_extraction",
            "strict": True,
            "schema": FACTS_JSON_SCHEMA,
        },
    }


@register_extractor("llm")
class LLMFactExtractor:
    """Extracts scored facts via a dedicated LLM connection.

    Implements the ``FactExtractor`` Protocol (``extract`` is async and pure).
    """

    id = "llm"

    def __init__(
        self,
        manager: "LLMManager",
        cfg: "ExtractorConfig",
        logger: logging.Logger | None = None,
        templates_dir: str | None = None,
    ) -> None:
        self._manager = manager
        self._cfg = cfg
        self._log = logger or logging.getLogger(__name__)

        # structured-output mode may be downgraded once at runtime (auto path).
        self._mode = cfg.structured_output.mode
        self._downgraded = False

        # Jinja2 environment for prompt templates.
        resolved_dir = self._resolve_templates_dir(templates_dir)
        self._jinja = Environment(
            loader=FileSystemLoader(resolved_dir), trim_blocks=True, lstrip_blocks=True
        )

    @staticmethod
    def _resolve_templates_dir(templates_dir: str | None) -> str:
        """Return the best available templates directory."""
        if templates_dir and os.path.isdir(templates_dir):
            return templates_dir
        # Fallback: <package_root>/templates (works when running from the repo).
        package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pkg_dir = os.path.join(package_root, "templates")
        if os.path.isdir(pkg_dir):
            return pkg_dir
        # Last resort: cwd/templates
        return "templates"

    # ------------------------------------------------------------------
    # FactExtractor interface
    # ------------------------------------------------------------------

    async def extract(self, messages: list[dict[str, Any]], user: str) -> list[ExtractedFact]:
        """Extract scored facts about *user* from the look-back *messages*.

        Pure: no side effects. Returns ``[]`` on any unrecoverable condition.
        """
        window = self._normalise_window(messages)
        if not window:
            return []

        user_prompt = self._render_user_prompt(window)

        use_schema = self._mode in ("json_schema", "auto") and not self._downgraded
        content = await self._call(user_prompt, use_schema=use_schema)

        # auto: one downgrade to prompt mode if the schema attempt produced nothing.
        if content is None and self._mode == "auto" and use_schema and not self._downgraded:
            self._downgraded = True
            self._log.info(
                "LLMFactExtractor: structured_output 'auto' downgraded to 'prompt' "
                "(endpoint did not return usable json_schema output)"
            )
            content = await self._call(user_prompt, use_schema=False)

        if content is None:
            self._log.warning("LLMFactExtractor: no response from extractor LLM; dropping batch")
            return []

        parsed = self._parse(content)
        if parsed is None:
            # Single bounded repair (REQ-013).
            repair = await self._repair(user_prompt, content)
            if repair is not None:
                parsed = self._parse(repair)
        if parsed is None:
            self._log.warning(
                "LLMFactExtractor: unrepairable JSON from extractor LLM; dropping batch"
            )
            return []

        return self._to_facts(parsed, window, user)

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    async def _call(self, user_prompt: str, use_schema: bool) -> str | None:
        """Call the dedicated manager; return content string or ``None``.

        ``temperature``/``max_tokens`` are left unset so each extractor provider
        uses its own configured sampling values (e.g. the low temperature from
        GUD-001), even across a fallback chain.
        """
        system_prompt = self._render_system_prompt()
        try:
            request = LLMRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=_response_format() if use_schema else None,
            )
            response = await self._manager.generate_response(request)
        except Exception as exc:  # never raise into the caller
            self._log.warning(f"LLMFactExtractor: extractor call failed: {exc}")
            return None
        if response is None:
            return None
        return response.content

    async def _repair(self, user_prompt: str, bad_output: str) -> str | None:
        """One corrective re-prompt for malformed JSON (REQ-013)."""
        repair_prompt = self._render_repair_prompt(user_prompt, bad_output)
        system_prompt = self._render_system_prompt()
        try:
            request = LLMRequest(
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                response_format=(
                    _response_format()
                    if (self._mode in ("json_schema", "auto") and not self._downgraded)
                    else None
                ),
            )
            response = await self._manager.generate_response(request)
        except Exception as exc:
            self._log.warning(f"LLMFactExtractor: repair call failed: {exc}")
            return None
        return response.content if response is not None else None

    # ------------------------------------------------------------------
    # Prompt rendering
    # ------------------------------------------------------------------

    def _render_system_prompt(self) -> str:
        """Render the fact-extraction system prompt from template."""
        try:
            tmpl = self._jinja.get_template(_TEMPLATE_SYSTEM)
            return tmpl.render(
                categories=sorted(FACT_CATEGORIES),
                max_summary_length=MAX_SUMMARY_LENGTH,
            ).strip()
        except Exception as exc:
            self._log.warning(f"LLMFactExtractor: failed to render system template: {exc}")
            return _SYSTEM_PROMPT_FALLBACK

    def _render_user_prompt(self, window: list[dict[str, Any]]) -> str:
        """Render the per-batch user prompt from template."""
        try:
            tmpl = self._jinja.get_template(_TEMPLATE_USER)
            return tmpl.render(window=window).strip()
        except Exception as exc:
            self._log.warning(f"LLMFactExtractor: failed to render user template: {exc}")
            return self._fallback_user_prompt(window)

    def _render_repair_prompt(self, original_request: str, bad_output: str) -> str:
        """Render the repair re-prompt from template."""
        try:
            tmpl = self._jinja.get_template(_TEMPLATE_REPAIR)
            return tmpl.render(
                original_request=original_request,
                bad_output=bad_output[:2000],
            ).strip()
        except Exception as exc:
            self._log.warning(f"LLMFactExtractor: failed to render repair template: {exc}")
            return (
                "Your previous reply was not valid JSON. "
                "Reply again with ONLY the strict JSON object described earlier.\n\n"
                f"Original request:\n{original_request}\n\nYour invalid reply:\n{bad_output[:2000]}"
            )

    # ------------------------------------------------------------------
    # Parsing / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        """Best-effort slice of the first ``{...}`` JSON object from *text*."""
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + 1]

    # Sentinel emitted by prompt-mode models when no facts are present (see _SYSTEM_PROMPT).
    _NO_FACTS_SENTINEL = "NO FACTS"

    def _parse(self, content: str) -> list[dict[str, Any]] | None:
        """Parse and shallow-validate the ``facts`` array. ``None`` on failure.

        Returns ``[]`` (empty, not a failure) when the model emits the
        ``NO FACTS`` sentinel defined in ``_SYSTEM_PROMPT``.
        """
        if not content or not content.strip():
            return None
        candidate = content.strip()
        # Prompt-mode models may emit the sentinel instead of JSON.
        if self._NO_FACTS_SENTINEL in candidate.upper():
            return []
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            sliced = self._extract_json_object(candidate)
            if sliced is None:
                return None
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                return None
        if not isinstance(obj, dict):
            return None
        facts = obj.get("facts")
        if not isinstance(facts, list):
            return None
        return facts

    def _to_facts(
        self, raw_facts: list[dict[str, Any]], window: list[dict[str, Any]], focus_user: str
    ) -> list[ExtractedFact]:
        """Validate raw fact dicts into :class:`ExtractedFact` records."""
        out: list[ExtractedFact] = []
        cap = self._cfg.cadence.max_facts_per_batch
        for raw in raw_facts:
            if len(out) >= cap:
                break
            if not isinstance(raw, dict):
                continue

            target = str(raw.get("target_user", "")).strip()
            category = str(raw.get("category", "")).strip().lower()
            summary = str(raw.get("summary", "")).strip()

            # REQ-015: drop facts missing required text fields.
            if not target or not category or not summary:
                continue
            if category not in FACT_CATEGORIES:
                category = "misc"

            summary = summary[:MAX_SUMMARY_LENGTH]
            confidence = self._clamp01(raw.get("confidence"))
            sentiment = self._clamp01(raw.get("sentiment"), default=0.5)
            evidence = self._resolve_evidence(raw.get("evidence_message_index"), window)

            out.append(
                ExtractedFact(
                    target_user=target,
                    category=category,
                    summary=summary,
                    confidence=confidence,
                    sentiment=sentiment,
                    evidence=evidence,
                )
            )
        return out

    @staticmethod
    def _clamp01(value: Any, default: float = 0.0) -> float:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return default
        if f < 0.0:
            return 0.0
        if f > 1.0:
            return 1.0
        return f

    @staticmethod
    def _resolve_evidence(index: Any, window: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            idx = int(index)
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(window):
            msg = window[idx]
            return {
                "index": idx,
                "time": msg.get("time", ""),
                "message": str(msg.get("message", ""))[:200],
            }
        return {"index": idx, "time": "", "message": ""}

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_window(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        window: list[dict[str, Any]] = []
        for m in messages:
            text = str(m.get("message", "")).strip()
            if not text:
                continue
            window.append(
                {
                    "username": str(m.get("username", "")),
                    "message": text,
                    "time": m.get("time", ""),
                }
            )
        return window

    @staticmethod
    def _build_user_prompt(window: list[dict[str, Any]], focus_user: str) -> str:  # pragma: no cover  # noqa: ARG002
        """Deprecated static fallback — superseded by _render_user_prompt."""
        lines = ["Chat window (index: author: message):"]
        for i, m in enumerate(window):
            lines.append(f"{i}: {m['username']}: {m['message']}")
        lines.append("")
        lines.append(
            "Extract durable facts about any user visible above. "
            "Attribute each fact to the correct author. "
            "Use the message index for evidence_message_index."
        )
        return "\n".join(lines)

    @staticmethod
    def _fallback_user_prompt(window: list[dict[str, Any]]) -> str:
        """Plain-text fallback if the user template cannot be rendered."""
        lines = ["Chat window (index: author: message):"]
        for i, m in enumerate(window):
            lines.append(f"{i}: {m['username']}: {m['message']}")
        lines.append("")
        lines.append(
            "Extract durable facts about any user visible above. "
            "Attribute each fact to the correct author. "
            "Use the message index for evidence_message_index."
        )
        return "\n".join(lines)
