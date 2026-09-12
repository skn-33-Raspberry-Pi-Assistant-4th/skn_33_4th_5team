"""Run the final dynamic-mini-challenge evaluation without invoking RAG.

The script deliberately drives the public ChatResponse entry point so the
adapter is included in measurement. It records raw structured-output outcomes
separately from final QuizResponse outcomes and emits a reviewer-ready CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

from src.contracts import ChatCitation, ChatResponse, QuizEvidence, QuizQuestion
from src.rag_to_llm import (
    AnswerGeneratorSettings,
    HuggingFaceAnswerGenerator,
    HuggingFaceQuizTextGenerator,
    build_answer_generator,
)
from src.services.quiz_generator import QuizGenerator
from src.services.quiz_adapters import chat_response_to_quiz_request
from src.services.quiz_parser import QuizOutputError, parse_quiz_draft_response
from src.services.quiz_validation import (
    finalize_questions,
    supporting_quote_matches,
    validate_question_evidence,
    validate_question_structure,
)


def _percentile_nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(-(-len(ordered) * percentile // 100)) - 1))
    return ordered[index]


class RecordingQuizTextGenerator:
    """Measure one structured generation call without altering service logic."""

    def __init__(self, inner: HuggingFaceQuizTextGenerator) -> None:
        self.inner = inner
        self.calls = 0
        self.raw_output: str | None = None
        self.elapsed_ms: float | None = None

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        self.raw_output = self.inner.generate(messages)
        assert self.inner.last_result is not None
        self.elapsed_ms = self.inner.last_result.elapsed_ms
        return self.raw_output


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _chat_response(case: dict[str, Any]) -> ChatResponse:
    citations = [
        ChatCitation(
            citation_id=item["citation_id"],
            document_id=item["document_id"],
            chunk_id=item["chunk_id"],
            title="Raspberry Pi official documentation",
            publisher="Raspberry Pi Ltd",
            section="Evaluation fixture",
            source_url="https://www.raspberrypi.com/documentation/",
            source_anchor=None,
            document_version=None,
            published_at=None,
            updated_at=None,
            collected_at=date(2026, 9, 12),
            license="Evaluation fixture",
            quote=item["content"],
        )
        for item in case["evidence"]
    ]
    if citations:
        answer = " ".join([case["answer"], *[f"[{item.citation_id}]" for item in citations]])
        status = "answered"
    else:
        answer = case["answer"]
        status = "insufficient_evidence"
    return ChatResponse(
        schema_version="1.2.0",
        request_id=case["case_id"],
        status=status,
        language="ko",
        answer=answer,
        conditions=None,
        citations=citations,
        products=[],
        media=[],
        clarification_questions=[],
        warnings=[],
    )


def _draft_metrics(raw_output: str, evidence: list[QuizEvidence], quote_candidates: list[Any]) -> dict[str, Any]:
    """Inspect the generated draft using the same parser/validators as the service."""

    evidence_by_id = {item.citation_id: item for item in evidence}
    try:
        draft = parse_quiz_draft_response(raw_output)
    except QuizOutputError as exc:
        return {"parse_success": False, "parse_error": str(exc), "questions": []}

    quote_by_id = {item.quote_id: item for item in quote_candidates}
    questions: list[dict[str, Any]] = []
    valid_questions: list[QuizQuestion] = []
    for item in draft.questions:
        allowlist_violation = any(key not in evidence_by_id for key in item.evidence_ids)
        quote = quote_by_id.get(item.supporting_quote_id)
        mapping_failure = quote is None or item.evidence_ids != [quote.evidence_id]
        materialized = None
        if not mapping_failure:
            materialized = QuizQuestion(
                question_id=item.question_id,
                question=item.question,
                choices=item.choices,
                correct_choice_id=item.correct_choice_id,
                explanation=item.explanation,
                evidence_ids=item.evidence_ids,
                supporting_quotes=[quote.content],
            )
        structure_errors = validate_question_structure(materialized) if materialized else []
        evidence_errors = validate_question_evidence(materialized, evidence_by_id) if materialized else []
        if materialized and not structure_errors and not evidence_errors:
            valid_questions.append(materialized)
        questions.append({
            "question_id": item.question_id,
            "allowlist_violation": allowlist_violation,
            "quote_candidate_mapping_failure": mapping_failure,
            "structure_errors": structure_errors,
            "evidence_errors": evidence_errors,
            "quote_matches": bool(
                materialized and supporting_quote_matches(materialized.supporting_quotes[0], evidence_by_id[item.evidence_ids[0]].content)
            ),
        })
    deduplicated = finalize_questions(valid_questions, max_questions=3)
    return {
        "parse_success": True,
        "parse_error": None,
        "draft_status": draft.status,
        "questions": questions,
        "valid_question_count_before_finalizer": len(valid_questions),
        "duplicate_questions_removed": len(valid_questions) - len(deduplicated.questions),
    }


def run(dataset: Path, output: Path, review_csv: Path) -> dict[str, Any]:
    cases = _load_cases(dataset)
    root = Path(__file__).resolve().parents[1]
    settings = AnswerGeneratorSettings.from_env(root)
    answer_generator = build_answer_generator(settings)
    if not isinstance(answer_generator, HuggingFaceAnswerGenerator):
        raise RuntimeError("This evaluation requires the HuggingFace Qwen provider.")

    load_started = perf_counter()
    answer_generator._load_model()  # noqa: SLF001 - evaluation records cold-load separately.
    model_load_ms = (perf_counter() - load_started) * 1000
    recorded_generator = RecordingQuizTextGenerator(
        HuggingFaceQuizTextGenerator(answer_generator, max_new_tokens=1024)
    )
    quiz_generator = QuizGenerator(recorded_generator)

    rows: list[dict[str, Any]] = []
    for case in cases:
        chat = _chat_response(case)
        before_calls = recorded_generator.calls
        started = perf_counter()
        runtime_error: str | None = None
        try:
            response = quiz_generator.generate_from_chat_response(
                chat, max_questions=case["expected_max_questions"] or 1
            )
        except Exception as exc:  # Keep later fixtures measurable if one runtime call fails.
            response = None
            runtime_error = f"{type(exc).__name__}: {exc}"
        total_elapsed_ms = (perf_counter() - started) * 1000
        model_called = recorded_generator.calls > before_calls

        row: dict[str, Any] = {
            "case_id": case["case_id"],
            "category": case["category"],
            "gold_status": "available" if case["expected_min_questions"] else "insufficient_content",
            "expected_min_questions": case["expected_min_questions"],
            "expected_max_questions": case["expected_max_questions"],
            "model_called": model_called,
            "generation_elapsed_ms": recorded_generator.elapsed_ms if model_called else None,
            "pipeline_elapsed_ms": total_elapsed_ms,
            "runtime_error": runtime_error,
            "raw_output": recorded_generator.raw_output if model_called else None,
        }
        if response is None:
            row.update({"quiz_status": "runtime_error", "questions": [], "draft": None})
            rows.append(row)
            continue

        row["quiz_status"] = response.status
        row["questions"] = [item.model_dump(mode="json") for item in response.questions]
        request = chat_response_to_quiz_request(chat, max_questions=case["expected_max_questions"] or 1)
        request_evidence = request.evidence if request else []
        row["draft"] = _draft_metrics(recorded_generator.raw_output, request_evidence, request.quote_candidates) if model_called and request else None
        row["provided_within_expected_range"] = (
            response.status == "available"
            and case["expected_min_questions"] <= len(response.questions) <= case["expected_max_questions"]
        )
        rows.append(row)

    positive_rows = [row for row in rows if row["gold_status"] == "available"]
    negative_rows = [row for row in rows if row["gold_status"] == "insufficient_content"]
    called_rows = [row for row in rows if row["model_called"]]
    parsed_rows = [row for row in called_rows if row["draft"] and row["draft"]["parse_success"]]
    generation_latencies = [row["generation_elapsed_ms"] for row in called_rows if row["generation_elapsed_ms"] is not None]
    pipeline_latencies = [row["pipeline_elapsed_ms"] for row in rows]

    # Final quote content is server-materialized from quote candidates. Check its retained origin directly.
    final_questions = [question for row in rows for question in row["questions"]]
    draft_questions = [question for row in parsed_rows for question in row["draft"]["questions"]]
    materialized_draft_questions = [question for question in draft_questions if not question["quote_candidate_mapping_failure"]]
    structure_pass_questions = [question for question in materialized_draft_questions if not question["structure_errors"]]
    evidence_pass_questions = [question for question in structure_pass_questions if not question["evidence_errors"]]
    quote_match_total = 0
    quote_match_pass = 0
    for row in rows:
        evidence_by_id = {item["citation_id"]: item["content"] for item in next(case for case in cases if case["case_id"] == row["case_id"])["evidence"]}
        for question in row["questions"]:
            for evidence_id, quote in zip(question["evidence_ids"], question["supporting_quotes"]):
                quote_match_total += 1
                quote_match_pass += int(
                    evidence_id in evidence_by_id and supporting_quote_matches(quote, evidence_by_id[evidence_id])
                )

    true_positive = sum(row["gold_status"] == "available" and row["quiz_status"] == "available" for row in rows)
    false_positive = sum(row["gold_status"] == "insufficient_content" and row["quiz_status"] == "available" for row in rows)
    true_negative = sum(row["gold_status"] == "insufficient_content" and row["quiz_status"] == "insufficient_content" for row in rows)
    false_negative = sum(row["gold_status"] == "available" and row["quiz_status"] != "available" for row in rows)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0

    result = {
        "environment": {
            "model_id": settings.model_id,
            "load_in_4bit": settings.load_in_4bit,
            "do_sample": False,
            "structured_max_new_tokens": 1024,
            "model_load_ms": model_load_ms,
            "rag_retrieval_calls": 0,
            "retry_count": 0,
        },
        "dataset": {"path": str(dataset), "cases": len(rows), "positive_cases": len(positive_rows), "insufficient_cases": len(negative_rows)},
        "metrics": {
            "json_parse_success": {"passed": len(parsed_rows), "total": len(called_rows)},
            "structure_validation": {"passed": len(structure_pass_questions), "total": len(materialized_draft_questions)},
            "evidence_validation": {"passed": len(evidence_pass_questions), "total": len(structure_pass_questions)},
            "valid_quiz_provision": {"passed": true_positive, "total": len(positive_rows)},
            "average_valid_questions_per_positive_case": sum(len(row["questions"]) for row in positive_rows) / len(positive_rows),
            "allowlist_violations": sum(question["allowlist_violation"] for question in draft_questions),
            "quote_candidate_mapping_failures": sum(question["quote_candidate_mapping_failure"] for question in draft_questions),
            "supporting_quote_match": {"passed": quote_match_pass, "total": quote_match_total},
            "duplicate_questions_removed": sum(row["draft"]["duplicate_questions_removed"] for row in parsed_rows),
            "generation_failed_cases": sum(row["quiz_status"] == "generation_failed" for row in rows),
            "insufficient_content_cases": sum(row["quiz_status"] == "insufficient_content" for row in rows),
            "availability_classification": {
                "confusion_matrix": {"tp": true_positive, "fp": false_positive, "tn": true_negative, "fn": false_negative},
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "accuracy": (true_positive + true_negative) / len(rows),
            },
            "generation_latency_ms": {
                "average": sum(generation_latencies) / len(generation_latencies),
                "p50": _percentile_nearest_rank(generation_latencies, 50),
                "p95": _percentile_nearest_rank(generation_latencies, 95),
            },
            "pipeline_latency_ms": {
                "average": sum(pipeline_latencies) / len(pipeline_latencies),
                "p50": _percentile_nearest_rank(pipeline_latencies, 50),
                "p95": _percentile_nearest_rank(pipeline_latencies, 95),
            },
        },
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    review_csv.parent.mkdir(parents=True, exist_ok=True)
    with review_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "case_id", "category", "question_id", "question", "correct_choice_id", "correct_choice_text",
                "evidence_ids", "supporting_quotes", "qa_relevance", "single_clear_answer",
                "answer_directly_supported", "outside_knowledge_required", "choice_quality", "duplicate_fact",
                "reviewer", "notes",
            ],
        )
        writer.writeheader()
        for row in rows:
            for question in row["questions"]:
                correct = next(choice["text"] for choice in question["choices"] if choice["id"] == question["correct_choice_id"])
                writer.writerow({
                    "case_id": row["case_id"], "category": row["category"], "question_id": question["question_id"],
                    "question": question["question"], "correct_choice_id": question["correct_choice_id"],
                    "correct_choice_text": correct, "evidence_ids": "|".join(question["evidence_ids"]),
                    "supporting_quotes": "|".join(question["supporting_quotes"]), "qa_relevance": "pending",
                    "single_clear_answer": "pending", "answer_directly_supported": "pending",
                    "outside_knowledge_required": "pending", "choice_quality": "pending", "duplicate_fact": "pending",
                    "reviewer": "", "notes": "",
                })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("eval/quiz_generation_cases.v1.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("eval/results/quiz_generation_final.v1.json"))
    parser.add_argument("--review-csv", type=Path, default=Path("eval/results/quiz_human_review.v1.csv"))
    args = parser.parse_args()
    result = run(args.dataset, args.output, args.review_csv)
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
