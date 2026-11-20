# CLAUDE.md — Graduation Project Context (SemNav-based Issue Localization)

> This file is the full hand-off context for Claude Code. Read it completely before doing anything.
> It summarizes a prior planning conversation: what the project is, what we decided, what code already
> exists in the ecosystem that we can reuse, and exactly what to build next.

---

## 0. How to work with me (the student)

- I am a graduation-project student. I am **new to AI agents** and **new to working with code repositories as data**
  (ASTs, code graphs, etc. are new to me). Explain every step simply, **in Egyptian Arabic**, with small concrete examples.
  Keep code, identifiers, comments and docs in English.
- Work **one step at a time**. After each step: tell me what you did, what file(s) changed, how to run it, and what output to expect.
- The project must look **professional** (clean architecture, config via `.env`, proper `.gitignore`, README, reproducible commands),
  in the spirit of well-structured open-source teaching projects such as Eng. Abu Bakr Soliman's *mini-rag*
  (layered `src/` package, `helpers/config.py` reading settings from `.env`, `.env.example` committed, data/secrets ignored).
- Ask me before: large downloads (>1 GB), installing system-level tools, deleting anything, or pushing to a remote.
- Use git from the start; small, meaningful commits.

---

## 1. The project in one paragraph

We are building our graduation project on top of the paper
**"SemNav: Semantic Navigation for Repository-Level Issue Localization"** — arXiv: https://arxiv.org/abs/2609.31176 (v1, 25 Sep 2026)
(the arXiv abs page lists the title as "Semantic Navigation for Issue Localization in Code Repository"; HTML/v1 header uses the SemNav title).
Authors: Yunxiang Wei, Zhenyu Lei, Jundong Li — affiliations: Independent Researcher; University of Virginia.
**The paper releases no code or data** → we re-implement it. Where the paper is silent, we make (and document) our own decisions.

> Convention in this file: **[paper]** = stated in the paper; **[ours]** = our engineering decision (paper is silent).

**Issue localization** = given a natural-language GitHub issue and a code repository, return a **ranked list of files / functions**
that need to be changed to fix the issue. Repositories are far larger than an LLM's context window, so localization decides what
code an agent can even look at.

SemNav is our **base architecture and design**. Other papers are references only.

---

## 2. SemNav — what we need to understand

### 2.1 Three problems it addresses
1. **Ambiguous relation targets** — a syntax graph shows `obj.run()` is a call, but not *which* `run` is invoked.
2. **Implicit entity semantics** — what a function is *for* is spread across its code; agents waste context reconstructing it.
3. **Underspecified candidate state** — a plain list of candidate locations doesn't record *why* each is a candidate.

### 2.2 Components
- **Semantic Navigation Graph (SNG)** [paper]: nodes = entities (**file, class, function only — no directory nodes**;
  methods are function entities); directed typed edges.
  **5 edge types: `Contains`, `Calls`, `Imports`, `Inherits`, `References`** (References = remaining symbol uses that are
  not calls/imports/inheritance).
  Resolved edge = `(u, r, v, ℓ)`; unresolved edge = `(u, r, ℓ)` (no target, ℓ = source location) = a "relation site".
  Edges whose target is "syntactically determined" are stored **resolved**; others **unresolved**, resolved **on demand**
  via **Pyright**: go-to-definition for forward access, find-references for reverse access; resolved edges move into the
  graph, failures stay unresolved. The paper does **not** define "syntactically determined" → our rule is in §3.2 (P3).
- **Entity retrieval index** [paper]: text D(v) = qualified name + declaration + documentation + implementation.
  Score `b(v|x,q) = α·BM25(x, D(v)) + β·Σ_c μ(c,v)` (μ = exact keyword / source-location match of issue cue c),
  then top-L anchors, then rerank with `+ γ·#(resolved SNG edges to an anchor)`.
  The weights α (text similarity), β (exact cue match), γ (graph-neighbour bonus) balance the three signals.
  **They are used only at search time (online, agent phase) → NOT needed for Seminar 1.** Values are not given in the
  paper → decide/tune in the agent phase. Offline (now) we only build the plain BM25 index; tokenization is [ours] (§3.2 P4).
