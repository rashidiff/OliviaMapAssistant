from __future__ import annotations

import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
]


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [PROJECT_ROOT / line for line in result.stdout.splitlines()]


def test_no_real_env_files_are_tracked() -> None:
    tracked_env_files = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _tracked_files()
        if path.name.startswith(".env") and path.name != ".env.example"
    ]

    assert tracked_env_files == []


def test_tracked_files_do_not_contain_api_secrets() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []
