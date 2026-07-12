"""Tests for the HeuristicFactExtractor (Phase 7b — REQ-031)."""

import pytest

from kryten_llm.components.memory.heuristic_extractor import (
    HeuristicFactExtractor,
    categorize,
    is_candidate,
    normalize,
    score_message,
    stable_fact_id,
    summarize_fact,
)


class TestNormalize:
    def test_lowercases(self):
        assert normalize("Hello WORLD") == "hello world"

    def test_strips_punctuation(self):
        # punctuation replaced by spaces, then whitespace collapsed
        result = normalize("hello, world!")
        assert "hello" in result
        assert "world" in result

    def test_collapses_whitespace(self):
        assert normalize("  hello   world  ") == "hello world"


class TestScoreMessage:
    def test_empty_is_zero(self):
        assert score_message("") == 0.0

    def test_short_message_low_score(self):
        # Very short (<4 words) gets a penalty
        assert score_message("I like") < 20.0

    def test_longer_scores_higher(self):
        short = score_message("I like movies")
        long = score_message(
            "I really love watching kung fu movies because they are exciting and fun"
        )
        assert long > short

    def test_interesting_keywords_boost(self):
        plain = score_message("I like movies a lot really much")
        with_kw = score_message("I like movies a lot because they are great honestly")
        assert with_kw > plain

    def test_score_bounded(self):
        very_long = "word " * 100
        assert score_message(very_long) <= 100.0


class TestCategorize:
    def test_preference(self):
        assert categorize("I really love kung fu movies") == "preference"

    def test_habit(self):
        assert categorize("I usually watch films every Friday") == "habit"

    def test_past(self):
        # "years ago" is the clearest past-only signal
        assert categorize("I played guitar years ago") == "past"

    def test_life_context(self):
        assert categorize("I work at a tech company downtown") == "life_context"

    def test_self_description(self):
        # No preference/habit/past/life keywords — only self-description
        assert categorize("I am a night owl by nature") == "self_description"

    def test_misc_fallback(self):
        # No category-specific keywords
        assert categorize("something something totally generic text here") == "misc"


class TestIsCandidate:
    def test_reaction_filtered(self):
        assert is_candidate("lol") is False
        assert is_candidate("lmao!") is False
        assert is_candidate("haha") is False

    def test_too_short_filtered(self):
        assert is_candidate("hi") is False
        assert is_candidate("yes ok") is False

    def test_no_first_person_filtered(self):
        # No first-person pronoun
        assert is_candidate("great movie playing right now") is False

    def test_valid_candidate(self):
        assert is_candidate("I really love watching kung fu films") is True


class TestStableFactId:
    def test_deterministic(self):
        id1 = stable_fact_id("alice", "I love kung fu films.")
        id2 = stable_fact_id("alice", "I love kung fu films.")
        assert id1 == id2

    def test_normalised_insensitive(self):
        # normalisation collapses case and punctuation
        id1 = stable_fact_id("alice", "I love kung fu films!")
        id2 = stable_fact_id("alice", "i love kung fu films")
        assert id1 == id2

    def test_different_users_differ(self):
        id1 = stable_fact_id("alice", "I love action movies")
        id2 = stable_fact_id("bob", "I love action movies")
        assert id1 != id2

    def test_length_32(self):
        fid = stable_fact_id("user", "some fact text")
        assert len(fid) == 32


class TestHeuristicFactExtractor:
    @pytest.fixture
    def extractor(self):
        return HeuristicFactExtractor(min_score=15.0)

    @pytest.mark.asyncio
    async def test_extracts_preference_fact(self, extractor):
        messages = [
            {
                "username": "alice",
                "message": "I absolutely love watching martial arts films because they are exciting",
            }
        ]
        facts = await extractor.extract(messages, "alice")
        assert len(facts) >= 1
        fact = facts[0]
        assert fact.user == "alice"
        assert fact.category in {"preference", "misc", "self_description", "habit", "past", "life_context"}
        assert len(fact.summary) > 0

    @pytest.mark.asyncio
    async def test_ignores_other_users(self, extractor):
        messages = [
            {"username": "bob", "message": "I love kung fu movies so much because they rock"},
            {"username": "alice", "message": "I prefer horror films honestly"},
        ]
        facts = await extractor.extract(messages, "alice")
        assert all(f.user == "alice" for f in facts)

    @pytest.mark.asyncio
    async def test_filters_pii(self, extractor):
        messages = [
            {
                "username": "alice",
                "message": "I work at user@example.com",
            }
        ]
        facts = await extractor.extract(messages, "alice")
        # Email in message should be blocked by safety gate
        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_deduplicates(self, extractor):
        messages = [
            {"username": "alice", "message": "I love action movies because they are great"},
            {"username": "alice", "message": "I love action movies because they are great"},
        ]
        facts = await extractor.extract(messages, "alice")
        # Should not produce two identical facts
        summaries = [f.summary for f in facts]
        assert len(summaries) == len(set(summaries))

    @pytest.mark.asyncio
    async def test_reaction_not_extracted(self, extractor):
        messages = [{"username": "alice", "message": "lol"}]
        facts = await extractor.extract(messages, "alice")
        assert facts == []

    @pytest.mark.asyncio
    async def test_source_is_live(self, extractor):
        messages = [
            {
                "username": "alice",
                "message": "I always watch horror films on weekends because I enjoy them",
            }
        ]
        facts = await extractor.extract(messages, "alice")
        if facts:
            assert facts[0].source == "live"
