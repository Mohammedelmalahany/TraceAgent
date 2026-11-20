import subprocess
from pathlib import Path

from traceagent.collection import repo_manager as rm
from traceagent.collection.dataset_loader import summarize
from traceagent.models.instance import Instance


def _instance(iid: str, repo: str, commit: str) -> Instance:
    return Instance(
        instance_id=iid, repo=repo, base_commit=commit, problem_statement="x", patch="",
        FAIL_TO_PASS='["test_a"]', PASS_TO_PASS="[]",
    )


def test_instance_parses_json_string_lists() -> None:
    inst = _instance("a__b-1", "a/b", "c1")
    assert inst.FAIL_TO_PASS == ["test_a"]
    assert inst.PASS_TO_PASS == []
    assert inst.repo_dir_name == "a__b"


def test_summarize_dedupes_snapshots() -> None:
    insts = [_instance("1", "a/b", "c1"), _instance("2", "a/b", "c1"), _instance("3", "x/y", "c2")]
    s = summarize(insts)
    assert s["n_instances"] == 3
    assert s["n_repos"] == 2
    assert s["n_unique_snapshots"] == 2


def test_checkout_and_has_commit_on_toy_repo(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "one")
    first = git("rev-parse", "HEAD")
    (tmp_path / "a.py").write_text("x = 2\n")
    git("commit", "-qam", "two")

    assert rm.has_commit(tmp_path, first)
    assert not rm.has_commit(tmp_path, "0" * 40)
    rm.checkout(tmp_path, first)
    assert rm.head_commit(tmp_path) == first
    assert (tmp_path / "a.py").read_text() == "x = 1\n"
