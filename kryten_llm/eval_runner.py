"""Memory-quality evaluation runner (Sprint 12, Sortie 5, REQ-270–275).

Provides a programmatic interface to the full eval suite so that:
- ``kryten-llm memory eval`` can call it from the CLI.
- CI steps can invoke it without a config file.

The runner uses the same FakeEmbedder + FakeStore as the pytest eval suite,
so it requires no live NATS, Chroma, or pgvector connection.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "eval" / "fixtures"


@dataclass
class EvalReport:
    """Combined results from the full eval suite (REQ-270)."""

    retrieval_precision_at_5: float = 0.0
    retrieval_recall_at_5: float = 0.0
    retrieval_mrr: float = 0.0
    retrieval_baseline: float = 0.6
    retrieval_n: int = 0

    contradiction_precision: float = 0.0
    contradiction_recall: float = 0.0
    contradiction_recall_baseline: float = 0.70
    contradiction_n: int = 0

    disclosure_violations: int = 0
    disclosure_n: int = 0

    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        """True if every metric meets its baseline (REQ-272)."""
        retrieval_ok = self.retrieval_recall_at_5 >= self.retrieval_baseline
        contradiction_ok = self.contradiction_recall >= self.contradiction_recall_baseline
        disclosure_ok = self.disclosure_violations == 0
        return retrieval_ok and contradiction_ok and disclosure_ok and not self.errors

    def to_table(self) -> str:
        """Markdown-style summary table (REQ-270)."""

        def _row(name: str, value: str, baseline: str, ok: bool) -> str:
            status = "✓ PASS" if ok else "✗ FAIL"
            return f"| {name:<40} | {value:>10} | {baseline:>10} | {status} |"

        sep = "|-" + "-" * 40 + "-|-" + "-" * 10 + "-|-" + "-" * 10 + "-|-" + "-" * 7 + "-|"
        header = (
            "| "
            + "Metric".ljust(40)
            + " | "
            + "Value".rjust(10)
            + " | "
            + "Baseline".rjust(10)
            + " | Status  |"
        )
        rows = [
            header,
            sep,
            _row(
                "Retrieval recall@5",
                f"{self.retrieval_recall_at_5:.2%}",
                f"≥{self.retrieval_baseline:.0%}",
                self.retrieval_recall_at_5 >= self.retrieval_baseline,
            ),
            _row(
                "Retrieval precision@5",
                f"{self.retrieval_precision_at_5:.2%}",
                "—",
                True,
            ),
            _row(
                "Retrieval MRR",
                f"{self.retrieval_mrr:.3f}",
                "—",
                True,
            ),
            _row(
                "Contradiction recall (heuristic)",
                f"{self.contradiction_recall:.2%}",
                f"≥{self.contradiction_recall_baseline:.0%}",
                self.contradiction_recall >= self.contradiction_recall_baseline,
            ),
            _row(
                "Contradiction precision (heuristic)",
                f"{self.contradiction_precision:.2%}",
                "—",
                True,
            ),
            _row(
                "Disclosure violations",
                str(self.disclosure_violations),
                "0",
                self.disclosure_violations == 0,
            ),
        ]
        status_line = "\nResult: " + ("ALL PASS ✓" if self.all_pass else "FAILURES DETECTED ✗")
        if self.errors:
            status_line += "\nErrors:\n" + "\n".join(f"  {e}" for e in self.errors)
        return "\n".join(rows) + status_line

    def to_json(self) -> str:
        """Machine-readable JSON report (REQ-274)."""
        return json.dumps(
            {
                "retrieval": {
                    "recall_at_5": self.retrieval_recall_at_5,
                    "precision_at_5": self.retrieval_precision_at_5,
                    "mrr": self.retrieval_mrr,
                    "baseline": self.retrieval_baseline,
                    "n_scenarios": self.retrieval_n,
                    "pass": self.retrieval_recall_at_5 >= self.retrieval_baseline,
                },
                "contradiction": {
                    "precision": self.contradiction_precision,
                    "recall": self.contradiction_recall,
                    "recall_baseline": self.contradiction_recall_baseline,
                    "n_scenarios": self.contradiction_n,
                    "pass": self.contradiction_recall >= self.contradiction_recall_baseline,
                },
                "disclosure": {
                    "violations": self.disclosure_violations,
                    "n_scenarios": self.disclosure_n,
                    "pass": self.disclosure_violations == 0,
                },
                "all_pass": self.all_pass,
                "elapsed_seconds": self.elapsed_seconds,
                "errors": self.errors,
            },
            indent=2,
        )


async def run_eval_suite(
    fixture_dir: Path | None = None,
    retrieval_k: int = 5,
    retrieval_baseline: float = 0.6,
    contradiction_recall_baseline: float = 0.70,
) -> EvalReport:
    """Run all memory-quality eval checks and return an ``EvalReport`` (REQ-270–275).

    Uses FakeEmbedder + FakeStore — no live services required (REQ-275).
    Completes in < 30 seconds with mocked components.
    """

    from kryten_llm.components.context.base import ContextRequest
    from tests.eval.harness import (
        FakeEmbedder,
        FakeStore,
        FixtureLoader,
        StaticModerationGate,
        make_provider,
        seed_store,
    )
    from tests.eval.scorers import score_contradictions, score_retrieval

    fixture_dir = fixture_dir or _DEFAULT_FIXTURE_DIR
    report = EvalReport(
        retrieval_baseline=retrieval_baseline,
        contradiction_recall_baseline=contradiction_recall_baseline,
    )
    t0 = time.monotonic()

    embedder = FakeEmbedder()

    # ------------------------------------------------------------------
    # 1. Retrieval scoring
    # ------------------------------------------------------------------
    try:
        retrieval_scenarios = FixtureLoader.load(fixture_dir / "retrieval.jsonl")
        store = FakeStore()
        for sc in retrieval_scenarios:
            await seed_store(store, sc.facts, embedder)
        ret_report = await score_retrieval(
            retrieval_scenarios,
            store,
            embedder,
            k=retrieval_k,
            baseline_precision=retrieval_baseline,
        )
        report.retrieval_precision_at_5 = ret_report.precision_at_k
        report.retrieval_recall_at_5 = ret_report.recall_at_k
        report.retrieval_mrr = ret_report.mean_reciprocal_rank
        report.retrieval_n = ret_report.n_scenarios
    except Exception as exc:
        report.errors.append(f"Retrieval scoring failed: {exc}")

    # ------------------------------------------------------------------
    # 2. Contradiction scoring
    # ------------------------------------------------------------------
    try:
        contra_scenarios = FixtureLoader.load(fixture_dir / "contradiction.jsonl")
        c_store = FakeStore()
        c_provider = make_provider(c_store, embedder)
        c_provider._contradiction_method = "heuristic"
        c_report = await score_contradictions(contra_scenarios, c_provider, method="heuristic")
        report.contradiction_precision = c_report.precision
        report.contradiction_recall = c_report.recall
        report.contradiction_n = c_report.n_scenarios
    except Exception as exc:
        report.errors.append(f"Contradiction scoring failed: {exc}")

    # ------------------------------------------------------------------
    # 3. Disclosure safety
    # ------------------------------------------------------------------
    try:
        disc_scenarios = FixtureLoader.load(fixture_dir / "disclosure.jsonl")
        report.disclosure_n = len(disc_scenarios)
        violations = 0
        for sc in disc_scenarios:
            d_store = FakeStore()
            d_provider = make_provider(d_store, embedder)
            d_provider._cross_user_enabled = True
            d_provider._topical_enabled = True

            normal_facts = sc.facts_normal or sc.facts
            await seed_store(d_store, normal_facts, embedder)
            for fact in sc.facts_silenced:
                await seed_store(d_store, [fact], embedder)

            silenced_set = sc.silenced_users
            if silenced_set is None:
                d_provider._mod_gate = StaticModerationGate(None)
                d_provider._gate_fail_closed = True
            else:
                d_provider._mod_gate = StaticModerationGate(set(silenced_set))
                d_provider._gate_fail_closed = True

            req = ContextRequest(
                username="__eval__", message=sc.query, trigger=None, channel="eval"
            )
            frags = await d_provider.provide(req)
            for frag in frags:
                text = frag.text or ""
                for user in silenced_set or []:
                    if user.lower() in text.lower():
                        violations += 1
                        report.errors.append(
                            f"Disclosure: '{user}' in fragment '{frag.name}' "
                            f"(scenario: {sc.label!r})"
                        )

        report.disclosure_violations = violations
    except Exception as exc:
        report.errors.append(f"Disclosure check failed: {exc}")

    report.elapsed_seconds = time.monotonic() - t0
    return report
