"""Tests for the pgvector ``_build_where`` operator translation.

Sprint 8, Sortie 0 (REQ-041): ``$in`` / ``$ne`` operators, fully parameterised
(no interpolation — OWASP A03). ``_build_where`` is a pure static method, so no
database is required.
"""

from __future__ import annotations

from kryten_llm.components.memory.vector_store import PgVectorStore


class TestBuildWhere:
    def test_scalar_user_equality_unchanged(self):
        sql, params, nxt = PgVectorStore._build_where({"user": "alice"}, 2)
        assert sql == "WHERE username = $2"
        assert params == ["alice"]
        assert nxt == 3

    def test_scalar_metadata_equality_unchanged(self):
        sql, params, _ = PgVectorStore._build_where({"category": "preference"}, 2)
        assert sql == "WHERE (metadata ->> $2) = $3"
        assert params == ["category", "preference"]

    def test_user_in_operator(self):
        sql, params, nxt = PgVectorStore._build_where({"user": {"$in": ["a", "b"]}}, 2)
        assert sql == "WHERE username = ANY($2)"
        assert params == [["a", "b"]]
        assert nxt == 3

    def test_user_ne_operator(self):
        sql, params, nxt = PgVectorStore._build_where({"user": {"$ne": "carol"}}, 2)
        assert sql == "WHERE username <> $2"
        assert params == ["carol"]
        assert nxt == 3

    def test_metadata_in_operator(self):
        sql, params, _ = PgVectorStore._build_where({"category": {"$in": ["a", "b"]}}, 2)
        assert sql == "WHERE (metadata ->> $2) = ANY($3)"
        assert params == ["category", ["a", "b"]]

    def test_empty_where(self):
        sql, params, nxt = PgVectorStore._build_where({}, 2)
        assert sql == ""
        assert params == []
        assert nxt == 2

    def test_injection_value_is_bound_not_interpolated(self):
        malicious = "'; DROP TABLE user_facts; --"
        sql, params, _ = PgVectorStore._build_where({"user": {"$ne": malicious}}, 2)
        # The value never appears in the SQL string; it is a bound parameter.
        assert malicious not in sql
        assert sql == "WHERE username <> $2"
        assert params == [malicious]

    def test_in_and_ne_combine(self):
        sql, params, nxt = PgVectorStore._build_where({"user": {"$in": ["a"], "$ne": "b"}}, 2)
        assert sql == "WHERE username = ANY($2) AND username <> $3"
        assert params == [["a"], "b"]
        assert nxt == 4
