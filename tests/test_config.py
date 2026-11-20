from pathlib import Path

from semnav_gp.helpers.config import Settings


def test_derived_paths_live_under_data_dir(tmp_path: Path) -> None:
    s = Settings(DATA_DIR=tmp_path, _env_file=None)
    assert s.repos_dir == tmp_path / "raw" / "repos"
    assert s.processed_dir == tmp_path / "processed"


def test_ensure_dirs_creates_layout(tmp_path: Path) -> None:
    s = Settings(DATA_DIR=tmp_path / "data", _env_file=None)
    s.ensure_dirs()
    for d in (s.raw_dir, s.repos_dir, s.interim_dir, s.processed_dir, s.logs_dir):
        assert d.is_dir()
