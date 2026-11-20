# Seminar 1 — Data Collection & Preprocessing (results log)

## Data collection

| Item | Value |
|---|---|
| Benchmark | SWE-bench Lite (`princeton-nlp/SWE-bench_Lite`, split `test`) |
| Issues | 300 |
| Repositories | 12 (full clones, 1.8 GB total) |
| Unique (repo, base_commit) snapshots | 297 |
| Missing base commits | 0 |

Issues per repo: django 114, sympy 77, matplotlib 23, scikit-learn 23, pytest 17, sphinx 16, astropy 6, requests 6,
pylint 6, xarray 5, seaborn 4, flask 3.

## P1 — Gold labels

Method [ours]: parse the gold `patch` (unified diff); locate `-` lines with the **pre-patch** AST and `+` lines with the
**post-patch** AST (rebuilt in memory). A `+` line in a function that already existed → modified function; in a function
that did not exist → added function; outside any function → class-body or module-level edit. Nested functions are folded
into their enclosing function. Only `patch` is used (never `test_patch`).

| Statistic | Value |
|---|---|
| Files edited per issue | exactly 1 for all 300 issues |
| Mean modified (pre-existing) functions per issue | 1.06 |
| Issues with no modified pre-existing function | 26 |
| Issues that add new functions | 32 |
| Issues with class-body edits / module-level edits | 16 / 46 |
| Parse errors | 0 |

### Data-quality finding: patch line numbers do not always match `base_commit`
In **8 issues (11 hunks)** the hunk headers' line numbers do not match the file at `base_commit`
(e.g. `sympy__sympy-14317`: off by 41 lines). Trusting the numbers would label the wrong function
(`_print_FourierSeries` instead of `_print_Poly`). Like `git apply`, we relocate each hunk by matching its context text
(0 hunks left unmatched).

A second pitfall: Python's `str.splitlines()` also splits on characters such as `\x0c` and ` `, so line numbers can
drift from what `ast` reports. We split on real line breaks only.

### Validation against CoSIL `gt.json`

| Metric | Value |
|---|---|
| File-level agreement | **100%** |
| Exact match of the location set | 79.3% |
| Entry precision / recall (CoSIL as reference) | 79.6% / 86.1% |

Every remaining difference was inspected and falls into a convention difference or a CoSIL labelling error:
- **Added methods:** CoSIL lists the enclosing class; we list the new function separately in `added_functions`.
- **Hunk-header names:** CoSIL sometimes takes the name from the `@@ ... def name` header, which can be a nested
  function or a function that was not edited (e.g. `astropy__astropy-14182` → `get_fixedwidth_params`, untouched).
- **Nested functions:** CoSIL lists them (`_postprocessor`, `fix_style`); we fold them into the parent.
- **Wrong qualification in CoSIL:** e.g. `django__django-10924` (`Field.formfield` vs the actual `FilePathField.formfield`),
  `scikit-learn__scikit-learn-13241` (`fit_transform` vs the actual `_fit_transform`).
