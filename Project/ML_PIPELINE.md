# Zonix ML evaluation baseline

This directory does **not** contain a trained AI DJ model. It contains a
small, deterministic ranking baseline that makes the next ML work measurable.
It scores catalog segments by prompt-tag overlap and transition quality, then
rejects segments whose silence probability exceeds the configured threshold.

The committed `sample_segments.jsonl` is synthetic test data. It proves the
pipeline wiring only; it must not be reported as real model performance.

## Run it

Use Python 3.11 in a separate environment from the API:

```powershell
python -m venv .ml-venv
.\.ml-venv\Scripts\Activate.ps1
python -m pip install --requirement requirements-ml.txt
dvc repro
dvc metrics show
mlflow ui --backend-store-uri ./mlruns
```

Commit the generated `dvc.lock` and reviewed `metrics.json`; do not commit the
local DVC cache, MLflow store, or generated ranking artifact.

MLflow stores runs locally in `mlruns/` unless `MLFLOW_TRACKING_URI` points to
a shared tracking server. Each run records the Git revision, catalog SHA-256,
parameters, metrics, and ranking artifacts so results remain traceable to their
exact code and input data. DVC has no fake remote configured; add an approved
object-store remote only when the team has a real, licensed dataset.

For a fast code-path check without installing MLflow or DVC:

```powershell
python ml_pipeline.py --skip-mlflow
```

## Input contract

Each JSONL row represents one real catalog segment and must contain:

- `segment_id`: stable, unique identifier.
- `track_id`: source-track identifier.
- `tags`: prompt-search terms produced by a documented feature pipeline.
- `silence_probability`: number from 0 to 1.
- `transition_score`: number from 0 to 1.
- `relevant`: human evaluation label for the configured query.

Real data must also have provenance and license metadata before it is added.
Do not put copyrighted audio in normal Git history; use an approved DVC remote
or object storage.

## Metrics

- `precision_at_k`: fraction of selected segments labeled relevant.
- `mean_transition_score_at_k`: average transition score of selected segments.
- `silence_rejection_rate`: fraction filtered by the silence guard.
- `catalog_integrity_rate`: fraction of returned IDs that exist in the input
  catalog. This must remain 1.0 and prevents invented segment IDs.
- `passes_quality_gate`: 1 only when every threshold in `params.yaml` is met.
  Passing on the synthetic sample validates wiring only and never promotes a
  production model.

The next legitimate ML milestone is to replace prompt-tag overlap with a
versioned embedding/ranking model, evaluate it against this baseline on a
licensed labeled dataset, and promote it only when the reviewed thresholds are
met and it improves on the baseline.
