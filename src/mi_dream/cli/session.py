import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_SESSION_DIR = Path.home() / ".mi-dream" / "sessions"


def new_session_id() -> str:
    """Random, human-readable session ID (resumable via /session <id>)."""
    return f"{datetime.now():%m%d%H%M}-{uuid4().hex[:4]}"


@dataclass
class Session:
    name: str
    context: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class SessionManager:
    def __init__(self, session_dir: Path = DEFAULT_SESSION_DIR):
        self._session_dir = session_dir
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._current: Session | None = None

    def create(self, name: str = "default") -> Session:
        self._current = Session(name=name)
        return self._current

    def resume(self, name: str) -> Session:
        path = self._session_dir / f"{name}.json"
        if path.exists():
            data = json.loads(path.read_text())
            self._current = Session(**data)
        else:
            self._current = Session(name=name)
        return self._current

    def current(self) -> Session:
        if not self._current:
            return self.create()
        return self._current

    def add_message(self, role: str, content: str) -> None:
        session = self.current()
        session.context.append({"role": role, "content": content, "ts": datetime.now().isoformat()})
        session.updated_at = datetime.now().isoformat()

    def clear_context(self) -> None:
        session = self.current()
        session.context = []
        session.updated_at = datetime.now().isoformat()

    def save(self) -> None:
        if not self._current:
            return
        path = self._session_dir / f"{self._current.name}.json"
        path.write_text(json.dumps(self._current.__dict__, indent=2))

    def list_sessions(self) -> list[str]:
        return [f.stem for f in self._session_dir.glob("*.json")]