- **Semantic Cards** (online, LLM-built on demand at `Read(card)` time, issue-conditioned) — contents: definition &
  responsibility, operational behavior, role in the issue, compact source snippets; cached by (repo snapshot, entity, issue).
  `Read` has 3 modes: summary (deterministic), code (raw span), card.
- **Candidate Workspace**: ordered candidate records, each with status (`unverified` / `plausible` / `discarded`) + evidence rationale.
- **Agents**: Localization Agent (tools: Search, Expand, Read, Update, Compare, Submit), Builder Agent (builds cards),
  Comparison Agent (re-ranks plausible candidates).

### 2.3 Pipeline (two stages — this split is how we explain "preprocessing" to the committee)
1. **Offline graph initialization (= our data preprocessing)**
   AST analysis → entities + relation sites → resolved edges + unresolved edges → SNG; build entity-level retrieval index.
2. **Online semantic localization (= the agent, later phase)**
   - Seeding: a **rule-based** parser extracts **issue cues** ([paper]: file paths, identifiers, API calls; [ours] adds
     exception names, traceback frames, backticked code); deterministic
     retrieval with the issue as query fills the Workspace with `unverified` candidates.
   - Iterative investigation: agent alternates navigation tools and Workspace updates; navigation triggers Pyright queries,
     newly resolved edges get added to the graph.
   - Verification (Compare) → Submission (plausible first, then unverified; discarded excluded).

### 2.4 Mental model (how I understand it — keep explanations consistent with this)
- **Index = "find"**: how to get from the issue's words to a *starting point* (like the search box in Google Maps).
- **Graph = "move"**: from a starting point, what is connected to it (like the roads).
- **Issue cues = the strongest search keywords**, extracted from the issue text itself.
- All three are built in preprocessing; the agent *uses* them later.

### 2.4.1 Offline vs online boundary (how we defend "preprocessing" to the committee)
Rule: **Offline = anything that does not depend on the agent's decisions or an LLM** (computed once, stored).
**Online = anything that depends on what the agent does while running.**

| Step | In the paper | In our project |
|---|---|---|
| AST → entities + relation sites + SNG | offline [paper] | P2 + P3 |
| Entity-level BM25 index | offline [paper] | P4 |
| Issue cue extraction (rule-based) | **online, first step before seeding** [paper] | P5 — **precomputed** by us because it is deterministic and depends only on the issue text |
| Gold labels, skip rules, EDA | not described | P1, P2-skip, P6 — [ours], evaluation/analysis prep (LocAgent-style) |
| Graph bonus, Pyright resolution, Cards, Workspace, agents | online [paper] | later phases |

**Data-leakage rule [ours]:** cues / seeding / retrieval may only use `problem_statement`.
Never use `hints_text`, `patch`, or `test_patch` there. `patch` is used **only** to derive gold labels (P1).

### 2.5 Evaluation (from the paper)
| Benchmark | Size | Task |
|---|---|---|
| SWE-bench Lite | 300 issues (12 Python repos) | ranked file + function localization |
| PLocBench | 821 issues | ranked file localization |
| SWE-Explore | 368 instances | evidence-quality evaluation |

Metrics: File Hit@{1,5,10}, Function Hit@{1,5,10}, Function Recall@{1,5,10} (SWE-bench Lite); Acc@3, Acc@5, MRR@5, Macro/Micro Recall@5 (PLocBench);
line-level P/F1, Recall@500, nDCG@500, HitFile, FUH, CE (SWE-Explore). Downstream repair: Applied / Resolved.
Models in paper: gemma-4-e4b-it (4B) for main comparisons; Qwen3.5 9B and 35B-A3B on SWE-bench Lite.
Baselines: Agentless, CoSIL, LocAgent, mini-swe-agent, RepoSearcher.

---

## 3. Current milestone: Seminar 1 = Data Collection + Data Preprocessing

The supervisors asked for **data collection** and **data preprocessing** only. No agent, no LLM in this milestone.

### 3.1 Data collection — what it really means here
A benchmark row contains only the issue + metadata, **not the code**. The real data is the repositories at the exact snapshot.
1. Load SWE-bench Lite (300 instances). Fields: `repo, instance_id, base_commit, patch, test_patch, problem_statement,
   hints_text, created_at, version, FAIL_TO_PASS, PASS_TO_PASS, environment_setup_commit`.
