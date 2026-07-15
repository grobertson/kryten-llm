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
from typing import TYPE_CHECKING, Any

from kryten_llm.components.memory.extractor import FACT_CATEGORIES, ExtractedFact
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


_SYSTEM_PROMPT = (
    "You extract durable, paraphrased facts about a specific chat user from a "
    "short window of multi-user chat. Attribute each fact to the user it is "
    "genuinely about. Reply with ONLY a strict JSON object matching this shape:\n"
    '{"facts": [{"target_user": str, "category": one of '
    "[preference|habit|past|life_context|self_description|misc], "
    '"summary": str, "confidence": number 0-1, "sentiment": number 0-1, '
    '"evidence_message_index": int}]}\n'
    "confidence = certainty the fact is really about target_user. "
    "sentiment = affect (1 positive, 0 negative, 0.5 neutral). "
    "summary must be a short third-person paraphrase (<= 120 chars) and must "
    "NOT invent personal data. Emit no facts if none are clearly present. "
    "Do not wrap the JSON in markdown or prose."
)


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
    ) -> None:
        self._manager = manager
        self._cfg = cfg
        self._log = logger or logging.getLogger(__name__)

        # structured-output mode may be downgraded once at runtime (auto path).
        self._mode = cfg.structured_output.mode
        self._downgraded = False
        self._focus_only = True  # MVP: facts limited to the focus user.

        # Representative sampling params for the extractor request. The provider
        # temperature is otherwise ignored by LLMManager (it uses the request's).
        order = manager._get_provider_priority(None)
        if order and order[0] in manager.providers:
            rep = manager.providers[order[0]]
        elif manager.providers:
            rep = next(iter(manager.providers.values()))
        else:  # pragma: no cover - guarded upstream
            rep = None
        self._temperature = rep.temperature if rep is not None else 0.1
        self._max_tokens = rep.max_tokens if rep is not None else 800

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

        user_prompt = self._build_user_prompt(window, user)

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
        """Call the dedicated manager; return content string or ``None``."""
        try:
            request = LLMRequest(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
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
        repair_prompt = (
            "Your previous reply was not valid JSON matching the required schema. "
            "Reply again with ONLY the strict JSON object described earlier — no "
            "markdown, no prose.\n\n"
            f"Original request:\n{user_prompt}\n\n"
            f"Your invalid reply:\n{bad_output[:2000]}"
        )
        try:
            request = LLMRequest(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=repair_prompt,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
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

    def _parse(self, content: str) -> list[dict[str, Any]] | None:
        """Parse and shallow-validate the ``facts`` array. ``None`` on failure."""
        if not content or not content.strip():
            return None
        candidate = content.strip()
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
            if self._focus_only and target.lower() != focus_user.lower():
                continue

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
    def _build_user_prompt(window: list[dict[str, Any]], focus_user: str) -> str:
        lines = [f"Focus user: {focus_user}", "", "Chat window (index: author: message):"]
        for i, m in enumerate(window):
            lines.append(f"{i}: {m['username']}: {m['message']}")
        lines.append("")
        lines.append(
            f"Extract durable facts about {focus_user} as the JSON object described. "
            "Use the message index for evidence_message_index."
        )
        return "\n".join(lines)
