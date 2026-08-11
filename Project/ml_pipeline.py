"""Evaluate Zonix's deterministic segment-ranking baseline.

This is deliberately an offline evaluation pipeline, not a trained model. It
validates that every selected segment comes from the catalog and rejects
likely-silent segments before ranking. DVC supplies repeatability and MLflow
records runs when the ML tooling is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from statistics import fmean
from typing import Any

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("sample_segments.jsonl"))
    parser.add_argument("--params", type=Path, default=Path("params.yaml"))
    parser.add_argument("--metrics", type=Path, default=Path("metrics.json"))
    parser.add_argument("--ranking", type=Path, default=Path("ranked_segments.json"))
    parser.add_argument(
        "--skip-mlflow",
        action="store_true",
        help="Run the deterministic evaluation without recording an MLflow run.",
    )
    return parser.parse_args()


def load_catalog(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    with path.open(encoding="utf-8") as catalog_file:
        for line_number, line in enumerate(catalog_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on catalog line {line_number}: {error}") from error

            segment_id = record.get("segment_id")
            tags = record.get("tags")
            if not isinstance(segment_id, str) or not segment_id.strip():
                raise ValueError(f"Catalog line {line_number} has no valid segment_id")
            if segment_id in seen_ids:
                raise ValueError(f"Duplicate segment_id: {segment_id}")
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                raise ValueError(f"Segment {segment_id} must have a string tags list")

            for field in ("silence_probability", "transition_score"):
                value = record.get(field)
                if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                    raise ValueError(f"Segment {segment_id} has invalid {field}")
            if not isinstance(record.get("relevant"), bool):
                raise ValueError(f"Segment {segment_id} must have a boolean relevant label")

            seen_ids.add(segment_id)
            records.append(record)

    if not records:
        raise ValueError("Catalog contains no segments")
    return records


def tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def evaluate(catalog: list[dict[str, Any]], params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float | int]]:
    baseline = params["baseline"]
    evaluation = params["evaluation"]
    promotion = params["promotion"]
    query_tokens = tokens(str(evaluation["query"]))
    top_k = int(evaluation["top_k"])
    max_silence = float(evaluation["max_silence_probability"])

    if not query_tokens:
        raise ValueError("evaluation.query must contain at least one word")
    if top_k < 1:
        raise ValueError("evaluation.top_k must be positive")
    if not 0 <= max_silence <= 1:
        raise ValueError("evaluation.max_silence_probability must be between 0 and 1")

    eligible: list[dict[str, Any]] = []
    for segment in catalog:
        if float(segment["silence_probability"]) > max_silence:
            continue
        overlap = len(query_tokens & tokens(" ".join(segment["tags"]))) / len(query_tokens)
        score = (
            overlap * float(baseline["prompt_overlap_weight"])
            + float(segment["transition_score"]) * float(baseline["transition_weight"])
            - float(segment["silence_probability"]) * float(baseline["silence_penalty"])
        )
        eligible.append({**segment, "baseline_score": round(score, 6)})

    eligible.sort(key=lambda item: (-item["baseline_score"], item["segment_id"]))
    selected = eligible[:top_k]
    selected_ids = {item["segment_id"] for item in selected}
    catalog_ids = {item["segment_id"] for item in catalog}
    relevant_count = sum(bool(item["relevant"]) for item in selected)

    metrics: dict[str, float | int] = {
        "catalog_size": len(catalog),
        "eligible_segments": len(eligible),
        "selected_segments": len(selected),
        "silence_rejection_rate": round(1 - len(eligible) / len(catalog), 6),
        "precision_at_k": round(relevant_count / len(selected), 6) if selected else 0.0,
        "mean_transition_score_at_k": round(
            fmean(float(item["transition_score"]) for item in selected), 6
        )
        if selected
        else 0.0,
        "catalog_integrity_rate": round(
            len(selected_ids & catalog_ids) / len(selected_ids), 6
        )
        if selected_ids
        else 1.0,
    }
    metrics["passes_quality_gate"] = int(
        metrics["precision_at_k"] >= float(promotion["min_precision_at_k"])
        and metrics["mean_transition_score_at_k"]
        >= float(promotion["min_mean_transition_score_at_k"])
        and metrics["catalog_integrity_rate"]
        >= float(promotion["required_catalog_integrity_rate"])
    )
    return selected, metrics


def flatten_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{section}.{name}": value
        for section, values in params.items()
        for name, value in values.items()
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"


def record_mlflow(
    params: dict[str, Any],
    metrics: dict[str, float | int],
    artifacts: list[Path],
    run_metadata: dict[str, str],
) -> None:
    try:
        import mlflow
    except ImportError as error:
        raise RuntimeError(
            "MLflow is not installed. Run `pip install -r requirements-ml.txt` "
            "or pass --skip-mlflow for a lightweight validation run."
        ) from error

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    else:
        mlflow.set_tracking_uri((Path("mlruns").resolve()).as_uri())
    mlflow.set_experiment("zonix-segment-ranking-baseline")

    with mlflow.start_run(run_name="deterministic-baseline"):
        mlflow.log_params({**flatten_params(params), **run_metadata})
        mlflow.log_metrics({name: float(value) for name, value in metrics.items()})
        for artifact in artifacts:
            mlflow.log_artifact(str(artifact))


def main() -> None:
    args = parse_args()
    with args.params.open(encoding="utf-8") as params_file:
        params = yaml.safe_load(params_file)
    if not isinstance(params, dict):
        raise ValueError("params.yaml must contain a mapping")

    ranking, metrics = evaluate(load_catalog(args.catalog), params)
    args.ranking.write_text(json.dumps(ranking, indent=2) + "\n", encoding="utf-8")
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    if not args.skip_mlflow:
        record_mlflow(
            params,
            metrics,
            [args.metrics, args.ranking],
            {
                "git_revision": git_revision(),
                "catalog_sha256": file_sha256(args.catalog),
                "catalog_path": str(args.catalog),
            },
        )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
