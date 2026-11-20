"""Run P1 over instances and (optionally) compare with CoSIL's gt.json."""

import json
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from semnav_gp.collection import repo_manager as rm
from semnav_gp.collection.dataset_loader import load_instances
from semnav_gp.helpers.config import Settings
from semnav_gp.helpers.logging import get_logger
from semnav_gp.preprocessing.gold_labels import extract_gold

log = get_logger(__name__)


def run_gold(settings: Settings, limit: int | None = None, instance_ids: list[str] | None = None,
             overwrite: bool = False) -> Path:
    out_dir = settings.processed_dir / "gold"
    out_dir.mkdir(parents=True, exist_ok=True)
    instances = load_instances(settings, limit=limit, instance_ids=instance_ids)
    n_done = 0
    for inst in tqdm(instances, desc="P1 gold labels"):
        out = out_dir / f"{inst.instance_id}.json"
        if out.exists() and not overwrite:
            continue  # resumable
        repo = rm.repo_path(settings.repos_dir, inst.repo)
        gold = extract_gold(inst.patch, lambda p: rm.read_file_at(repo, inst.base_commit, p))
        record = {"instance_id": inst.instance_id, "repo": inst.repo, "base_commit": inst.base_commit, **gold}
        out.write_text(json.dumps(record, indent=2), encoding="utf-8")
        n_done += 1
    log.info("P1: wrote %d new gold files to %s", n_done, out_dir)
    return out_dir


# ---------------------------------------------------------------- validation vs CoSIL

def _ours_comparable(g: dict) -> set[str]:
    """Our gold in CoSIL's style: modified + added functions, edited classes, and the file itself
    when a file has only module-level edits (no function/class entry)."""
    locs = set(g["functions"]) | set(g["added_functions"]) | set(g["edited_classes"])
    for f in g["files"]:
        if f.endswith(".py") and not any(x.startswith(f + "::") for x in locs):
            locs.add(f)
    return locs


def _last(name: str) -> str:
    return name.split("::")[-1].split(".")[-1]


def _classify(ours: set[str], theirs: set[str], g: dict) -> str:
    if ours == theirs:
        return "exact"
    only_o, only_t = ours - theirs, theirs - ours
    if {_last(x) for x in only_o} == {_last(x) for x in only_t}:
        return "naming (same names, different qualification)"
    if only_t and only_t <= {x for x in theirs if "::" not in x} | set():
        return "they list file only"
    if only_o and not only_t:
        if only_o & set(g["edited_classes"]) or only_o <= set(g["files"]):
            return "we add class/module-level entry"
        if only_o & set(g["added_functions"]):
            return "we add added_functions"
        return "we list extra functions"
    if only_t and not only_o:
        return "they list extra entries"
    return "different entries"


def compare_with_cosil(settings: Settings, cosil_path: Path) -> dict:
    theirs_all = json.loads(cosil_path.read_text(encoding="utf-8"))
    gold_dir = settings.processed_dir / "gold"
    cats: Counter = Counter()
    examples: dict[str, list] = {}
    tp = n_ours = n_theirs = 0
    for iid, theirs_list in theirs_all.items():
        p = gold_dir / f"{iid}.json"
        if not p.exists():
            continue
        g = json.loads(p.read_text(encoding="utf-8"))
        ours, theirs = _ours_comparable(g), {t.strip() for t in theirs_list}
        tp += len(ours & theirs)
        n_ours += len(ours)
        n_theirs += len(theirs)
        c = _classify(ours, theirs, g)
        cats[c] += 1
        if c != "exact" and len(examples.setdefault(c, [])) < 5:
            examples[c].append({"id": iid, "only_ours": sorted(ours - theirs), "only_theirs": sorted(theirs - ours)})

    n = sum(cats.values())
    file_agree = 0
    for iid, theirs_list in theirs_all.items():
        p = gold_dir / f"{iid}.json"
        if p.exists():
            g = json.loads(p.read_text(encoding="utf-8"))
            ours_files = {f for f in g["files"] if f.endswith(".py")} | set(g["added_files"])
            file_agree += ours_files >= {t.split("::")[0].strip() for t in theirs_list}
    report = {
        "n_compared": n,
        "exact_match_pct": round(100 * cats["exact"] / n, 1) if n else 0,
        "file_level_agreement_pct": round(100 * file_agree / n, 1) if n else 0,
        "entry_precision_pct": round(100 * tp / n_ours, 1) if n_ours else 0,
        "entry_recall_pct": round(100 * tp / n_theirs, 1) if n_theirs else 0,
        "categories": dict(cats.most_common()),
        "examples": examples,
    }
    out = settings.processed_dir / "stats" / "gold_vs_cosil.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("CoSIL comparison: exact %.1f%% | files %.1f%% | precision %.1f%% | recall %.1f%% -> %s",
             report["exact_match_pct"], report["file_level_agreement_pct"],
             report["entry_precision_pct"], report["entry_recall_pct"], out)
    return report
