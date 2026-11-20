"""Project settings, read from environment variables / the `.env` file.

Usage:
    from semnav_gp.helpers.config import get_settings
    settings = get_settings()
    print(settings.repos_dir)
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Root for all data. Must be outside OneDrive / synced folders.
    DATA_DIR: Path = Path("D:/semnav-data")

    DATASET_NAME: str = "princeton-nlp/SWE-bench_Lite"
    DATASET_SPLIT: str = "test"
    LOCAL_DATASET_PATH: Path | None = None

    MAX_FILE_SIZE_KB: int = 1024
    LOG_LEVEL: str = "INFO"

    # ---- Derived paths (all under DATA_DIR) ----
    @property
    def raw_dir(self) -> Path:
        return self.DATA_DIR / "raw"

    @property
    def repos_dir(self) -> Path:
        return self.raw_dir / "repos"

    @property
    def interim_dir(self) -> Path:
        return self.DATA_DIR / "interim"

    @property
    def processed_dir(self) -> Path:
        return self.DATA_DIR / "processed"

    @property
    def logs_dir(self) -> Path:
        return self.DATA_DIR / "logs"

    def ensure_dirs(self) -> None:
        """Create the data folder layout if it does not exist."""
        for d in (self.raw_dir, self.repos_dir, self.interim_dir, self.processed_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
