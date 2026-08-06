import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))


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


def make_driver_mock(session):
    """Return a driver mock where driver.session(...) is an async CM -> session."""
    driver = AsyncMock()
    driver.session = MagicMock(return_value=mock_async_cm(session))
    return driver
