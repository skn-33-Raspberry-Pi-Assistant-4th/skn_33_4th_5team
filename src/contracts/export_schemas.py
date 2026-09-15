"""Export the canonical Pydantic contracts as JSON Schema Draft 2020-12 files."""
from __future__ import annotations

import json
from pathlib import Path

from .models import ChatResponse, ConditionPayload, QuizResponse, SearchResponse


def export_schemas(output_dir: str | Path | None = None) -> list[Path]:
    destination = Path(output_dir) if output_dir else Path(__file__).resolve().parents[2] / "docs" / "schemas"
    destination.mkdir(parents=True, exist_ok=True)
    schema_models = {
        "condition.schema.json": ConditionPayload,
        "search-response.schema.json": SearchResponse,
        "chat-response.schema.json": ChatResponse,
        "quiz-response.schema.json": QuizResponse,
    }
    written: list[Path] = []
    for filename, model in schema_models.items():
        path = destination / filename
        payload = model.model_json_schema()
        payload["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for schema_path in export_schemas():
        print(schema_path)
