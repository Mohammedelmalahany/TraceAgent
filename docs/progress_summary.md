# Progress Summary — SemNav-GP (Seminar 1: Data Collection + Preprocessing)

*Last updated: 2026-11-20*

This document summarizes everything done so far: the review of the plan against the paper, the decisions we made,
the code we wrote, the results, and what comes next. For the detailed numbers, see [seminar1.md](seminar1.md).

---

## 1. Review of the plan against the SemNav paper

We checked every claim in `CLAUDE.md` against the paper itself (arXiv 2609.31176, HTML v1).

**Confirmed (matches the paper):**
- The 3 problems: ambiguous relation targets, implicit entity semantics, underspecified candidate state.
- Graph nodes are file / class / function only (no directory nodes).
- The 5 edge types: Contains, Calls, Imports, Inherits, References.
- Resolved edges `(u, r, v, ℓ)` vs unresolved edges `(u, r, ℓ)`; unresolved ones are resolved later with Pyright
  (go-to-definition forward, find-references backward).
- The entity text = qualified name + declaration + documentation + implementation.
- Semantic Cards, the Candidate Workspace (unverified / plausible / discarded), the agents and their tools.
- The benchmarks, metrics, models and baselines.

**Corrected:**
- Affiliations are "Independent Researcher" and "University of Virginia" (not all UVA).
- The title differs between the arXiv abstract page and the HTML version; both are recorded.
- Metrics are specifically Acc@3 / Acc@5 (PLocBench) and Hit@1/5/10 (SWE-bench Lite).
- **The paper releases no code** → we re-implement it.

**Key clarifications for the committee:**
- **Offline vs online boundary.** Offline = anything that does not depend on the agent or an LLM. In the paper, issue
  cue extraction is the *first online step*; we precompute it because it is rule-based and deterministic.
- **The paper says *what* to do, not *how*.** Example: it says "syntactically determined targets are resolved" but never
  defines "syntactically determined". Every such decision is ours and is marked `[ours]` in `CLAUDE.md`.
- **Search weights α, β, γ** balance three signals (text similarity, exact cue match, graph neighbours). They are used
  only at search time by the agent → **not needed for Seminar 1**.
- **Data-leakage rule:** retrieval and cues may only use `problem_statement`; `patch` is used only for gold labels;
  `hints_text` and `test_patch` are never used.

## 2. Environment decisions

| Item | Decision |
|---|---|
| OS / Python | Windows 11, venv with **Python 3.12.6** (system Python 3.14 avoided for library compatibility) |
| Data location | **`D:\semnav-data`** (outside OneDrive, set in `.env`) |
| Repo strategy | one clone per repo; `git checkout <base_commit>` per snapshot (12 folders, not ~300 copies) |
| Version control | git, small commits on `main` (local only, not pushed) |

## 3. What was built

| Step | What it does | Main files | Status |
|---|---|---|---|
| Scaffold | package layout, `.env` config, logging, CLI, README | `helpers/config.py`, `helpers/logging.py`, `scripts/run_pipeline.py` | ✅ |
| Collect | download SWE-bench Lite, clone 12 repos, verify commits | `collection/dataset_loader.py`, `repo_manager.py`, `collect.py` | ✅ |
| P1 Gold labels | which files/functions the real fix changed | `preprocessing/patch_parser.py`, `gold_labels.py`, `run_gold.py` | ✅ |
| P2 AST parsing | entities + raw relation sites per file | `preprocessing/ast_parser.py` | ✅ |
| P3 Graph | resolve relations → edges / unresolved sites | `preprocessing/graph_builder.py`, `run_graph.py` | ✅ (all 297 snapshots) |
| P4 BM25 index | search engine over entities | — | ⏭ next |
| P5 Issue cues | rule-based evidence from the issue text | — | ⏭ |
| P6 Stats / figures | tables + plots for the seminar | — | ⏭ |

**Tests:** 26 unit tests (config, collection, gold labels, graph), all passing.

**How to run:**
```bash
.venv\Scripts\activate
python scripts/run_pipeline.py --step collect
python scripts/run_pipeline.py --step gold
python scripts/run_pipeline.py --step graph --workers 6
pytest
```

## 4. Results

### Data collection
- **300 issues, 12 repos, 297 unique (repo, commit) snapshots, 0 missing commits.**
- Clones: ~2 GB on `D:`.

