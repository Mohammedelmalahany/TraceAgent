"""Minimal unified-diff parser (enough for SWE-bench gold patches).

A patch is a list of FilePatch; each FilePatch has hunks; each hunk has lines tagged ' ', '-', '+'.
We keep the OLD line number of every ' ' and '-' line, which is what P1 needs.

Robustness: a hunk header says how many old/new lines follow (`@@ -12,5 +12,7 @@`). We count them down,
so a removed line such as "-- sql comment" (raw "--- sql comment") is never mistaken for a file header.
"""

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class HunkLine:
    tag: str  # ' ' context, '-' removed, '+' added
    text: str
    old_lineno: int | None  # line number in the OLD file (None for '+')
    new_lineno: int | None = None  # line number in the NEW file (None for '-')


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[HunkLine] = field(default_factory=list)


@dataclass
class FilePatch:
    old_path: str | None  # None when the file is newly created
    new_path: str | None  # None when the file is deleted
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.old_path or self.new_path  # type: ignore[return-value]

    @property
    def is_new_file(self) -> bool:
        return self.old_path is None


def _strip_prefix(p: str) -> str | None:
    p = p.strip().split("\t")[0]
    if p == "/dev/null":
        return None
    return p[2:] if p.startswith(("a/", "b/")) else p


def parse_patch(patch: str) -> list[FilePatch]:
    files: list[FilePatch] = []
    cur: FilePatch | None = None
    hunk: Hunk | None = None
    old_left = new_left = 0  # lines still expected in the current hunk
    old_no = new_no = 0

    for raw in split_lines(patch):
        in_hunk = hunk is not None and (old_left > 0 or new_left > 0)

        if not in_hunk:
            if raw.startswith("--- "):
                cur = FilePatch(old_path=_strip_prefix(raw[4:]), new_path=None)
                files.append(cur)
                hunk = None
            elif raw.startswith("+++ ") and cur is not None:
                cur.new_path = _strip_prefix(raw[4:])
            elif (m := _HUNK_RE.match(raw)) and cur is not None:
                hunk = Hunk(
                    old_start=int(m.group(1)), old_len=int(m.group(2) if m.group(2) is not None else 1),
                    new_start=int(m.group(3)), new_len=int(m.group(4) if m.group(4) is not None else 1),
                )
                cur.hunks.append(hunk)
                old_left, new_left = hunk.old_len, hunk.new_len
                old_no, new_no = hunk.old_start, hunk.new_start
            continue  # "diff --git", "index ...", "\ No newline", etc.

        tag, text = (raw[0], raw[1:]) if raw else (" ", "")  # empty line = context with stripped space
        if tag == "\\":  # "\ No newline at end of file"
            continue
        if tag == "+":
            hunk.lines.append(HunkLine("+", text, None, new_no))
            new_no += 1
            new_left -= 1
        elif tag == "-":
            hunk.lines.append(HunkLine("-", text, old_no, None))
            old_no += 1
            old_left -= 1
        else:  # context
            hunk.lines.append(HunkLine(" ", text, old_no, new_no))
            old_no += 1
            new_no += 1
            old_left -= 1
            new_left -= 1
    return files


def split_lines(text: str) -> list[str]:
    """Split on real line breaks only (\\n, \\r\\n, \\r) — the same way `ast` and git count lines.

    NOTE: str.splitlines() also splits on \\x0c, \\x1c, \\u2028, ... which shifts line numbers
    in files that contain those characters (found in sympy).
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _find_block(old_lines: list[str], block: list[str], expected: int, lo: int) -> int | None:
    """0-based index (>= lo) where `block` occurs in old_lines, closest to `expected`. Exact match first,
    then a whitespace-insensitive match (like `patch` with --ignore-whitespace)."""
    n = len(block)
    for norm in (lambda s: s, lambda s: s.rstrip()):
        b = [norm(x) for x in block]
        hits = [p for p in range(lo, len(old_lines) - n + 1)
                if norm(old_lines[p]) == b[0] and [norm(x) for x in old_lines[p:p + n]] == b]
        if hits:
            return min(hits, key=lambda p: abs(p - expected))
    return None


def relocate_hunks(old_text: str, fp: FilePatch) -> dict:
    """Fix hunk positions by matching their context text against the real old file.

    Some SWE-bench patches have line numbers that do not match the file at base_commit (e.g. sympy-14317 is
    off by 41 lines). `git apply` / `patch` tolerate this by matching context; we do the same and rewrite
    `old_start` and every `old_lineno`. Returns {"offset_hunks": n, "unmatched_hunks": m}.
    """
    old_lines = split_lines(old_text)
    offset_hunks = unmatched = 0
    lo = 0
    for h in fp.hunks:
        block = [ln.text for ln in h.lines if ln.tag in (" ", "-")]
        if not block:  # pure insertion without context: trust the header
            continue
        expected = h.old_start - 1
        p = _find_block(old_lines, block, expected, lo)
        if p is None:
            unmatched += 1
            continue
        delta = p - expected
        if delta:
            offset_hunks += 1
            h.old_start += delta
            for ln in h.lines:
                if ln.old_lineno is not None:
                    ln.old_lineno += delta
        lo = p + len(block)
    return {"offset_hunks": offset_hunks, "unmatched_hunks": unmatched}


def apply_patch_to_text(old_text: str, fp: FilePatch) -> str:
    """Rebuild the NEW file content from the OLD content + hunks (in memory, no `git apply`).

    Also (re)assigns `new_lineno` of every '+' / ' ' line so it matches the rebuilt file exactly.
    """
    old_lines = split_lines(old_text)
    out: list[str] = []
    pos = 0  # 0-based index into old_lines
    for h in fp.hunks:
        # old_len == 0 means a pure insertion AFTER old line `old_start`.
        start = h.old_start if h.old_len == 0 else h.old_start - 1
        out.extend(old_lines[pos:start])
        pos = start
        for ln in h.lines:
            if ln.tag == " ":
                out.append(old_lines[pos] if pos < len(old_lines) else ln.text)
                ln.new_lineno = len(out)
                pos += 1
            elif ln.tag == "-":
                pos += 1
            else:
                out.append(ln.text)
                ln.new_lineno = len(out)
    out.extend(old_lines[pos:])
    return "\n".join(out) + "\n"
