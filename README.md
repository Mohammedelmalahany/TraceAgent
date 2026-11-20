# TraceAgent: Repository-Level Issue Localization Using Semantic Navigation

Graduation project in Computer Science.

## What TraceAgent does

When a bug is reported on GitHub, a developer first has to find **where** in the code the problem is. In a large
repository (thousands of files) this is the hardest and slowest part of fixing a bug.

**TraceAgent takes a GitHub issue and a code repository, and returns a ranked list of the files and functions that most
likely need to change.**

It works in two stages:

1. **Offline (preprocessing — this milestone).** Turn each repository into data that can be searched and navigated:
   - a **search index** over every file, class and function (to *find* a starting point from the issue's words);
   - a **code graph** of how the code is connected — who contains, calls, imports, inherits from or references whom
     (to *move* from a starting point to related code).
2. **Online (next milestone).** An agent reads the issue, searches the index, walks the graph, collects evidence
   for each candidate location, and submits a ranked list.

**Current milestone (Seminar 1):** data collection and preprocessing on the SWE-bench Lite benchmark
(300 real GitHub issues from 12 popular Python projects).

## Pipeline

| Step | What it does | Module |
|---|---|---|
| collect | download the 300 issues and clone the 12 repositories | `collection/` |
| P1 gold labels | from each issue's real fix, extract the files/functions that were changed (the "answer key") | `preprocessing/gold_labels.py` |
| P2 AST parsing | parse every Python file into files, classes, functions and the relations between them | `preprocessing/ast_parser.py` |
| P3 code graph | connect entities with 5 edge types: Contains, Calls, Imports, Inherits, References | `preprocessing/graph_builder.py` |
| P4 search index | build a text for every entity and a BM25 search index over them | `preprocessing/entity_index.py` |
| P5 issue cues | extract evidence (file paths, function names, errors, tracebacks) from the issue text | *next* |
| P6 statistics | tables and figures | *next* |

**Key idea in the graph:** a call like `helper()` whose target is certain is stored as an edge. A call like `obj.run()`,
where the target depends on the runtime type of `obj`, is **not guessed** — it is stored as an *unresolved site* with its
exact position, to be resolved precisely later with a language server.

## Results so far

| | |
|---|---|
| Issues / repositories / code snapshots | 300 / 12 / 297 |
| Gold labels | 100% file-level agreement with an independent label set |
| Code graphs | 297 built; every gold file and function is a node of its graph |
| Calls whose target is not syntactically certain | 55% (handled by the language server later) |
| Plain BM25 search, issue text as query | gold file in top 10 for 82% of issues; gold function in top 10 for 60% |

Details, tables and findings: [docs/seminar1.md](docs/seminar1.md) · overview: [docs/progress_summary.md](docs/progress_summary.md).

## Setup (Windows, Python 3.12)

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .
copy .env.example .env
```

Edit `.env` → set `DATA_DIR` to a folder **outside OneDrive / any synced folder** (default `D:/traceagent-data`).
All data (cloned repositories, graphs, indexes) lives there and is never committed; rebuild it with the commands below.

## Run

```bash
python scripts/run_pipeline.py --step info
python scripts/run_pipeline.py --step collect --limit 10   # quick try: 10 issues, 2 repos
python scripts/run_pipeline.py --step collect              # all 300 issues, 12 repos (~2 GB)
python scripts/run_pipeline.py --step gold                 # P1 gold labels
python scripts/run_pipeline.py --step graph --workers 6    # P2+P3 code graphs for all 297 snapshots
python scripts/run_pipeline.py --step index --workers 6    # P4 search indexes + sanity check
pytest
```

Every step is resumable (finished outputs are skipped); add `--overwrite` to recompute.

| Output (under `DATA_DIR`) | Content |
|---|---|
| `raw/swe_bench_lite.jsonl`, `raw/repos/` | the issues and the cloned repositories |
| `processed/gold/<instance_id>.json` | gold files / functions per issue |
| `processed/graphs/<repo>__<commit>/` | `entities`, `edges`, `sites` (`.jsonl.gz`), `stats.json`, `skipped.csv` |
| `processed/index/<repo>__<commit>/` | BM25 index |
| `processed/stats/` | evaluation reports |

## Project layout

```
src/traceagent/
  helpers/        config (.env) + logging
  models/         data schemas
  collection/     dataset loading, repository cloning
  preprocessing/  P1–P5
  analysis/       P6 statistics
  resolution/     language-server resolution (next milestone)
scripts/          CLI entry point
tests/            unit tests
docs/             seminar write-ups
```
