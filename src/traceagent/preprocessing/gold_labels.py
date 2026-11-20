"""P1 — gold labels: which files / functions did the real fix (`patch`) change?

Rules [see docs/seminar1.md, P1]:
- Only `patch` is used (never `test_patch`).
- '-' lines are located with the OLD file's AST; '+' lines with the NEW file's AST
  (new file = old file + patch, rebuilt in memory).
- A '+' line inside a function that already existed  -> that function was modified.
- A '+' line inside a function that did NOT exist     -> added function (not localizable pre-patch).
- A changed line outside any function                 -> class-level edit (inside a class body) or module-level edit.
- Blank / whitespace-only changed lines are ignored.
- Nested functions are folded into their enclosing top-level function/method.
"""

import ast
import warnings
from dataclasses import dataclass, field

from traceagent.preprocessing.patch_parser import FilePatch, apply_patch_to_text, parse_patch, relocate_hunks


@dataclass(frozen=True)
class Scope:
    qualname: str  # e.g. "Parser.parse"
    kind: str  # "class" | "function"
    start: int  # first line (including decorators)
    end: int  # last line


def collect_scopes(source: str) -> list[Scope]:
    """All classes (incl. nested) and functions/methods; functions inside functions are not separate scopes."""
    with warnings.catch_warnings():  # old code triggers e.g. "invalid escape sequence" SyntaxWarnings
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    scopes: list[Scope] = []

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([d.lineno for d in node.decorator_list] + [node.lineno])
                qual = f"{prefix}{node.name}"
                if isinstance(node, ast.ClassDef):
                    scopes.append(Scope(qual, "class", start, node.end_lineno))
                    visit(node.body, qual + ".")
                else:
                    scopes.append(Scope(qual, "function", start, node.end_lineno))
                    # do not descend: nested functions are folded into this one
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                # e.g. `if sys.version_info > ...: def f(): ...` at module/class level
                for field in ("body", "orelse", "finalbody", "handlers"):
                    for child in getattr(node, field, []) or []:
                        visit(child.body if isinstance(child, ast.ExceptHandler) else [child], prefix)

    visit(tree.body, "")
    return scopes


def innermost_scope(scopes: list[Scope], line: int) -> Scope | None:
    best = None
    for s in scopes:
        if s.start <= line <= s.end and (best is None or s.end - s.start <= best.end - best.start):
            best = s
    return best


@dataclass
class FileGold:
    path: str
    modified_functions: set[str]
    added_functions: set[str]
    edited_classes: set[str]  # class-body edits outside any method (class existed before the patch)
    module_level: bool  # edits outside any class/function
    added_classes: set[str] = field(default_factory=set)  # classes that only exist after the patch
    parse_error: str | None = None
    offset_hunks: int = 0  # hunks whose header line numbers were wrong (fixed by context matching)
    unmatched_hunks: int = 0  # hunks whose context was not found in the old file


def gold_for_file(fp: FilePatch, old_text: str | None) -> FileGold:
    g = FileGold(fp.path, set(), set(), set(), False)
    if fp.is_new_file or old_text is None or not fp.path.endswith(".py"):
        return g
    reloc = relocate_hunks(old_text, fp)
    g.offset_hunks, g.unmatched_hunks = reloc["offset_hunks"], reloc["unmatched_hunks"]
    try:
        old_scopes = collect_scopes(old_text)
        new_scopes = collect_scopes(apply_patch_to_text(old_text, fp))
    except (SyntaxError, ValueError) as exc:
        g.parse_error = f"{type(exc).__name__}: {exc}"
        return g
    old_functions = {s.qualname for s in old_scopes if s.kind == "function"}
    old_classes = {s.qualname for s in old_scopes if s.kind == "class"}

    def record(scope: Scope | None, existed: bool) -> None:
        if scope is None:
            g.module_level = True
        elif scope.kind == "class":
            if scope.qualname in old_classes:
                g.edited_classes.add(scope.qualname)
            else:  # e.g. `+class _StyleLibrary(dict):` — a brand-new class
                g.added_classes.add(scope.qualname)
        elif existed:
            g.modified_functions.add(scope.qualname)
        else:
            g.added_functions.add(scope.qualname)

    for h in fp.hunks:
        for ln in h.lines:
            if ln.tag == " " or not ln.text.strip():
                continue
            if ln.tag == "-":
                record(innermost_scope(old_scopes, ln.old_lineno), existed=True)
            else:  # '+'
                s = innermost_scope(new_scopes, ln.new_lineno)
                record(s, existed=(s is None or s.kind == "class" or s.qualname in old_functions))
    return g


def extract_gold(patch: str, read_old_file) -> dict:
    """`read_old_file(path) -> str | None` returns the pre-patch content of a file."""
    files, added_files, functions, added_functions, classes, module_files, errors = [], [], [], [], [], [], []
    added_classes: list[str] = []
    offset_hunks = unmatched_hunks = 0
    for fp in parse_patch(patch):
        if fp.is_new_file:
            added_files.append(fp.new_path)
            continue
        g = gold_for_file(fp, read_old_file(fp.path))
        files.append(fp.path)
        functions += [f"{fp.path}::{q}" for q in sorted(g.modified_functions)]
        added_functions += [f"{fp.path}::{q}" for q in sorted(g.added_functions)]
        classes += [f"{fp.path}::{q}" for q in sorted(g.edited_classes)]
        added_classes += [f"{fp.path}::{q}" for q in sorted(g.added_classes)]
        if g.module_level:
            module_files.append(fp.path)
        if g.parse_error:
            errors.append({"file": fp.path, "error": g.parse_error})
        offset_hunks += g.offset_hunks
        unmatched_hunks += g.unmatched_hunks
    return {
        "files": files,
        "functions": functions,
        "added_functions": added_functions,
        "edited_classes": classes,
        "added_classes": added_classes,
        "module_level_files": module_files,
        "added_files": added_files,
        "parse_errors": errors,
        "offset_hunks": offset_hunks,
        "unmatched_hunks": unmatched_hunks,
    }
