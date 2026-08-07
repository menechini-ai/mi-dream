"""Tests for mi_dream.observability."""

import json
import logging
from unittest.mock import patch

import pytest

from mi_dream.observability import Metrics, WORKER_ID, get_logger, get_metrics


def test_get_metrics_returns_singleton():
    assert get_metrics() is get_metrics()


def test_metrics_increment_default():
    m = Metrics()
    m.increment("learning_cycle_failures")
    assert m.learning_cycle_failures == 1


def test_metrics_increment_custom_amount():
    m = Metrics()
    m.increment("lessons_created", 5)
    assert m.lessons_created == 5


def test_metrics_to_dict():
    m = Metrics()
    m.increment("strategies_promoted", 3)
    d = m.to_dict()
    assert d["strategies_promoted"] == 3
    assert d["learning_cycle_failures"] == 0


def test_worker_id_default():
    assert WORKER_ID.startswith("worker-")


def test_worker_id_from_env():
    with patch.dict("os.environ", {"MI_DREAM_WORKER_ID": "custom-worker"}):
        from mi_dream.observability import WORKER_ID as wid
        assert wid == "custom-worker"


def test_get_logger_returns_named_logger():
    logger = get_logger("scheduler")
    assert logger.name == "mi_dream.scheduler"


def test_get_logger_no_duplicate_handlers():
    logger = get_logger("test_module")
    handler_count = len(logger.handlers)
    logger2 = get_logger("test_module")
    assert len(logger2.handlers) == handler_count


def test_get_logger_emits_json(caplog):
    logger = get_logger("test_emit")
    with caplog.at_level(logging.INFO, logger="mi_dream.test_emit"):
        logger.info("hello world")
    assert len(caplog.records) == 1
    # Should be parseable as JSON
    parsed = json.loads(caplog.records[0].message)
    assert parsed["msg"] == "hello world"
    assert "level" in parsed
    assert "ts" in parsed
