"""Concrete agent tools: web search/fetch, filesystem read/list/edit, shell exec.

Default web clients use only the standard library (urllib) so no new
dependencies are required; the callables can be injected for testing and for
alternative providers. Filesystem tools are scoped to ``tool_workdir`` and
reject paths that escape it. ``exec`` is opt-in via ``ENABLE_SHELL_TOOL=true``.
"""

import subprocess
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from mi_dream.agents.loop import Tool, Toolbox
from mi_dream.config import settings

WEB_SEARCH_TIMEOUT = 15
WEB_FETCH_TIMEOUT = 20
READ_FILE_MAX_CHARS = 20000
EDIT_FILE_MAX = 200000
EXEC_OUTPUT_MAX_CHARS = 5000
LIST_DIR_MAX_ENTRIES = 200
MAX_SEARCH_COUNT = 10
DEFAULT_SEARCH_URL = "https://html.duckduckgo.com/html/"


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self, max_chars: int) -> str:
        joined = " ".join(" ".join(self._parts).split())
        return joined[:max_chars]


def _extract_text(html: str, max_chars: int = 8000) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - never crash on malformed markup
        pass
    return parser.text(max_chars)


def _http_get(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "mi-dream/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def default_search(query: str, count: int) -> list[dict]:
    """DuckDuckGo HTML search via stdlib. Returns top ``count`` results."""
    count = max(1, min(count, MAX_SEARCH_COUNT))
    url = f"{DEFAULT_SEARCH_URL}?q={urllib.parse.quote(query)}"
    html = _http_get(url, WEB_SEARCH_TIMEOUT)
    results: list[dict] = []
    # html.duckduckgo.com marks results with result__a / result__snippet links.
    marker = 'class="result__a"'
    cursor = 0
    while len(results) < count:
        start = html.find(marker, cursor)
        if start == -1:
            break
        link_open = html.find("<a", max(0, start - 400))
        if link_open == -1:
            break
        href_start = html.find('href="', link_open) + len('href="')
        href_end = html.find('"', href_start)
        href = html[href_start:href_end]
        title_start = html.find(">", href_end) + 1
        title_end = html.find("</a>", title_start)
        title = html[title_start:title_end]
        snippet_start = html.find("result__snippet", title_end)
        snippet = ""
        if snippet_start != -1:
            s_tag = html.find(">", snippet_start) + 1
            s_end = html.find("</", s_tag)
            if s_end != -1:
                snippet = html[s_tag:s_end]
        results.append(
            {
                "title": title.strip(),
                "url": href,
                "snippet": snippet.strip(),
            }
        )
        cursor = max(start + 1, title_end + 1)
    return results


def default_fetch(url: str) -> str:
    """Fetch a URL and return readable text (stdlib only)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http/https URLs are supported")
    html = _http_get(url, WEB_FETCH_TIMEOUT)
    return _extract_text(html)


class WebSearchTool(Tool):
    def __init__(self, search_fn=None):
        super().__init__(
            name="web_search",
            description=(
                "Search the web and return a numbered list of titles, URLs and "
                "snippets. Use it for current facts, docs and anything not in "
                "your training data."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "count": {
                        "type": "integer",
                        "description": "Number of results (1-10)",
                    },
                },
                "required": ["query"],
            },
        )
        self._search = search_fn or default_search

    def run(self, query: str, count: int = 5) -> str:
        try:
            count = max(1, min(int(count), MAX_SEARCH_COUNT))
            results = self._search(query, count)
        except Exception as exc:  # noqa: BLE001 - surface search failures gracefully
            return f"Error: web search failed: {exc}"
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results[:count], start=1):
            lines.append(f"{i}. {r.get('title', '')}")
            lines.append(f"   {r.get('url', '')}")
            snippet = r.get("snippet") or ""
            if snippet:
                lines.append(f"   {snippet}")
        return "\n".join(lines)


class WebFetchTool(Tool):
    def __init__(self, fetch_fn=None):
        super().__init__(
            name="web_fetch",
            description=(
                "Fetch the text content of a URL (http/https only). Use it to "
                "read a page found via web_search."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to return",
                    },
                },
                "required": ["url"],
            },
        )
        self._fetch = fetch_fn or default_fetch

    def run(self, url: str, max_chars: int = 20000) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return f"Error: only http/https URLs are supported, got {parsed.scheme!r}"
        try:
            text = self._fetch(url)
        except Exception as exc:  # noqa: BLE001 - surface fetch failures gracefully
            return f"Error: web fetch failed: {exc}"
        return text[: max(1, int(max_chars))]


def _resolve(workdir: str, path: str) -> Path:
    base = Path(workdir or ".").resolve()
    target = (base / path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escapes tool workdir: {path!r}") from exc
    return target


class ReadFileTool(Tool):
    def __init__(self, workdir=None):
        super().__init__(
            name="read_file",
            description="Read the contents of a file inside the project workdir.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path"}},
                "required": ["path"],
            },
        )
        self._workdir = workdir or settings.tool_workdir

    def run(self, path: str) -> str:
        try:
            target = _resolve(self._workdir, path)
            content = target.read_text(encoding="utf-8", errors="replace")
        except (ValueError, OSError) as exc:
            return f"Error: {exc}"
        if len(content) > READ_FILE_MAX_CHARS:
            content = content[:READ_FILE_MAX_CHARS] + "\n...[truncated]"
        return content


class ListDirTool(Tool):
    def __init__(self, workdir=None):
        super().__init__(
            name="list_dir",
            description="List the entries of a directory inside the project workdir.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '.')"}
                },
            },
        )
        self._workdir = workdir or settings.tool_workdir

    def run(self, path: str = ".") -> str:
        try:
            target = _resolve(self._workdir, path)
            entries = []
            for entry in sorted(target.iterdir()):
                entries.append(entry.name + ("/" if entry.is_dir() else ""))
                if len(entries) >= LIST_DIR_MAX_ENTRIES:
                    entries.append("...[truncated]")
                    break
        except (ValueError, OSError) as exc:
            return f"Error: {exc}"
        return "\n".join(entries) if entries else "(empty directory)"


class EditFileTool(Tool):
    def __init__(self, workdir=None):
        super().__init__(
            name="edit_file",
            description=(
                "Replace the first occurrence of ``old`` with ``new`` in a file "
                "inside the project workdir. Use read_file first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old": {"type": "string", "description": "Text to find"},
                    "new": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old", "new"],
            },
        )
        self._workdir = workdir or settings.tool_workdir

    def run(self, path: str, old: str, new: str) -> str:
        try:
            target = _resolve(self._workdir, path)
            if target.stat().st_size > EDIT_FILE_MAX:
                raise ValueError("file too large to edit")
            content = target.read_text(encoding="utf-8")
            if old not in content:
                raise ValueError(f"old text not found in {path!r}")
            content = content.replace(old, new, 1)
            target.write_text(content, encoding="utf-8")
        except (ValueError, OSError) as exc:
            return f"Error: {exc}"
        return f"updated {path!r}"


class ExecTool(Tool):
    def __init__(self, enabled=False, workdir=None):
        super().__init__(
            name="exec",
            description=(
                "Run a shell command inside the project workdir and return its "
                "output. Only available when explicitly enabled."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command"},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                    },
                },
                "required": ["command"],
            },
        )
        self._enabled = enabled
        self._workdir = workdir or settings.tool_workdir

    def run(self, command: str, timeout: int = 30) -> str:
        if not self._enabled:
            return "Error: exec tool is disabled; set ENABLE_SHELL_TOOL=true to enable it"
        try:
            proc = subprocess.run(  # noqa: S603 - explicitly enabled by the user
                command,
                shell=True,  # noqa: S604 - the model already has edit_file; exec is opt-in
                cwd=self._workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"Error: exec failed: {exc}"
        output = (proc.stdout or "").strip() + (proc.stderr or "").strip()
        if not output:
            return f"(exit code {proc.returncode}, no output)"
        return output[:EXEC_OUTPUT_MAX_CHARS]


def build_chat_toolbox(workdir: str | None = None) -> Toolbox:
    """Assemble the tools exposed to the REPL chat agent."""
    toolbox = Toolbox(
        [
            WebSearchTool(),
            WebFetchTool(),
            ReadFileTool(workdir),
            ListDirTool(workdir),
            EditFileTool(workdir),
        ]
    )
    if settings.enable_shell_tool:
        toolbox.add(ExecTool(enabled=True, workdir=workdir))
    return toolbox
