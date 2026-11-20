"""Schemas of the Semantic Navigation Graph (SNG).

Plain dataclasses (not pydantic): a big repo produces hundreds of thousands of records.
"""

from dataclasses import asdict, dataclass, field

EDGE_TYPES = ("Contains", "Calls", "Imports", "Inherits", "References")


@dataclass
class Entity:
    id: str  # "pkg/mod.py" (file) | "pkg/mod.py::Class.method"
    type: str  # "file" | "class" | "function"
    name: str  # short name: "method" (file: "mod.py")
    qualified_name: str  # "Class.method" (file: "" )
    file_path: str
    start_line: int  # 1-based, includes decorators
    end_line: int
    signature: str = ""  # "def parse(self, text)" / "class Parser(Base)"
    is_test: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Edge:
    """Resolved edge (u, r, v, l) — the target is known syntactically."""

    src: str
    dst: str
    type: str  # one of EDGE_TYPES
    line: int  # first source line where the relation appears
    count: int = 1  # how many times this (src, dst, type) appears

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RelationSite:
    """Unresolved edge (u, r, l) — the target is left to Pyright (later phase).

    `line` is 1-based; `col` is in UTF-16 code units and points at the TARGET NAME token
    (e.g. at `run` in `obj.run()`), so it can be sent to an LSP after `line - 1`.
    """

    src: str
    kind: str  # "Calls" | "Imports" | "Inherits" | "References"
    file_path: str
    line: int
    col: int
    raw_text: str  # e.g. "self.helper" / "obj.run"
    target_name: str  # e.g. "helper" / "run"
    count: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GraphStats:
    files_total: int = 0
    files_parsed: int = 0
    skipped: dict = field(default_factory=dict)  # reason -> count
    entities: dict = field(default_factory=dict)  # type -> count
    entities_non_test: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)  # type -> count
    sites: dict = field(default_factory=dict)  # kind -> count
    external: dict = field(default_factory=dict)  # kind -> count (stdlib / builtins / third-party)
    dropped_local: int = 0  # names bound locally (variables / parameters)
    dropped_unknown: int = 0  # names not defined anywhere we can see and not matching any repo entity

    def to_dict(self) -> dict:
        return asdict(self)
