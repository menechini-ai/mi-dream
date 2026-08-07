import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CRON_FILE = Path.cwd() / ".midream" / "cron.json"
SCRIPTS_DIR = Path.cwd() / ".midream" / "scripts"


@dataclass
class CronJob:
    id: str
    interval: str
    prompt: str
    script: str | None = None
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run: str | None = None


class CronManager:
    def __init__(self, path: Path | None = None):
        self._path = path or CRON_FILE
        self._jobs: list[CronJob] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            return
        try:
            data = json.loads(self._path.read_text())
            self._jobs = [CronJob(**j) for j in data]
        except Exception:
            self._jobs = []

    def _save(self) -> None:
        self._path.write_text(json.dumps([j.__dict__ for j in self._jobs], indent=2))

    def add(self, interval: str, prompt: str, script: str | None = None) -> CronJob:
        job = CronJob(
            id=__import__("uuid").uuid4().hex[:8],
            interval=interval,
            prompt=prompt,
            script=script,
        )
        self._jobs.append(job)
        self._save()
        return job

    def list_jobs(self) -> list[CronJob]:
        return [j for j in self._jobs if j.active]

    def deactivate(self, job_id: str) -> bool:
        for j in self._jobs:
            if j.id == job_id:
                j.active = False
                self._save()
                return True
        return False

    def due_jobs(self) -> list[CronJob]:
        now = datetime.now()
        due = []
        for j in self._jobs:
            if not j.active:
                continue
            if j.last_run is None:
                due.append(j)
                continue
            minutes = self._interval_to_minutes(j.interval)
            last = datetime.fromisoformat(j.last_run)
            if (now - last).total_seconds() >= minutes * 60:
                due.append(j)
        return due

    def mark_run(self, job_id: str) -> None:
        for j in self._jobs:
            if j.id == job_id:
                j.last_run = datetime.now().isoformat()
                self._save()
                break

    def parse_chat(self, message: str) -> tuple[str, str, str | None] | None:
        """Parse '/cron add 1h "busque sobre SRE"' or '/cron add 5m --no-agent
        --script check.sh'."""
        m = re.match(r"/cron\s+add\s+(\S+)\s+--no-agent\s+--script\s+(\S+)", message)
        if m:
            return m.group(1), "", m.group(2)
        m = re.match(r"/cron\s+add\s+(\S+)\s+[\"'](.+)[\"']\s*$", message, re.DOTALL)
        if m:
            return m.group(1), m.group(2), None
        return None

    def run_script(self, script_name: str) -> str:
        """Execute a script from .midream/scripts/. Returns output or error string."""
        script_path = SCRIPTS_DIR / script_name
        if not script_path.is_file():
            return f"Script not found: {script_path}"
        try:
            if script_path.suffix in (".sh", ".bash"):
                result = subprocess.run(
                    ["bash", str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            else:
                result = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            output = result.stdout.strip()
            if not output:
                return ""
            return output
        except subprocess.TimeoutExpired:
            return f"Script timeout: {script_name}"
        except Exception as e:
            return f"Script error: {e}"

    @staticmethod
    def _interval_to_minutes(interval: str) -> int:
        m = re.match(r"(\d+)(m|min|h|hour)", interval, re.IGNORECASE)
        if not m:
            return 60
        value = int(m.group(1))
        unit = m.group(2).lower()
        return value * 60 if unit in ("h", "hour") else value
