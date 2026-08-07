import functools
import re
from pathlib import Path

import yaml

from mi_dream.config import settings


def _load_yaml_files(directory: str) -> list[dict]:
    path = Path(directory)
    if not path.is_dir():
        return []
    items = []
    for f in sorted(path.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text())
            if isinstance(data, dict):
                data.setdefault("name", f.stem)
                data.setdefault("description", "")
                items.append(data)
        except Exception:
            pass
    return items


def _load_skill_dirs(directory: str) -> list[dict]:
    path = Path(directory)
    if not path.is_dir():
        return []
    items = []
    for skill_dir in sorted(path.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text()
            meta, body = _parse_frontmatter(text)
            item = {
                "name": meta.get("name", skill_dir.name),
                "description": meta.get("description", ""),
                "prompt": body,
            }
            items.append(item)
        except Exception:
            pass
    return items


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if match:
        meta = yaml.safe_load(match.group(1)) or {}
        body = match.group(2).strip()
        return meta, body
    return {}, text.strip()


@functools.lru_cache(maxsize=2)
def load_skills() -> list[dict]:
    return _load_skill_dirs(settings.skills_dir)


@functools.lru_cache(maxsize=2)
def load_agents() -> list[dict]:
    return _load_yaml_files(settings.agents_dir)
