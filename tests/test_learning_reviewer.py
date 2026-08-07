import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from conftest import FakeAsyncIter, make_driver_mock


class FakeRecord:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]


def _count_session():
    session = AsyncMock()

    async def mock_run(query, **kwargs):
        result = AsyncMock()
        result.single.return_value = FakeRecord({"count": 0})
        return result

    session.run.side_effect = mock_run
    return session


@pytest.mark.asyncio
async def test_review_collects_stats_and_persists():
    from mi_dream.learning.reviewer import DailyReviewer

    session = _count_session()
    reviewer = DailyReviewer(session, use_llm=False)
    with patch("mi_dream.learning.reviewer.Curator") as MockCurator:
        MockCurator.return_value.run_integrity_checks = AsyncMock(return_value=[])
        report = await reviewer.review("default")

    assert report["date"]
    assert report["tenant_id"] == "default"
    assert report["stats"]["traces_today"] == 0
    assert report["health"]["ok"] is True
    assert report["summary"] == ""
    queries = [c.args[0] for c in session.run.call_args_list]
    assert any("DailyReview" in q for q in queries)


@pytest.mark.asyncio
async def test_review_reports_integrity_violations():
    from mi_dream.learning.reviewer import DailyReviewer

    session = _count_session()
    reviewer = DailyReviewer(session, use_llm=False)
    violation = {"trace_id": "t1", "reason": "mutated (INV-001)"}
    with patch("mi_dream.learning.reviewer.Curator") as MockCurator:
        MockCurator.return_value.run_integrity_checks = AsyncMock(return_value=[violation])
        report = await reviewer.review("default")

    assert report["integrity_violations"] == [violation]
    assert report["health"]["ok"] is False


@pytest.mark.asyncio
async def test_review_llm_summary_on():
    from mi_dream.learning.reviewer import DailyReviewer

    session = _count_session()
    reviewer = DailyReviewer(session, use_llm=True)
    with patch("mi_dream.learning.reviewer.Curator") as MockCurator, patch(
        "mi_dream.learning.reviewer.ask_llm_full",
        return_value=MagicMock(content="Dia produtivo, pipeline saudável."),
    ) as mock_llm:
        MockCurator.return_value.run_integrity_checks = AsyncMock(return_value=[])
        report = await reviewer.review("default")

    assert "Dia produtivo" in report["summary"]
    mock_llm.assert_called_once()


@pytest.mark.asyncio
async def test_run_daily_review_uses_driver():
    from mi_dream.learning.reviewer import run_daily_review

    session = _count_session()
    driver = make_driver_mock(session)
    with patch("mi_dream.learning.reviewer.get_driver", return_value=driver), patch(
        "mi_dream.learning.reviewer.ask_llm_full",
        return_value=MagicMock(content="ok"),
    ):
        report = await run_daily_review("default")

    assert report["date"]


@pytest.mark.asyncio
async def test_reviewed_dates_parses_records():
    from mi_dream.learning.reviewer import reviewed_dates

    session = AsyncMock()
    session.run.return_value = FakeAsyncIter(
        [FakeRecord({"date": "2026-08-06"}), FakeRecord({"date": "2026-08-05"})]
    )
    driver = make_driver_mock(session)
    with patch("mi_dream.learning.reviewer.get_driver", return_value=driver):
        dates = await reviewed_dates("default")

    assert dates == {"2026-08-06", "2026-08-05"}


def test_daily_review_due():
    from mi_dream.learning.reviewer import daily_review_due

    assert daily_review_due(7, {"2026-08-07"}, "2026-08-07") is False
    assert daily_review_due(8, set(), "2026-08-07") is True
    assert daily_review_due(9, set(), "2026-08-07") is True
    assert daily_review_due(9, {"2026-08-07"}, "2026-08-07") is False
