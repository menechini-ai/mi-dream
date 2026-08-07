from unittest.mock import MagicMock, patch

from mi_dream.agents.toolbox import (
    EditFileTool,
    ExecTool,
    ListDirTool,
    ReadFileTool,
    WebFetchTool,
    WebSearchTool,
    build_chat_toolbox,
)


def test_web_search_formats_results_and_caps_count():
    def fake_search(query, count):
        assert query == "mi dream"
        assert count == 10
        return [
            {"title": f"t{i}", "url": f"https://ex{i}.com", "snippet": f"s{i}"} for i in range(15)
        ]

    tool = WebSearchTool(search_fn=fake_search)
    out = tool.run(query="mi dream", count=10)
    lines = out.splitlines()
    assert lines[0] == "1. t0"
    assert lines[1] == "   https://ex0.com"
    assert lines[2] == "   s0"
    numbers = [line for line in lines if line[:1].isdigit()]
    assert len(numbers) == 10
    assert "t9" in out
    assert "t10" not in out


def test_web_search_error_is_graceful():
    def broken_search(query, count):
        raise OSError("network down")

    tool = WebSearchTool(search_fn=broken_search)
    assert tool.run(query="q").startswith("Error:")


def test_web_fetch_strips_html_and_caps():
    def fake_fetch(url):
        assert url == "https://ex.com"
        return "<html><body><h1>Title</h1><p>Some <b>bold</b> text</p></body></html>"

    tool = WebFetchTool(fetch_fn=fake_fetch)
    out = tool.run(url="https://ex.com", max_chars=10)
    assert "Title" not in out
    assert "bold" not in out
    assert len(out) <= 10


def test_web_fetch_error_is_graceful():
    def broken_fetch(url):
        raise OSError("dns")

    tool = WebFetchTool(fetch_fn=broken_fetch)
    assert tool.run(url="https://ex.com").startswith("Error:")


def test_web_fetch_requires_http_scheme():
    tool = WebFetchTool(fetch_fn=lambda url: "x")
    assert tool.run(url="file:///etc/passwd").startswith("Error:")


def test_read_file_returns_content(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world")
    tool = ReadFileTool(workdir=str(tmp_path))
    assert tool.run(path="a.txt") == "hello world"


def test_read_file_missing_returns_error(tmp_path):
    tool = ReadFileTool(workdir=str(tmp_path))
    assert tool.run(path="nope.txt").startswith("Error:")


def test_read_file_blocks_escape(tmp_path, monkeypatch):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("top secret")
    tool = ReadFileTool(workdir=str(tmp_path))
    assert tool.run(path="../secret.txt").startswith("Error:")


def test_list_dir_lists_entries(tmp_path):
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a").mkdir()
    tool = ListDirTool(workdir=str(tmp_path))
    out = tool.run(path=".")
    assert "a/" in out
    assert "b.txt" in out


def test_edit_file_replaces_content(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("foo bar baz")
    tool = EditFileTool(workdir=str(tmp_path))
    result = tool.run(path="x.py", old="bar", new="BING")
    assert "updated" in result
    assert "x.py" in result
    assert f.read_text() == "foo BING baz"


def test_edit_file_old_not_found_returns_error(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("foo")
    tool = EditFileTool(workdir=str(tmp_path))
    assert tool.run(path="x.py", old="nope", new="y").startswith("Error:")
    assert f.read_text() == "foo"


def test_edit_file_blocks_escape(tmp_path):
    outside = tmp_path.parent / "s.txt"
    outside.write_text("keep")
    tool = EditFileTool(workdir=str(tmp_path))
    assert tool.run(path="../s.txt", old="keep", new="evil").startswith("Error:")
    assert outside.read_text() == "keep"


def test_exec_disabled_returns_error():
    tool = ExecTool(enabled=False)
    assert "disabled" in tool.run(command="echo hi")


def test_exec_enabled_runs_command(tmp_path):
    with patch("mi_dream.agents.toolbox.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="hi\n", stderr="")
        tool = ExecTool(enabled=True, workdir=str(tmp_path))
        out = tool.run(command="echo hi", timeout=5)
    assert out == "hi"
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)


def test_build_chat_toolbox_includes_exec_when_enabled(monkeypatch):
    from mi_dream.agents.toolbox import settings

    monkeypatch.setattr(settings, "enable_shell_tool", True)
    tb = build_chat_toolbox()
    assert "exec" in tb.names()


def test_build_chat_toolbox_excludes_exec_when_disabled(monkeypatch):
    from mi_dream.agents.toolbox import settings

    monkeypatch.setattr(settings, "enable_shell_tool", False)
    tb = build_chat_toolbox()
    assert "exec" not in tb.names()
    assert "web_search" in tb.names()
    assert "web_fetch" in tb.names()
    assert "read_file" in tb.names()
    assert "list_dir" in tb.names()
    assert "edit_file" in tb.names()