2. For each instance: get the repo at `base_commit`.
   Clone each of the 12 repos **once** (full history needed for old commits; ~3–4 GB total), and **deduplicate by
   (repo, base_commit)** (expect few duplicates in Lite — almost every instance has its own commit).
   Strategy [ours]: **one working copy per repo** (12 folders, not ~300 snapshots). For each instance:
   `git checkout --force <base_commit>` in that repo's folder → parse → save outputs → next instance.
   Total disk ~5–6 GB. Files are real on disk, so Pyright can use them later with no extra work.
   Process instances grouped by repo so checkouts stay sequential (no parallel workers on the same repo folder).
3. Environment [ours]: Windows 11; venv with **Python 3.12** (`py -3.12`; system `python` is 3.14 — avoid for library
   compatibility); git 2.56; Node 24 (for Pyright later). `git config core.longpaths true`.
   Disk: C: ~64 GB free, D: ~29 GB free.
   **`DATA_DIR = D:\semnav-data`** (outside OneDrive), set via `.env` — the code folder is OneDrive-synced
   and must not receive cloned repos / thousands of output files.

Repo distribution in SWE-bench Lite: django 114, sympy 77, matplotlib 23, scikit-learn 23, pytest 17, sphinx 16,
astropy 6, requests 6, pylint 6, xarray 5, seaborn 4, flask 3.

### 3.2 Data preprocessing — steps
| # | Step | What it does | Plain-language meaning |
|---|---|---|---|
| P1 | **Gold label extraction** | Parse the gold `patch` (unified diff) → edited files; map edited line ranges to enclosing functions using the AST of the **pre-patch** file | "Extract the correct answer from the real fix" so we can evaluate later |
| P2 | **AST parsing + cleaning** | Walk repo `.py` files → entities (file/class/function, qualified names, line spans, code) + relation sites (calls, imports, references, inheritance). Skip non-.py, symlinks, `.git`, files with syntax/encoding errors (e.g., Python 2), generated or abnormally large files; **log every skip** | |
| P3 | **Graph construction** | Build directed multigraph with the 5 edge types. Syntactically certain → resolved edge. Uncertain target (e.g. `obj.run()`) → store **unresolved relation site** with (file, line, col, kind, raw text) for Pyright later. **Do NOT guess targets.** | |
| P4 | **Entity text + BM25 index** | Per entity: qualified name + signature + docstring + code → text; build BM25 index; same entity ID in graph and index | Mini search engine over the code |
| P5 | **Issue cue extraction (rule-based, no LLM)** | Regex/heuristics over `problem_statement`: file paths, dotted names, `identifier(` calls, backticked code, traceback frames (`File "...", line N, in func`), exception names | Pull the "evidence" out of the issue text |
| P6 | **Statistics / EDA** | Per repo & instance: #files parsed/skipped, #entities by type, #edges by type, % unresolved, issue length, #cues, #gold files/functions per issue, cue→gold hit rate | Tables + figures for the seminar |

#### What the paper specifies vs what we must decide
The paper gives the *what* (ASTInit extracts entities + relation sites; syntactically determined targets → resolved,
others → unresolved; build an entity-level index). It releases no code, so every *how* below is [ours]:

| Question the code forces us to answer | Example | Why it matters | Our answer |
|---|---|---|---|
| What exactly is "syntactically determined"? | `helper()` defined in same file → yes; `self.save()` → no (subclass may override) | Core of P3; can't write `graph_builder` without it | P2/P3 rules below |
| What about `print()`, `os.path.join()`? | not repo entities | Storing them as unresolved wastes Pyright calls | count as `external` only |
| Nested function = entity? | `def outer(): def inner(): ...` | Node count + matching gold labels | fold into parent |
| Include test files? | `tests/test_models.py` | Gold edits are rarely in tests; may add noise | parse, flag `is_test` |
| How to tokenize for BM25? | `parse_date` vs `parse` + `date` | Issue says "date parsing" → must match | split + keep full name |
| How to derive gold labels? | patch adds a brand-new function | Paper only uses metrics, not how gold is built | P1 details below |
| Search weights α, β, γ? | — | Online only | deferred to agent phase |

