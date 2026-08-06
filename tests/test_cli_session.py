import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.session import SessionManager


def test_create_session():
    mgr = SessionManager(session_dir=Path(tempfile.mkdtemp()))
    s = mgr.create("test")
    assert s.name == "test"
    assert len(s.context) == 0


def test_add_message():
    mgr = SessionManager(session_dir=Path(tempfile.mkdtemp()))
    mgr.create("test")
    mgr.add_message("user", "hello")
    mgr.add_message("assistant", "hi")
    ctx = mgr.current().context
    assert len(ctx) == 2
    assert ctx[0]["role"] == "user"
    assert ctx[0]["content"] == "hello"


def test_clear_context():
    mgr = SessionManager(session_dir=Path(tempfile.mkdtemp()))
    mgr.create("test")
    mgr.add_message("user", "hello")
    mgr.clear_context()
    assert len(mgr.current().context) == 0


def test_save_and_resume():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)
    mgr.create("persist")
    mgr.add_message("user", "msg1")
    mgr.save()

    mgr2 = SessionManager(session_dir=tmpdir)
    resumed = mgr2.resume("persist")
    assert resumed.name == "persist"
    assert len(resumed.context) == 1
    assert resumed.context[0]["content"] == "msg1"


def test_resume_nonexistent_creates_new():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)
    s = mgr.resume("nonexistent")
    assert s.name == "nonexistent"
    assert len(s.context) == 0


def test_list_sessions():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)
    mgr.create("s1")
    mgr.save()
    mgr.create("s2")
    mgr.save()
    sessions = mgr.list_sessions()
    assert "s1" in sessions
    assert "s2" in sessions
