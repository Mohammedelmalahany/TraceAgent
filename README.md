# SemNav-GP — Repository-Level Issue Localization

Graduation project built on **SemNav: Semantic Navigation for Repository-Level Issue Localization**
([arXiv:2609.31176](https://arxiv.org/abs/2609.31176)).

**Issue localization:** given a GitHub issue and a code repository, return a ranked list of the files and functions
that need to change to fix the issue.

**Current milestone (Seminar 1):** data collection and offline preprocessing on SWE-bench Lite. No agent and no LLM yet.

## Pipeline (offline)

| Step | Module | Output |
|---|---|---|
| collect | `collection/` | SWE-bench Lite rows + 12 cloned repositories |
| P1 gold | `preprocessing/gold_labels.py` | gold files/functions per issue |
| P2+P3 graph | `preprocessing/ast_parser.py`, `graph_builder.py` | Semantic Navigation Graph (resolved edges + unresolved relation sites) |
| P4 index | `preprocessing/entity_index.py` | BM25 index over entities |
| P5 cues | `preprocessing/issue_cues.py` | rule-based issue cues |
| P6 stats | `analysis/stats.py` | tables + figures |

## Setup (Windows, Python 3.12)

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .
copy .env.example .env
```

Edit `.env` → set `DATA_DIR` to a folder **outside OneDrive** (default `D:/semnav-data`).

## Run

```bash
python scripts/run_pipeline.py --step info
python scripts/run_pipeline.py --step collect --limit 10   # quick try: 10 issues, 2 repos
python scripts/run_pipeline.py --step collect              # all 300 issues, 12 repos (~several GB)
pytest
```

`collect` downloads SWE-bench Lite (cached to `DATA_DIR/raw/swe_bench_lite.jsonl`), clones each needed repo once
into `DATA_DIR/raw/repos/<owner>__<name>`, verifies every `base_commit` exists, and writes
`DATA_DIR/processed/collection_report.json`. Re-running is safe: cached data and existing clones are reused.

## Project layout

```
src/semnav_gp/
  helpers/        config (.env) + logging
  models/         data schemas
  collection/     dataset loading, repo cloning
  preprocessing/  P1–P5
  analysis/       P6 statistics
  resolution/     Pyright resolution (later phase)
scripts/          CLI entry points
tests/            unit tests
docs/             seminar write-ups
```

## Acknowledgements
Parts of the preprocessing are adapted from [LocAgent](https://github.com/gersteinlab/LocAgent) (Apache-2.0).