#### P1 details [ours]
- Use `patch` only (never `test_patch`). Map **pre-patch** line ranges (`-` lines) to the enclosing function in the pre-patch AST.
- Pure insertions (no `-` lines) → use the hunk's anchor line in the old file.
- Functions that exist only post-patch → store separately as `added_functions` (they cannot be localized pre-patch).
- Edits outside any function (module- or class-level) → record at file level (and class level when inside a class body).
- Output: `{files, functions, added_functions, module_level_edits}`.
- Validate vs CoSIL `gt.json`: don't chase 100%; report agreement % and categorize disagreements
  (method naming, added functions, module-level edits, nested functions).

#### P2/P3 rules [ours — the paper does not define "syntactically determined"]
- Entities: files, classes (incl. nested classes), functions/methods. **Nested functions inside functions are folded into
  their parent** (not separate entities). No directory nodes.
- Entity ID: `path.py::Qualified.Name`; on duplicates (e.g. property setter, redefinition) append `@<start_line>`.
- Test files are parsed but flagged `is_test`; stats reported with and without tests.
- Resolved vs unresolved:
  - `Contains`: always resolved.
  - `Imports`: resolved when the module maps to a file inside the repo (absolute or relative import); imported name
    resolved if defined at top level of that file.
  - `Calls` / `Inherits` / `References`: resolved only when the target is a **bare name** defined in the same module or
    explicitly imported by name from a repo module. `obj.run()`, `self.x()` (subclass may override), `mod.attr` chains →
    **unresolved site**.
  - Targets outside the repo (stdlib, builtins like `print`/`len`, third-party) → **not stored as edges or sites**; only
    counted in an `external` counter. No LocAgent-style hacks.
  - `References` filter: only record name uses whose identifier matches some repo entity name (filter, not a guess).
- Relation-site position for Pyright: store the position of the **target name token**, not the expression start —
  for `obj.run()` that is the `run` token (`end_col_offset - len(attr)`), since `col_offset` points at `obj`.
  Python AST columns are **UTF-8 byte offsets**; LSP uses **UTF-16 code units** → convert on non-ASCII lines.
- Parse with `ast.parse`; skip-and-log syntax errors (Python 2 code, old code using `async` as an identifier, etc.).
- Implemented refinements: re-exports are followed (`from .x import name` and `from .x import *` in `__init__.py`,
  depth ≤ 4); module-level variables (`CONST = 1`, `_ = gettext_lazy`) resolve to their **file** entity (so a Calls
  edge may point to a file, meaning "a module-level callable defined there"); identical sites in one entity are stored
  once with a `count`; "generated" = only an explicit header comment saying the whole file is generated.

#### P4 details [ours]
- BM25 tokenization: split snake_case and camelCase, lowercase, also keep full dotted names and identifiers as tokens.

**Not in this milestone:** Semantic Cards (LLM, issue-conditioned, online), Pyright resolution during navigation, the agents.
A small Pyright smoke test (resolve a handful of unresolved sites) is a nice-to-have to demonstrate the idea.

---

## 4. Existing code we inspected (reuse plan)

All repos below were cloned and their code read during planning.

### 4.1 LocAgent — https://github.com/gersteinlab/LocAgent (Apache-2.0 → we may reuse/modify with attribution)
74 .py files, ~14.3k lines. Contains almost every preprocessing step:
| File | Use |
|---|---|
| `util/benchmark/git_repo_manager.py` | clone / checkout helpers (`setup_github_repo(repo, base_commit, base_dir)`) |
| `util/benchmark/parse_patch.py` | diff parsing (`get_oracle_filenames`, `get_edited_lines`, `parse_patch`) |
| `util/benchmark/gen_oracle_locations.py` | gold function locations from patch (`extract_module_from_patch`) |
| `dependency_graph/build_graph.py` (775 lines) | AST → networkx `MultiDiGraph`. Node types: directory/file/class/function. Edge types: `contains, inherits, invokes, imports` |
| `dependency_graph/batch_build_graph.py` | batch graph building over a dataset |
| `build_bm25_index.py`, `plugins/location_tools/retriever/bm25_retriever.py` | BM25 indexing (uses `bm25s`, llama-index) |
| `util/extract_entity_from_issue.py` | issue entity extraction — **uses an LLM (litellm)**; SemNav needs rule-based → we write our own |
| `evaluation/eval_metric.py` | localization metrics (useful later) |

