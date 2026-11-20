from pathlib import Path

from traceagent.preprocessing.entity_index import BM25Index, build_index, entity_texts, tokenize
from traceagent.preprocessing.graph_builder import build_from_sources

SRC = {
    "app/dates.py": (
        '"""Date helpers."""\n'
        "import re\n"
        "\n"
        "\n"
        "def parse_date(value):\n"
        '    """Parse an ISO date string."""\n'
        "    return re.match(r'\\d+', value)\n"
        "\n"
        "\n"
        "class HTTPResponse:\n"
        "    status_code = 200\n"
        "\n"
        "    def render_body(self):\n"
        "        secret_body_token = 1\n"
        "        return secret_body_token\n"
    ),
    "tests/test_dates.py": "def test_parse_date():\n    assert parse_date('2020')\n",
}


def test_tokenize_splits_snake_and_camel_case():
    toks = tokenize("def parse_date(self): return HTTPResponse.status_code")
    assert {"parse_date", "parse", "date", "httpresponse", "http", "response", "status_code", "status", "code"} <= set(toks)
    assert "def" not in toks and "self" not in toks and "return" not in toks


def _texts():
    g = build_from_sources({k: v.encode() for k, v in SRC.items()})
    lines = {k: v.split("\n") for k, v in SRC.items()}
    return g, dict(zip([e.id for e in g.entities], entity_texts(g.entities, lines)))


def test_entity_text_contents():
    _, t = _texts()
    fn = t["app/dates.py::parse_date"]
    assert "parse_date" in fn and "Parse an ISO date string" in fn  # name + docstring + code
    cls = t["app/dates.py::HTTPResponse"]
    assert "status_code = 200" in cls and "def render_body(self)" in cls  # own lines + method signature
    assert "secret_body_token" not in cls  # method BODY is not repeated in the class text
    f = t["app/dates.py"]
    assert "Date helpers" in f and "import re" in f and "def parse_date(value)" in f
    assert "re.match" not in f  # function body not repeated in the file text


def test_bm25_ranks_the_right_entity_and_filters(tmp_path: Path):
    g, _ = _texts()
    idx = build_index(g.entities, SRC)
    top = idx.search(tokenize("Bug when I parse a date string"), top_k=3, types={"function"})
    assert top[0][0] in {"app/dates.py::parse_date", "tests/test_dates.py::test_parse_date"}
    top_nt = idx.search(tokenize("Bug when I parse a date string"), top_k=3, types={"function"}, exclude_tests=True)
    assert top_nt[0][0] == "app/dates.py::parse_date"
    assert all(not i.startswith("tests/") for i, _ in top_nt)
    # save / load round trip gives identical scores
    idx.save(tmp_path)
    idx2 = BM25Index.load(tmp_path)
    q = tokenize("http response status")
    assert idx.search(q, 5) == idx2.search(q, 5)


def test_bm25_matches_textbook_formula():
    docs = [["a", "b", "a"], ["b", "c"], ["c", "c", "c", "d"]]
    idx = BM25Index.build(docs, ["d0", "d1", "d2"], [False] * 3, ["function"] * 3, k1=1.2, b=0.75)
    import math
    n, avg = 3, (3 + 2 + 4) / 3
    idf_a = math.log(1 + (n - 1 + 0.5) / (1 + 0.5))
    expected = idf_a * 2 * 2.2 / (2 + 1.2 * (1 - 0.75 + 0.75 * 3 / avg))
    assert abs(idx.scores(["a"])[0] - expected) < 1e-5
    assert idx.scores(["zzz"]).sum() == 0
