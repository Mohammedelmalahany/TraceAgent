"""P4 — entity text representation + BM25 index.

Entity text D(v) [paper]: qualified name + declaration + documentation + implementation.
How we build it [ours]:
- function: file path + qualified name + signature + its source lines (docstring included).
- class:    file path + qualified name + signature + its own source lines, where each method / nested class body is
            replaced by its signature line (so a class does not repeat all its methods' code).
- file:     path + module-level source lines, with every top-level class / function body replaced by its signature.
Tokenizer [ours]: identifiers are split on snake_case and camelCase, lower-cased, and the full identifier is kept
too (`parse_date` -> `parse_date`, `parse`, `date`). Python keywords and very common English words are dropped.

BM25 is implemented directly with a sparse matrix (no extra library), so every number is easy to explain:
    score(doc, query) = sum over query terms t of  idf(t) * tf(t,doc) * (k1+1) / (tf(t,doc) + k1 * (1 - b + b*len/avg))
"""

import json
import keyword
import re
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import sparse

from semnav_gp.models.graph import Entity
from semnav_gp.preprocessing.patch_parser import split_lines

# ----------------------------------------------------------------------------- tokenizer

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
STOPWORDS = set(keyword.kwlist) | {
    "self", "cls", "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "be", "for", "on", "this", "that",
    "with", "as", "are", "was", "by", "at", "from", "if", "not", "no", "but", "can", "we", "i", "you", "will",
    "would", "should", "there", "which", "when", "then", "than", "so", "do", "does", "have", "has", "been",
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for ident in _IDENT_RE.findall(text):
        low = ident.lower().strip("_")
        if len(low) < 2:
            continue
        parts = [p.lower() for chunk in ident.split("_") for p in _CAMEL_RE.findall(chunk)]
        if low not in STOPWORDS:
            tokens.append(low)
        if len(parts) > 1:
            tokens.extend(p for p in parts if len(p) > 1 and p not in STOPWORDS and p != low)
    return tokens


# ----------------------------------------------------------------------------- entity text

def _base_id(eid: str) -> str:
    return eid.split("@")[0]


def _parent_id(e: Entity) -> str:
    """Direct parent: 'f.py::A.B.m' -> 'f.py::A.B' ; top-level -> the file."""
    if e.type == "file":
        return ""
    qual = _base_id(e.id).split("::", 1)[1]
    return f"{e.file_path}::{qual.rsplit('.', 1)[0]}" if "." in qual else e.file_path


def entity_texts(entities: list[Entity], file_lines: dict[str, list[str]]) -> list[str]:
    """One text per entity, in the same order as `entities`."""
    children: dict[str, list[Entity]] = {}
    for e in entities:
        if e.type != "file":
            children.setdefault(_parent_id(e), []).append(e)

    texts = []
    for e in entities:
        lines = file_lines.get(e.file_path, [])
        own = lines[e.start_line - 1:e.end_line]
        if e.type != "function":  # replace children's bodies by their signatures
            keep = [True] * len(own)
            sigs = []
            for c in children.get(_base_id(e.id), []):
                for ln in range(c.start_line, c.end_line + 1):
                    if 0 <= ln - e.start_line < len(keep):
                        keep[ln - e.start_line] = False
                sigs.append(c.signature)
            own = [ln for ln, k in zip(own, keep) if k] + sigs
        header = f"{e.file_path} {e.qualified_name} {e.signature}"
        texts.append(header + "\n" + "\n".join(own))
    return texts


# ----------------------------------------------------------------------------- BM25

class BM25Index:
    """Sparse BM25: `weights` is a (n_docs x n_terms) matrix; a query score is a sum of columns."""

    def __init__(self, weights: sparse.csc_matrix, vocab: dict[str, int], ids: list[str], is_test: np.ndarray,
                 types: list[str]):
        self.weights, self.vocab, self.ids, self.is_test, self.types = weights, vocab, ids, is_test, types

    @classmethod
    def build(cls, docs: list[list[str]], ids: list[str], is_test: list[bool], types: list[str],
              k1: float = 1.2, b: float = 0.75) -> "BM25Index":
        vocab: dict[str, int] = {}
        rows, cols, tfs = [], [], []
        lengths = np.zeros(len(docs), dtype=np.float32)
        for i, toks in enumerate(docs):
            lengths[i] = len(toks)
            for t, c in Counter(toks).items():
                rows.append(i)
                cols.append(vocab.setdefault(t, len(vocab)))
                tfs.append(c)
        tf = np.asarray(tfs, dtype=np.float32)
        rows_a, cols_a = np.asarray(rows, dtype=np.int64), np.asarray(cols, dtype=np.int64)
        n = max(len(docs), 1)
        df = np.bincount(cols_a, minlength=len(vocab)).astype(np.float32)
        idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
        avg = float(lengths.mean()) if len(docs) else 1.0
        norm = k1 * (1 - b + b * lengths[rows_a] / max(avg, 1e-9))
        w = idf[cols_a] * tf * (k1 + 1) / (tf + norm)
        weights = sparse.csc_matrix((w.astype(np.float32), (rows_a, cols_a)), shape=(len(docs), len(vocab)))
        return cls(weights, vocab, ids, np.asarray(is_test, dtype=bool), types)

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        cols = [self.vocab[t] for t in set(query_tokens) if t in self.vocab]
        if not cols:
            return np.zeros(len(self.ids), dtype=np.float32)
        return np.asarray(self.weights[:, cols].sum(axis=1)).ravel()

    def search(self, query_tokens: list[str], top_k: int = 10, types: set[str] | None = None,
               exclude_tests: bool = False) -> list[tuple[str, float]]:
        s = self.scores(query_tokens)
        mask = np.ones(len(s), dtype=bool)
        if types is not None:
            mask &= np.isin(np.asarray(self.types), list(types))
        if exclude_tests:
            mask &= ~self.is_test
        s = np.where(mask, s, -np.inf)
        k = min(top_k, int(mask.sum()))
        if k == 0:
            return []
        top = np.argpartition(-s, k - 1)[:k]
        top = top[np.argsort(-s[top], kind="stable")]
        return [(self.ids[i], float(s[i])) for i in top if s[i] > 0]

    # --- persistence
    def save(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        sparse.save_npz(out_dir / "bm25_weights.npz", self.weights.tocsc(), compressed=True)
        terms = [None] * len(self.vocab)
        for t, j in self.vocab.items():
            terms[j] = t
        meta = {"terms": terms, "ids": self.ids, "is_test": self.is_test.tolist(), "types": self.types}
        (out_dir / "bm25_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    @classmethod
    def load(cls, in_dir: Path) -> "BM25Index":
        weights = sparse.load_npz(in_dir / "bm25_weights.npz").tocsc()
        meta = json.loads((in_dir / "bm25_meta.json").read_text(encoding="utf-8"))
        vocab = {t: j for j, t in enumerate(meta["terms"])}
        return cls(weights, vocab, meta["ids"], np.asarray(meta["is_test"], dtype=bool), meta["types"])


def build_index(entities: list[Entity], file_text: dict[str, str]) -> BM25Index:
    file_lines = {p: split_lines(t) for p, t in file_text.items()}
    texts = entity_texts(entities, file_lines)
    docs = [tokenize(t) for t in texts]
    return BM25Index.build(docs, [e.id for e in entities], [e.is_test for e in entities], [e.type for e in entities])
