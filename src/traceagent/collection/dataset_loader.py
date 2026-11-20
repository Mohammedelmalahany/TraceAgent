"""Load SWE-bench Lite and cache it as a local jsonl file.

Order of sources:
    1. cached file  DATA_DIR/raw/swe_bench_lite.jsonl
    2. HuggingFace  (DATASET_NAME / DATASET_SPLIT)
    3. LOCAL_DATASET_PATH  (e.g. XAgent's swebench_lite_test.jsonl) as a fallback
"""

import json
from collections import Counter
from pathlib import Path

from traceagent.helpers.config import Settings
from traceagent.helpers.logging import get_logger
from traceagent.models.instance import Instance

log = get_logger(__name__)

CACHE_FILE_NAME = "swe_bench_lite.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _download_from_hf(settings: Settings) -> list[dict]:
    from datasets import load_dataset  # imported lazily: heavy import

    log.info("Downloading %s [%s] from HuggingFace...", settings.DATASET_NAME, settings.DATASET_SPLIT)
    ds = load_dataset(settings.DATASET_NAME, split=settings.DATASET_SPLIT)
    return [dict(row) for row in ds]


def load_instances(
    settings: Settings,
    limit: int | None = None,
    instance_ids: list[str] | None = None,
) -> list[Instance]:
    cache = settings.raw_dir / CACHE_FILE_NAME
    if cache.exists():
        rows = _read_jsonl(cache)
        log.info("Loaded %d rows from cache %s", len(rows), cache)
    else:
        try:
            rows = _download_from_hf(settings)
        except Exception as exc:  # network / HF errors
            if not settings.LOCAL_DATASET_PATH:
                raise
            log.warning("HuggingFace failed (%s); using local fallback %s", exc, settings.LOCAL_DATASET_PATH)
            rows = _read_jsonl(settings.LOCAL_DATASET_PATH)
        _write_jsonl(rows, cache)
        log.info("Cached %d rows to %s", len(rows), cache)

    instances = [Instance.model_validate(r) for r in rows]
    if instance_ids:
        wanted = set(instance_ids)
        instances = [i for i in instances if i.instance_id in wanted]
    if limit is not None:
        instances = instances[:limit]
    return instances


def summarize(instances: list[Instance]) -> dict:
    """Small summary used by the CLI and later by P6 stats."""
    per_repo = Counter(i.repo for i in instances)
    unique_snapshots = {(i.repo, i.base_commit) for i in instances}
    return {
        "n_instances": len(instances),
        "n_repos": len(per_repo),
        "n_unique_snapshots": len(unique_snapshots),
        "per_repo": dict(per_repo.most_common()),
    }
