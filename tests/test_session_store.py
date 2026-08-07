"""Tests for mi_dream.observability.session_store."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mi_dream.observability.session_store import LocalFileSessionStore, Session


def test_create_session(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    sess = store.create(name="test")
    assert sess.name == "test"
    assert sess.context == []


def test_add_message(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    store.create("s1")
    store.add_message("user", "hello")
    store.add_message("assistant", "hi")
    sess = store.current()
    assert len(sess.context) == 2
    assert sess.context[0]["role"] == "user"
    assert sess.context[0]["content"] == "hello"


def test_save_and_resume(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    store.create("s1")
    store.add_message("user", "hello")
    store.save()

    path = tmp_path / "s1.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["name"] == "s1"
    assert len(data["context"]) == 1


def test_resume_nonexistent_creates_new(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    sess = store.resume("nonexistent")
    assert sess.name == "nonexistent"
    assert sess.context == []


def test_resume_existing(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    store.create("s1")
    store.add_message("user", "hello")
    store.save()

    store2 = LocalFileSessionStore(session_dir=tmp_path)
    sess = store2.resume("s1")
    assert len(sess.context) == 1
    assert sess.context[0]["content"] == "hello"


def test_clear_context(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    store.create("s1")
    store.add_message("user", "hello")
    store.clear_context()
    assert store.current().context == []


def test_list_sessions(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    store.create("s1")
    store.save()
    store.create("s2")
    store.save()
    sessions = store.list_sessions()
    assert "s1" in sessions
    assert "s2" in sessions


def test_current_creates_if_none(tmp_path):
    store = LocalFileSessionStore(session_dir=tmp_path)
    sess = store.current()
    assert sess.name == "default"
