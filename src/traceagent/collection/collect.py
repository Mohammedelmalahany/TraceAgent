"""Collection step: load the benchmark, clone the needed repos, verify every base commit exists."""

import json

from tqdm import tqdm

from traceagent.collection import repo_manager as rm
from traceagent.collection.dataset_loader import load_instances, summarize
from traceagent.helpers.config import Settings
from traceagent.helpers.logging import get_logger

log = get_logger(__name__)


def run_collection(settings: Settings, limit: int | None = None, instance_ids: list[str] | None = None) -> dict:
    settings.ensure_dirs()
    instances = load_instances(settings, limit=limit, instance_ids=instance_ids)
    summary = summarize(instances)
    log.info(
        "Instances: %d | repos: %d | unique (repo, commit) snapshots: %d",
        summary["n_instances"], summary["n_repos"], summary["n_unique_snapshots"],
    )

    # 1) Clone each needed repo once.
    repos = sorted({i.repo for i in instances})
    for repo in repos:
        rm.clone_repo(repo, settings.repos_dir)

    # 2) Verify every base_commit exists in its clone (deduplicated).
    snapshots = sorted({(i.repo, i.base_commit) for i in instances})
    missing = []
    for repo, commit in tqdm(snapshots, desc="Verifying base commits"):
        if not rm.has_commit(rm.repo_path(settings.repos_dir, repo), commit):
            missing.append({"repo": repo, "base_commit": commit})

    repo_sizes = {r: round(rm.folder_size_mb(rm.repo_path(settings.repos_dir, r)), 1) for r in repos}
    report = {
        **summary,
        "repo_size_mb": repo_sizes,
        "total_size_mb": round(sum(repo_sizes.values()), 1),
        "missing_commits": missing,
    }
    out = settings.processed_dir / "collection_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if missing:
        log.warning("%d base commits NOT found: %s", len(missing), missing)
    else:
        log.info("All %d base commits found.", len(snapshots))
    log.info("Total size of clones: %.1f MB | report: %s", report["total_size_mb"], out)
    return report
