"""Run P2 + P3 for every unique (repo, base_commit) snapshot.

Output per snapshot in DATA_DIR/processed/graphs/<owner>__<name>__<commit12>/:
    entities.jsonl.gz, edges.jsonl.gz, sites.jsonl.gz, stats.json, skipped.csv

Resumable (a snapshot with stats.json is skipped). Snapshots of the same repo run sequentially (they share one
working copy); different repos can run in parallel with --workers.
"""

import csv
import gzip
import json
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from semnav_gp.collection import repo_manager as rm
from semnav_gp.collection.dataset_loader import load_instances
from semnav_gp.helpers.config import Settings, get_settings
from semnav_gp.helpers.logging import get_logger
from semnav_gp.preprocessing.graph_builder import SNG, build_from_sources

log = get_logger(__name__)


def snapshot_key(repo: str, commit: str) -> str:
    return f"{repo.replace('/', '__')}__{commit[:12]}"


def graph_dir(settings: Settings, repo: str, commit: str) -> Path:
    return settings.processed_dir / "graphs" / snapshot_key(repo, commit)


def read_python_sources(repo_dir: Path) -> tuple[dict[str, bytes], list[dict]]:
    """Tracked .py files of the current checkout (symlinks skipped and logged)."""
    out = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=repo_dir, capture_output=True, check=True).stdout
    sources, skipped = {}, []
    for rec in out.decode("utf-8", errors="replace").split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        if not path.endswith(".py"):
            continue
        if meta.startswith("120000"):  # symlink
            skipped.append({"file": path, "reason": "symlink", "detail": ""})
            continue
        try:
            sources[path] = (repo_dir / path).read_bytes()
        except OSError as exc:
            skipped.append({"file": path, "reason": "read_error", "detail": str(exc)[:120]})
    return sources, skipped


def _write_jsonl_gz(path: Path, records) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def save_graph(g: SNG, out_dir: Path, meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl_gz(out_dir / "entities.jsonl.gz", g.entities)
    _write_jsonl_gz(out_dir / "edges.jsonl.gz", g.edges)
    _write_jsonl_gz(out_dir / "sites.jsonl.gz", g.sites)
    with (out_dir / "skipped.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "reason", "detail"])
        w.writeheader()
        w.writerows(g.skipped)
    # stats.json last: its presence marks the snapshot as done (resumability)
    (out_dir / "stats.json").write_text(json.dumps({**meta, **g.stats.to_dict()}, indent=2), encoding="utf-8")


def process_snapshot(settings: Settings, repo: str, commit: str) -> dict:
    repo_dir = rm.repo_path(settings.repos_dir, repo)
    t0 = time.time()
    rm.checkout(repo_dir, commit)
    sources, pre_skipped = read_python_sources(repo_dir)
    g = build_from_sources(sources, max_kb=settings.MAX_FILE_SIZE_KB)
    g.skipped = pre_skipped + g.skipped
    g.stats.files_total += len(pre_skipped)
    for s in pre_skipped:
        g.stats.skipped[s["reason"]] = g.stats.skipped.get(s["reason"], 0) + 1
    meta = {"repo": repo, "base_commit": commit, "seconds": round(time.time() - t0, 1)}
    save_graph(g, graph_dir(settings, repo, commit), meta)
    return meta


def _process_repo(data_dir: str, repo: str, commits: list[str]) -> list[dict]:
    """Worker: all snapshots of one repo, sequentially (they share one working copy)."""
    settings = get_settings().model_copy(update={"DATA_DIR": Path(data_dir)})
    return [process_snapshot(settings, repo, c) for c in commits]


def run_graph(settings: Settings, limit: int | None = None, instance_ids: list[str] | None = None,
              overwrite: bool = False, workers: int = 1) -> None:
    instances = load_instances(settings, limit=limit, instance_ids=instance_ids)
    todo: dict[str, list[str]] = defaultdict(list)
    for repo, commit in sorted({(i.repo, i.base_commit) for i in instances}):
        if overwrite or not (graph_dir(settings, repo, commit) / "stats.json").exists():
            todo[repo].append(commit)
    n = sum(len(v) for v in todo.values())
    log.info("P2+P3: %d snapshots to build (%d repos), workers=%d", n, len(todo), workers)
    if n == 0:
        return
    bar = tqdm(total=n, desc="P2+P3 graphs")
    if workers <= 1:
        for repo, commits in todo.items():
            for c in commits:
                meta = process_snapshot(settings, repo, c)
                bar.update(1)
                bar.set_postfix_str(f"{repo} {meta['seconds']}s")
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            # biggest repos first so they do not finish last
            futs = {ex.submit(_process_repo, str(settings.DATA_DIR), repo, commits): repo
                    for repo, commits in sorted(todo.items(), key=lambda kv: -len(kv[1]))}
            for fut in as_completed(futs):
                bar.update(len(fut.result()))
                bar.set_postfix_str(f"done {futs[fut]}")
    bar.close()
    log.info("P2+P3: graphs written to %s", settings.processed_dir / "graphs")
