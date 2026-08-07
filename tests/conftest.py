import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
os.environ["SKILLS_DIR"] = str(_FIXTURES / "skills")
os.environ.setdefault("LLM_API_KEY", "test-key-not-used")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:9")


@pytest.fixture(autouse=True)
def _reset_driver_singleton():
    yield
    import mi_dream.memory.bootstrap as bootstrap
    import mi_dream.memory.connection as connection

    connection._driver = None
    bootstrap._bootstrapped = False


def mock_async_cm(cm_result):
    """Return a sync object usable with `async with` whose body is cm_result."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=cm_result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class FakeAsyncIter:
    """Async iterator over a fixed list — stand-in for a Neo4j session.run() result."""

    def __init__(self, items):
        self._items = items
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._i]
        self._i += 1
        return item


def make_driver_mock(session):
    """Return a driver mock where driver.session(...) is an async CM -> session."""
    driver = AsyncMock()
    driver.session = MagicMock(return_value=mock_async_cm(session))
    return driver
