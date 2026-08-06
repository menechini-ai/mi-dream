import hashlib
import json


def trace_fingerprint(content: str, outcome: str, metadata_json: str) -> str:
    """Deterministic fingerprint of a ReasoningTrace payload (INV-001).

    Stored at creation time as ``content_hash``; the Curator recomputes it to
    detect any later mutation of the trace's content/outcome/metadata.
    """
    canonical = json.dumps(
        [content, outcome, metadata_json],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
