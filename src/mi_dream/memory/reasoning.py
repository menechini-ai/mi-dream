import hashlib
import json


def _canonical_metadata(metadata: str | dict) -> str:
    """Serialize metadata to a stable canonical JSON string.

    Dicts are normalized (sorted keys, compact separators) so the fingerprint
    is independent of insertion order and matches whatever the Curator reads
    back from Neo4j (which always yields a string).
    """
    if isinstance(metadata, dict):
        return json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    return metadata


def trace_fingerprint(content: str, outcome: str, metadata: str | dict) -> str:
    """Deterministic fingerprint of a ReasoningTrace payload (INV-001).

    Stored at creation time as ``content_hash``; the Curator recomputes it to
    detect any later mutation of the trace's content/outcome/metadata.

    ``metadata`` may be a dict or an already-serialized JSON string — both are
    canonicalized to the same form before hashing, so write and read paths
    always agree.
    """
    canonical = json.dumps(
        [content, outcome, _canonical_metadata(metadata)],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