### P1 — Gold labels
- Method: `-` lines are mapped with the **old** file's AST, `+` lines with the **new** file's AST (rebuilt in memory).
  A `+` line in an existing function → modified; in a new function → added. No guessing about insertions.
- Every issue in SWE-bench Lite edits **exactly 1 file**; on average 1.06 modified functions per issue; 32 issues add
  new functions; 0 parse errors.
- **Validation vs CoSIL's `gt.json`:** files agree **100%**; exact function-level match 79.3%. Every remaining difference
  was inspected: they are convention differences (added methods, nested functions) or CoSIL labelling errors
  (e.g. names taken from the `@@` hunk header).

### P2 + P3 — Semantic Navigation Graph (all 297 snapshots)
- **297 graphs built**, ~85 min with 6 workers, 588 MB compressed, stored in `D:\semnav-data\processed\graphs\`.
- A typical Django snapshot: 2,666 files, ~34k entities, ~87k resolved edges, ~71k unresolved sites (~19 s to build).
- **55% of calls are unresolved** over all snapshots (from 33% in sympy to 83% in pytest). They depend on runtime
  types, e.g. `obj.run()`. Imports and inheritance are >99.7% resolved. This is the paper's first problem measured on
  real data, and why Pyright is needed later.
- **Coverage over all 300 issues: gold files 300/300, gold functions 317/317, edited classes 17/17** are nodes of the
  graph, so the correct answer is always reachable.
- Skipped files (generated parsers, Python 2 scripts, broken linter fixtures, >1 MB files, symlinks) were all
  inspected; no hand-written source is lost.

## 5. Problems found and fixed (good material for the seminar)

| # | Problem | Effect if ignored | Fix |
|---|---|---|---|
| 1 | **8 SWE-bench patches have wrong line numbers** (e.g. `sympy__sympy-14317` is off by 41 lines) | wrong gold function (`_print_FourierSeries` instead of `_print_Poly`) | relocate each hunk by matching its context text, like `git apply` |
| 2 | Python's `str.splitlines()` also splits on `\x0c`, `\u2028`, … | line numbers drift from what `ast` reports | split on real line breaks only |
| 3 | A removed line like `-- comment` looks like a file header `---` | the diff parser splits a file in two | count the remaining lines of each hunk |
| 4 | Re-exports via `from .fields import *` in `__init__.py` | 495 imports stayed unresolved in Django | follow star re-exports → 20 left |
| 5 | Loose "generated file" rule | skipped the real `matplotlib/pyplot.py`, missed real generated PLY tables | only skip files whose header comment says the *whole* file is generated |
| 6 | Classes *added* by a patch were labelled "edited classes" (2 issues) | gold pointed at classes that do not exist pre-patch | new `added_classes` field (found by the full coverage check) |

## 6. Design decisions we made (where the paper is silent)

- Nested functions are folded into their parent function; duplicate names (e.g. property setter) get `@<line>`.
- Directory nodes are dropped (LocAgent has them; SemNav does not).
- Resolved only when a static lookup reaches exactly one repo entity: same-file definition, explicit import
  (following re-exports), module attribute (`models.Field`), or a member defined directly in a known class.
- `self.x()`, `obj.run()`, `super().f()` and inherited members → **unresolved site** (never guessed — the key difference
  from LocAgent, which links `obj.run()` to every function named `run`).
- stdlib / builtins / third-party targets are only counted (`external`), never stored.
- Relation-site positions point at the target-name token in UTF-16 columns, ready for Pyright.
- Test files are parsed and flagged `is_test`.

## 7. Git history

| Commit | Content |
|---|---|
| `7c1c0df` | Scaffold project structure, config and CLI skeleton |
| `43d1ecd` | Data collection step (dataset loader + repo manager) |
| `5277574` | P1 gold label extraction with CoSIL validation |
| `901bc24` | P2+P3 AST parser and Semantic Navigation Graph builder |
| `8053523` | Switch explanation language to English in CLAUDE.md |
| `d1de727` | Progress summary document |
| (next) | Full graph run results + `added_classes` fix in P1 |

## 8. Next steps

1. ~~Finish the full graph build and check gold coverage~~ ✅ done.
2. **P4** — entity text + BM25 index; sanity check: are gold functions in the top-k for each issue?
3. **P5** — rule-based issue cues for all 300 issues; how often does a cue directly name a gold file/function?
4. **P6** — statistics and figures (notebook) + finish `docs/seminar1.md`.
5. (Optional) Pyright smoke test on a few unresolved sites.
