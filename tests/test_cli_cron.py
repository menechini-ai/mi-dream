import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.cron import CronManager


def _fresh_manager(tmp_path: Path) -> CronManager:
    return CronManager(path=tmp_path / "cron.json")


def test_add_job(tmp_path):
    mgr = _fresh_manager(tmp_path)
    job = mgr.add("1h", "busque sobre SRE")
    assert job.id
    assert job.interval == "1h"
    assert job.prompt == "busque sobre SRE"
    assert job.script is None
    assert job.active


def test_add_job_with_script(tmp_path):
    mgr = _fresh_manager(tmp_path)
    job = mgr.add("5m", "", script="check.sh")
    assert job.script == "check.sh"
    assert job.prompt == ""


def test_list_active_jobs(tmp_path):
    mgr = _fresh_manager(tmp_path)
    mgr.add("1h", "topic A")
    mgr.add("30m", "topic B")
    mgr.add("2h", "topic C")
    mgr.deactivate(mgr.list_jobs()[0].id)
    jobs = mgr.list_jobs()
    assert len(jobs) == 2


def test_due_jobs_empty(tmp_path):
    mgr = _fresh_manager(tmp_path)
    assert mgr.due_jobs() == []


def test_due_jobs_new_job_is_due(tmp_path):
    mgr = _fresh_manager(tmp_path)
    mgr.add("1h", "learn SRE")
    jobs = mgr.due_jobs()
    assert len(jobs) == 1
    assert jobs[0].id


def test_due_jobs_after_interval(tmp_path):
    mgr = _fresh_manager(tmp_path)
    job = mgr.add("1h", "learn SRE")
    job.last_run = (datetime.now() - timedelta(hours=2)).isoformat()
    jobs = mgr.due_jobs()
    assert len(jobs) == 1


def test_due_jobs_not_yet_due(tmp_path):
    mgr = _fresh_manager(tmp_path)
    job = mgr.add("1h", "learn SRE")
    job.last_run = datetime.now().isoformat()
    jobs = mgr.due_jobs()
    assert jobs == []


def test_deactivate_job(tmp_path):
    mgr = _fresh_manager(tmp_path)
    job = mgr.add("1h", "learn SRE")
    assert mgr.deactivate(job.id) is True
    assert mgr.deactivate("nonexistent") is False
    assert all(not j.active for j in mgr.list_jobs())


def test_mark_run(tmp_path):
    mgr = _fresh_manager(tmp_path)
    job = mgr.add("1h", "learn SRE")
    assert job.last_run is None
    mgr.mark_run(job.id)
    assert job.last_run is not None


def test_parse_chat_agent_mode(tmp_path):
    mgr = _fresh_manager(tmp_path)
    result = mgr.parse_chat('/cron add 1h "busque sobre SRE"')
    assert result is not None
    interval, prompt, script = result
    assert interval == "1h"
    assert prompt == "busque sobre SRE"
    assert script is None


def test_parse_chat_single_quotes(tmp_path):
    mgr = _fresh_manager(tmp_path)
    result = mgr.parse_chat("/cron add 30m 'learn kubernetes'")
    assert result is not None
    assert result[0] == "30m"
    assert result[1] == "learn kubernetes"
    assert result[2] is None


def test_parse_chat_script_mode(tmp_path):
    mgr = _fresh_manager(tmp_path)
    result = mgr.parse_chat('/cron add 5m --no-agent --script check.sh')
    assert result is not None
    interval, prompt, script = result
    assert interval == "5m"
    assert prompt == ""
    assert script == "check.sh"


def test_parse_chat_no_match(tmp_path):
    mgr = _fresh_manager(tmp_path)
    assert mgr.parse_chat("hello world") is None


def test_interval_to_minutes():
    assert CronManager._interval_to_minutes("1h") == 60
    assert CronManager._interval_to_minutes("30m") == 30
    assert CronManager._interval_to_minutes("90min") == 90
    assert CronManager._interval_to_minutes("unknown") == 60


def test_run_script_not_found(tmp_path):
    mgr = _fresh_manager(tmp_path)
    result = mgr.run_script("nonexistent.sh")
    assert "not found" in result


def test_run_script_success(tmp_path):
    mgr = _fresh_manager(tmp_path)
    scripts_dir = Path.cwd() / ".midream" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    test_script = scripts_dir / "test_ok.sh"
    test_script.write_text("#!/bin/bash\necho 'hello from script'\n")
    test_script.chmod(0o755)
    try:
        result = mgr.run_script("test_ok.sh")
        assert result == "hello from script"
    finally:
        test_script.unlink(missing_ok=True)
