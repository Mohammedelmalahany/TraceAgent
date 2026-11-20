"""Schema for one SWE-bench Lite row."""

import json

from pydantic import BaseModel, field_validator


class Instance(BaseModel):
    instance_id: str
    repo: str  # e.g. "django/django"
    base_commit: str
    problem_statement: str
    patch: str  # gold fix — used ONLY for gold labels (P1)
    test_patch: str = ""
    hints_text: str = ""  # never used for retrieval (data-leakage rule)
    created_at: str = ""
    version: str = ""
    environment_setup_commit: str = ""
    FAIL_TO_PASS: list[str] = []
    PASS_TO_PASS: list[str] = []

    @field_validator("FAIL_TO_PASS", "PASS_TO_PASS", mode="before")
    @classmethod
    def _parse_json_list(cls, v):
        # In the HF dataset these fields are JSON strings like '["test_a", "test_b"]'.
        if isinstance(v, str):
            return json.loads(v) if v.strip() else []
        return v

    @property
    def repo_dir_name(self) -> str:
        """Folder name for the cloned repo: 'django/django' -> 'django__django'."""
        return self.repo.replace("/", "__")
