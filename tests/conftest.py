import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _clean_fsort_env(monkeypatch):
    """Evita filtraciones de FSORT_* entre tests."""
    for var in ("FSORT_YES", "FSORT_TRASH_DIR", "FSORT_AI_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def no_tty(monkeypatch):
    """Finge stdin sin TTY: las confirmaciones destructivas devuelven False."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