**Differences we must implement vs LocAgent:**
0. **Drop `directory` nodes** (SemNav nodes are file/class/function only).
1. Add **`References`** edge type (LocAgent has 4 types; SemNav has 5). Rename `invokes` → `Calls`.
2. LocAgent **guesses** callees (`find_all_possible_callee` links every possible match). SemNav stores **unresolved relation
   sites** instead and resolves them later with Pyright. This is the key design change.
3. Issue cues: rule-based, deterministic (no LLM).
4. Entity text representation per SemNav (qualified name + declaration + docs + implementation).
5. LocAgent has hard-coded hacks (`handle_edge_cases` rewrites `True/False/print`) — prefer clean skip-and-log instead;
   external/builtin targets are only counted (`external`), never stored (see §3.2 P2/P3 rules).
### 4.2 CoSIL — https://github.com/ZhonghaoJiang/CoSIL
- `evaluation/gt.json`: **gold labels for all 300 SWE-bench Lite instances**, format
  `{"astropy__astropy-12907": ["astropy/modeling/separable.py::_cstack"], ...}` → use to **validate** our P1 output.

### 4.3 XAgent — https://github.com/xagent-se/XAgent
- `src/swebench_lite_test.jsonl`: **full copy of SWE-bench Lite (300 rows, 12 fields)**. Useful fallback if HuggingFace is blocked.
- Paper (arXiv 2609.09769) is execution-based (runtime call trees + UniXcoder), no AST graph → reference only.

### 4.4 Others
- HuggingFace `czlll/SWE-bench_Lite` (LocAgent's adapted version): 274 rows, adds `edit_functions` (format `file:function`)
  and `added_functions`. Note: 274 ≠ 300. Official: `princeton-nlp/SWE-bench_Lite`.
- RepoGraph (https://github.com/ozyyshr/RepoGraph) `repograph/construct_graph.py` ~600 lines — alternative graph builder, reference only.
- Agentless, mini-swe-agent — baselines for later phases; nothing needed for preprocessing.
- CogniGent (arXiv 2601.12522) — multi-agent bug localization with call-graph root-cause analysis; reference only, no code link found.
- Label formats differ (`::` in CoSIL, `:` in czlll) → **normalize to one canonical ID format**.

### 4.5 Canonical entity ID (proposal)
`<relative/file/path.py>::<Qualified.Name>` e.g. `django/utils/dateparse.py::parse_date`, `pkg/mod.py::Class.method`.
Files: just the relative path.

---

## 5. Target project structure (proposal — refine but keep the spirit)

```
semnav-gp/
├── CLAUDE.md
├── README.md                  # overview, setup, how to run each step, results table
├── pyproject.toml             # or requirements.txt (+ requirements-dev.txt)
├── .env.example               # all configurable paths/params, committed
├── .env                       # local, git-ignored
├── .gitignore                 # data/, .env, __pycache__, .venv, *.pkl, logs/, outputs/, repos/
├── configs/                   # optional YAML for experiment params
│   (data lives OUTSIDE the repo at $DATA_DIR = D:\semnav-data — not in OneDrive)
$DATA_DIR/
│   ├── raw/                   # benchmark files (jsonl), cloned repos (one working copy per repo, checked out per commit)
│   ├── interim/               # temporary files
│   └── processed/             # graphs, indexes, cues, gold labels, stats
├── src/semnav_gp/
│   ├── __init__.py
│   ├── helpers/
│   │   ├── config.py          # pydantic-settings: reads .env
│   │   └── logging.py
│   ├── models/                # pydantic/dataclass schemas: Instance, Entity, Edge, RelationSite, Cue, GoldLabel
│   ├── collection/
│   │   ├── dataset_loader.py  # load SWE-bench Lite (HF or local jsonl fallback)
│   │   └── repo_manager.py    # clone once, checkout per base_commit, dedupe
│   ├── preprocessing/
│   │   ├── gold_labels.py     # P1
│   │   ├── ast_parser.py      # P2
│   │   ├── graph_builder.py   # P3
│   │   ├── entity_index.py    # P4
│   │   └── issue_cues.py      # P5
│   ├── analysis/
│   │   └── stats.py           # P6
│   └── resolution/
│       └── pyright_resolver.py  # later phase (stub now)
├── scripts/
│   └── run_pipeline.py        # CLI: --step collect|gold|graph|index|cues|stats|all --limit N --instances ...
├── notebooks/
│   └── 01_data_exploration.ipynb  # seminar figures
├── tests/                     # small unit tests on toy repos (ast_parser, graph_builder, issue_cues, gold_labels)
└── docs/
    └── seminar1.md            # what we did + stats, for the presentation
```

### 5.1 Output artifacts (per instance unless noted)
- `processed/gold/{instance_id}.json` — `{files: [...], functions: [...]}`
- `processed/graphs/{repo}__{commit}.json` (node-link JSON) or `.pkl` — nodes, resolved edges, unresolved sites
- `processed/index/{repo}__{commit}/` — BM25 index + entity id mapping
- `processed/cues/{instance_id}.json` — typed cues
- `processed/stats/*.csv` + figures
- `logs/skipped_files.csv`

### 5.2 Suggested schemas
- **Entity**: `id, type(file|class|function), name, qualified_name, file_path, start_line, end_line, signature, docstring, code`
- **Edge (resolved)**: `src, dst, type(Contains|Calls|Imports|Inherits|References)`
- **RelationSite (unresolved)**: `src_entity, kind(Calls|References|Inherits|Imports), file_path, line, col, raw_text, target_name`
  (`line`/`col` = position of the target name token, LSP-ready; see §3.2)
- Graph files store entities **without** code; code/text goes in a separate `entities.jsonl` to keep graphs small.
- **Cue**: `kind(file_path|identifier|call|exception|traceback_frame|code_span), value, span`

---

## 6. Size estimate (seminar scope)

| Module | Origin | ~Lines |
|---|---|---|
| dataset_loader + repo_manager | adapt LocAgent | ~100–150 |
| gold_labels | adapt LocAgent | ~150 |
| ast_parser | adapt LocAgent (`CodeAnalyzer`) | ~300 |
| graph_builder | adapt LocAgent + unresolved sites + References | ~250 |
| entity_index | adapt (bm25s) | ~100 |
| issue_cues | **new** | ~120 |
| stats | **new** | ~150 |
| run_pipeline CLI + config | **new** | ~80–100 |
| pyright_resolver (later) | **new** | ~150 |
| **Total (seminar)** | ~8 modules | **~1,200–1,300** |

---

## 7. Execution plan (do in this order; stop and report after each)

1. **Scaffold**: structure above, `.gitignore`, `.env.example`, `config.py`, README skeleton, venv, `git init`, first commit.
2. **Collect**: load SWE-bench Lite (HF `princeton-nlp/SWE-bench_Lite`, fallback to XAgent's jsonl); clone 12 repos
   into `D:\semnav-data`; verify every `base_commit` exists (checkout happens per instance in P1–P4). Start with `--limit 10`, then full.
3. **P1 gold labels** → validate against CoSIL `gt.json`; report agreement %.
4. **P2 + P3 AST + graph** on a tiny toy repo first (with unit tests), then 1 real instance, then a sample (~30), then all.
5. **P4 index**, quick sanity query (search an issue → are gold functions in top-k?).
6. **P5 cues** for all 300; report how often a cue directly names a gold file/function.
7. **P6 stats + notebook** figures for the seminar; write `docs/seminar1.md`.
8. (Optional) Pyright smoke test on a few unresolved sites (`pip install pyright`, needs Node).

Run long batch jobs with progress bars, resumable (skip outputs that already exist), multiprocessing optional.

---

## 8. Later phases (not now — for context)
- Pyright-based on-demand resolution integrated with the graph.
- Agent tools: Search, Expand, Read, Update, Compare, Submit; Candidate Workspace; Semantic Cards + cache.
- LLM backend: paper uses Gemma 4B (gemma-4-e4b-it) / Qwen3.5 → needs a GPU or an API key (this is where the student must provide access).
- Evaluation on SWE-bench Lite (+ PLocBench, SWE-Explore if obtainable) vs baselines (LocAgent, CoSIL, Agentless, ...).

## 9. Open questions to confirm with me
- ~~OS and Python version~~ → answered: Windows 11, Python 3.12 venv, git 2.56, Node 24; C: ~64 GB, D: ~29 GB free.
- ~~`DATA_DIR` location~~ → answered: `D:\semnav-data`.
- Where the code lives: local only or a GitHub repo for the team.
- Run the graph build on all 300 instances or a sample for the seminar.
- Whether to also collect PLocBench and SWE-Explore now (availability not yet verified) or only SWE-bench Lite.
