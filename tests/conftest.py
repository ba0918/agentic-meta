"""Shared test setup: make scripts/vendor.py importable and locate fixtures."""

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

FIXTURES = REPO_ROOT / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def copy_tree(tmp_path):
    """Copy a fixture tree into tmp_path so tests can mutate or regenerate it."""

    def _copy(relative: str) -> Path:
        source = FIXTURES / relative
        target = tmp_path / Path(relative).name
        shutil.copytree(source, target)
        return target

    return _copy
