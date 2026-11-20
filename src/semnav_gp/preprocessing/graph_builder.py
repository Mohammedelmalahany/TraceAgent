"""P3 — build the Semantic Navigation Graph from all parsed files of one snapshot.

For every raw site the builder asks: is the target *syntactically determined*? [ours, CLAUDE.md §3.2]

  resolved   -> Edge(src, dst, type)       the name leads, by static lookup only, to ONE repo entity:
                                           same-file definition, an explicit import, a module attribute
                                           (`models.Field`), or a member defined directly in a known class.
  unresolved -> RelationSite(...)          it depends on runtime values / inheritance (`obj.run()`, `self.x()`,
                                           `super().f()`), or the lookup reaches a repo module but stops.
  external   -> only counted                stdlib / builtins / third-party (`print`, `os.path.join`).
  dropped    -> only counted                local variables / parameters, or unknown names that match no
                                           repo entity (References filter).

We never guess: no "link to every function called `run`" (that is LocAgent's behaviour).
"""

import builtins
from collections import Counter
from dataclasses import dataclass, field

from semnav_gp.models.graph import Edge, Entity, GraphStats, RelationSite
from semnav_gp.preprocessing.ast_parser import FileParse, ImportBinding, RawSite, SkipFile, parse_file

BUILTIN_NAMES = set(dir(builtins))
SELF_NAMES = {"self", "cls"}
MAX_REEXPORT_DEPTH = 4

# result of a lookup
RESOLVED, UNRESOLVED, EXTERNAL, LOCAL, UNKNOWN = "resolved", "unresolved", "external", "local", "unknown"


@dataclass
class SNG:
    entities: list[Entity] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    sites: list[RelationSite] = field(default_factory=list)
    stats: GraphStats = field(default_factory=GraphStats)
    skipped: list[dict] = field(default_factory=list)  # {"file", "reason", "detail"}


def module_names(paths: list[str]) -> dict[str, tuple[str, bool]]:
    """path -> (dotted module, is_package). A file's module starts at the top-most directory of its
    chain of packages (dirs with __init__.py), so `lib/matplotlib/axes/_base.py` -> `matplotlib.axes._base`."""
    pyset = set(paths)
    out = {}
    for p in paths:
        parts = p[:-3].split("/")
        is_pkg = parts[-1] == "__init__"
        if is_pkg:
            parts = parts[:-1]
        dirs = p.split("/")[:-1]
        # walk up while the directory is a package
        k = len(dirs)
        while k > 0 and "/".join(dirs[:k] + ["__init__.py"]) in pyset:
            k -= 1
        mod_parts = parts[k:]
        out[p] = (".".join(mod_parts), is_pkg)
    return out


class _Resolver:
    def __init__(self, files: dict[str, FileParse]):
        self.files = files
        self.mod2file: dict[str, str] = {}
        for path, fp in sorted(files.items(), key=lambda kv: (kv[1].is_test, kv[0])):
            if fp.module:
                self.mod2file.setdefault(fp.module, path)  # prefer non-test on collisions
        self.top_level_pkgs = {m.split(".")[0] for m in self.mod2file}
        self.entity_type = {e.id: e.type for fp in files.values() for e in fp.entities}
        self.short_names = {e.name for fp in files.values() for e in fp.entities if e.type != "file"}

    # --- module / binding lookups ------------------------------------------------------------
    def in_repo_module(self, module: str) -> bool:
        return module.split(".")[0] in self.top_level_pkgs

    def module_attr(self, module: str, attr: str, depth: int = 0) -> tuple[str, str | None]:
        """Look up `attr` in repo module `module`: a top-level def, a submodule, or a re-exported import."""
        path = self.mod2file.get(module)
        if path is not None:
            fp = self.files[path]
            if attr in fp.top_defs:
                return RESOLVED, fp.top_defs[attr]
        sub = f"{module}.{attr}" if module else attr
        if sub in self.mod2file:
            return RESOLVED, self.mod2file[sub]
        if path is not None and attr in self.files[path].imports and depth < MAX_REEXPORT_DEPTH:
            return self.binding_target(self.files[path].imports[attr], depth + 1)
        if path is not None and depth < MAX_REEXPORT_DEPTH:  # re-export via `from .fields import *`
            for star_mod in self.files[path].star_imports:
                if self.in_repo_module(star_mod) and star_mod != module:
                    st, tgt = self.module_attr(star_mod, attr, depth + 1)
                    if st == RESOLVED:
                        return st, tgt
        if path is not None and attr in self.files[path].module_vars:
            return RESOLVED, path  # a module-level variable: the target is that file

        return (UNRESOLVED, None) if self.in_repo_module(module) else (EXTERNAL, None)

    def binding_target(self, b: ImportBinding, depth: int = 0) -> tuple[str, str | None]:
        if not self.in_repo_module(b.module):
            return EXTERNAL, None
        if b.name is None:  # `import pkg.mod` -> the module (file) itself
            path = self.mod2file.get(b.module)
            return (RESOLVED, path) if path else (UNRESOLVED, None)
        return self.module_attr(b.module, b.name, depth)

    def walk_attrs(self, status: str, target: str | None, attrs: list[str]) -> tuple[str, str | None]:
        """Continue `target.attr1.attr2...` statically: module attribute or a class's own member."""
        for i, attr in enumerate(attrs):
            if status != RESOLVED:
                return status, target
            kind = self.entity_type.get(target)
            if kind == "file":
                prev = target
                status, target = self.module_attr(self.files[target].module, attr)
                if status == RESOLVED and target == prev and i < len(attrs) - 1:
                    return UNRESOLVED, None  # `mod.CONST.x`: attribute of a module variable's value
            elif kind == "class":
                member = self.files[target.split("::")[0]].class_members.get(target, {}).get(attr)
                status, target = (RESOLVED, member) if member else (UNRESOLVED, None)  # may be inherited
            else:  # attribute of a function object / instance -> runtime
                return UNRESOLVED, None
        return status, target

    # --- names ---------------------------------------------------------------------------------
    def lookup_chain(self, fp: FileParse, src: str, chain: tuple[str, ...]) -> tuple[str, str | None]:
        head, rest = chain[0], list(chain[1:])
        fn_id = src if self.entity_type.get(src) == "function" else None
        local_tbl = fp.local_imports.get(src, {})
        if head in local_tbl:
            return self.walk_attrs(*self.binding_target(local_tbl[head]), rest)
        if head in SELF_NAMES or (fn_id and head in fp.locals.get(fn_id, set())):
            # a local value: `x` alone is just a variable; `obj.run` / `self.x` depend on its runtime type
            return (UNRESOLVED, None) if rest else (LOCAL, None)
        if head in fp.top_defs:
            return self.walk_attrs(RESOLVED, fp.top_defs[head], rest)
        if head in fp.imports:
            return self.walk_attrs(*self.binding_target(fp.imports[head]), rest)
        if head in BUILTIN_NAMES:
            return EXTERNAL, None
        for star_mod in fp.star_imports:  # `from repo.mod import *`: deterministic if mod defines it
            if self.in_repo_module(star_mod):
                st, tgt = self.module_attr(star_mod, head)
                if st == RESOLVED:
                    return self.walk_attrs(st, tgt, rest)
        return (UNRESOLVED, None) if chain[-1] in self.short_names else (UNKNOWN, None)


def build_graph(files: dict[str, FileParse]) -> SNG:
    """Resolve every raw site of a snapshot into edges / unresolved sites / counters."""
    r = _Resolver(files)
    g = SNG()
    stats = g.stats
    edge_index: dict[tuple[str, str, str], Edge] = {}
    external, ent_count, ent_non_test = Counter(), Counter(), Counter()

    def add_edge(src: str, dst: str, kind: str, line: int, count: int = 1) -> None:
        key = (src, dst, kind)
        if key in edge_index:
            edge_index[key].count += count
        else:
            edge_index[key] = Edge(src, dst, kind, line, count)

    for path, fp in sorted(files.items()):
        for e in fp.entities:
            g.entities.append(e)
            ent_count[e.type] += 1
            if not e.is_test:
                ent_non_test[e.type] += 1
        ent_line = {e.id: e.start_line for e in fp.entities}
        for parent, child in fp.contains:
            add_edge(parent, child, "Contains", ent_line[child])

        for s in fp.sites:
            status, target = resolve_site(r, fp, s)
            if status == RESOLVED and target is not None:
                add_edge(s.src, target, s.kind, s.line, s.count)
            elif status == UNRESOLVED:
                g.sites.append(RelationSite(s.src, s.kind, path, s.line, s.col, s.raw_text, s.target_name, s.count))
            elif status == EXTERNAL:
                external[s.kind] += s.count
            elif status == LOCAL:
                stats.dropped_local += s.count
            else:
                stats.dropped_unknown += s.count

    g.edges = list(edge_index.values())
    stats.entities, stats.entities_non_test = dict(ent_count), dict(ent_non_test)
    stats.edges = dict(Counter(e.type for e in g.edges))
    stats.sites = dict(Counter(s.kind for s in g.sites))
    stats.external = dict(external)
    return g


def resolve_site(r: _Resolver, fp: FileParse, s: RawSite) -> tuple[str, str | None]:
    if s.kind == "Imports":
        b = s.binding
        if b is None:
            return UNKNOWN, None
        if b.name is None:  # `import a.b.c` / star import -> module file
            path = r.mod2file.get(b.module)
            if path:
                return RESOLVED, path
            return (UNRESOLVED, None) if r.in_repo_module(b.module) else (EXTERNAL, None)
        return r.binding_target(b)
    if s.chain is None:  # e.g. `self.get(x).run()`, `foo()[0].bar()`: depends on a runtime value
        return (UNRESOLVED, None) if s.kind == "Calls" or s.target_name in r.short_names else (UNKNOWN, None)
    status, target = r.lookup_chain(fp, s.src, s.chain)
    if status == UNRESOLVED and s.kind == "References" and s.target_name not in r.short_names:
        return UNKNOWN, None  # References filter: keep only names that could be repo entities
    if status == UNRESOLVED and s.kind == "Calls" and len(s.chain) == 1 and s.target_name not in r.short_names:
        return UNKNOWN, None  # bare call to a name defined nowhere in the repo
    return status, target


def build_from_sources(sources: dict[str, bytes], max_kb: int = 1024) -> SNG:
    """Parse + build. `sources` maps repo-relative POSIX paths of .py files to their raw bytes."""
    py_paths = sorted(p for p in sources if p.endswith(".py"))
    mods = module_names(py_paths)
    files: dict[str, FileParse] = {}
    skipped: list[dict] = []
    for p in py_paths:
        module, is_pkg = mods[p]
        try:
            files[p] = parse_file(p, sources[p], module, is_pkg, max_kb=max_kb)
        except SkipFile as exc:
            skipped.append({"file": p, "reason": exc.reason, "detail": exc.detail})
    g = build_graph(files)
    g.skipped = skipped
    g.stats.files_total = len(py_paths)
    g.stats.files_parsed = len(files)
    g.stats.skipped = dict(Counter(s["reason"] for s in skipped))
    return g
