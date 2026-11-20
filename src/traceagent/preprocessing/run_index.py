"""Run P4 for every snapshot, and a BM25 sanity check against the gold labels.

Index output per snapshot: DATA_DIR/processed/index/<key>/ {bm25_weights.npz, bm25_meta.json, meta.json}
The entity ids are exactly the graph's entity ids (same key, same order as entities.jsonl.gz).
"""

import gzip
import json
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from tqdm import tqdm

from traceagent.collection import repo_manager as rm
from traceagent.collection.dataset_loader import load_instances
from traceagent.helpers.config import Settings, get_settings
from traceagent.helpers.logging import get_logger
from traceagent.models.graph import Entity
from traceagent.preprocessing.ast_parser import decode_source
from traceagent.preprocessing.entity_index import BM25Index, build_index, tokenize
from traceagent.preprocessing.run_graph import graph_dir, snapshot_key

log = get_logger(__name__)


def index_dir(settings: Settings, repo: str, commit: str) -> Path:
    return settings.processed_dir / "index" / snapshot_key(repo, commit)


def load_entities(gdir: Path) -> list[Entity]:
    with gzip.open(gdir / "entities.jsonl.gz", "rt", encoding="utf-8") as f:
        return [Entity(**json.loads(line)) for line in f]


def process_snapshot(settings: Settings, repo: str, commit: str) -> dict:
    t0 = time.time()
    entities = load_entities(graph_dir(settings, repo, commit))
    repo_dir = rm.repo_path(settings.repos_dir, repo)
    rm.checkout(repo_dir, commit)
    file_text = {}
    for path in {e.file_path for e in entities if e.type == "file"}:
        file_text[path] = decode_source((repo_dir / path).read_bytes())  # all of them parsed fine in P2
    idx = build_index(entities, file_text)
    out = index_dir(settings, repo, commit)
    idx.save(out)
    meta = {"repo": repo, "base_commit": commit, "n_docs": len(idx.ids), "n_terms": len(idx.vocab),
            "nnz": int(idx.weights.nnz), "seconds": round(time.time() - t0, 1)}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")  # last: marks done
    return meta


def _process_repo(data_dir: str, repo: str, commits: list[str]) -> list[dict]:
    settings = get_settings().model_copy(update={"DATA_DIR": Path(data_dir)})
    return [process_snapshot(settings, repo, c) for c in commits]


def run_index(settings: Settings, limit: int | None = None, instance_ids: list[str] | None = None,
              overwrite: bool = False, workers: int = 1) -> None:
    instances = load_instances(settings, limit=limit, instance_ids=instance_ids)
    todo: dict[str, list[str]] = defaultdict(list)
    for repo, commit in sorted({(i.repo, i.base_commit) for i in instances}):
        if not (graph_dir(settings, repo, commit) / "stats.json").exists():
            log.warning("No graph for %s@%s — run --step graph first", repo, commit[:12])
            continue
        if overwrite or not (index_dir(settings, repo, commit) / "meta.json").exists():
            todo[repo].append(commit)
    n = sum(len(v) for v in todo.values())
    log.info("P4: %d snapshot indexes to build, workers=%d", n, workers)
    if n:
        bar = tqdm(total=n, desc="P4 BM25 index")
        if workers <= 1:
            for repo, commits in todo.items():
                for c in commits:
                    process_snapshot(settings, repo, c)
                    bar.update(1)
        else:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_process_repo, str(settings.DATA_DIR), r, cs): r
                        for r, cs in sorted(todo.items(), key=lambda kv: -len(kv[1]))}
                for fut in as_completed(futs):
                    bar.update(len(fut.result()))
        bar.close()
    bm25_sanity_check(settings, [i.instance_id for i in instances])


# ----------------------------------------------------------------------------- sanity check

KS = (1, 5, 10)


def _strip(eid: str) -> str:
    return eid.split("@")[0]


def bm25_sanity_check(settings: Settings, instance_ids: list[str] | None = None) -> dict:
    """Query = the issue text (problem_statement only). Are gold functions / files in BM25's top-k?
    This is a plain BM25 baseline (no cues, no graph bonus, no agent)."""
    instances = {i.instance_id: i for i in load_instances(settings, instance_ids=instance_ids)}
    rows = []
    cache: tuple[Path, BM25Index] | None = None
    for iid, inst in sorted(instances.items(), key=lambda kv: (kv[1].repo, kv[1].base_commit)):
        idir = index_dir(settings, inst.repo, inst.base_commit)
        gpath = settings.processed_dir / "gold" / f"{iid}.json"
        if not (idir / "meta.json").exists() or not gpath.exists():
            continue
        if cache is None or cache[0] != idir:
            cache = (idir, BM25Index.load(idir))
        idx = cache[1]
        gold = json.loads(gpath.read_text(encoding="utf-8"))
        q = tokenize(inst.problem_statement)
        row = {"instance_id": iid, "repo": inst.repo}

        # function ranking (non-test functions)
        gold_fn = set(gold["functions"])
        if gold_fn:
            ranked = [_strip(e) for e, _ in idx.search(q, top_k=max(KS), types={"function"}, exclude_tests=True)]
            for k in KS:
                hit = gold_fn & set(ranked[:k])
                row[f"fn_hit@{k}"] = int(bool(hit))
                row[f"fn_recall@{k}"] = len(hit) / len(gold_fn)
        # file ranking: a file's score = best score of any entity in it (non-test)
        s = idx.scores(q)
        s = np.where(idx.is_test, -np.inf, s)
        best: dict[str, float] = {}
        for eid, sc in zip(idx.ids, s):
            f = eid.split("::")[0]
            if sc > best.get(f, -np.inf):
                best[f] = sc
        files_ranked = sorted((f for f in best if best[f] > 0), key=lambda f: -best[f])[:max(KS)]
        for k in KS:
            row[f"file_hit@{k}"] = int(bool(set(gold["files"]) & set(files_ranked[:k])))
        rows.append(row)

    def mean(key: str, rs: list[dict]) -> float | None:
        vals = [r[key] for r in rs if key in r]
        return round(100 * sum(vals) / len(vals), 1) if vals else None

    keys = [f"file_hit@{k}" for k in KS] + [f"fn_hit@{k}" for k in KS] + [f"fn_recall@{k}" for k in KS]
    by_repo = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    report = {
        "n_instances": len(rows),
        "overall": {k: mean(k, rows) for k in keys},
        "per_repo": {repo: {"n": len(rs), **{k: mean(k, rs) for k in keys}} for repo, rs in sorted(by_repo.items())},
    }
    out = settings.processed_dir / "stats" / "bm25_sanity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out.parent / "bm25_sanity_per_instance.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    o = report["overall"]
    log.info("BM25 sanity (%d issues): file Hit@1/5/10 = %s/%s/%s | function Hit@1/5/10 = %s/%s/%s -> %s",
             len(rows), o["file_hit@1"], o["file_hit@5"], o["file_hit@10"],
             o["fn_hit@1"], o["fn_hit@5"], o["fn_hit@10"], out)
    return report
