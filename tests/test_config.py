import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.config import Settings


def test_settings_defaults():
    s = Settings(neo4j_uri="bolt://localhost:7687", tenant_id="test")
    assert s.tenant_id == "test"
    assert s.neo4j_uri.startswith("bolt://")


def test_settings_neo4j_database_default():
    s = Settings(neo4j_uri="bolt://localhost:7687", tenant_id="test")
    assert s.neo4j_database == "neo4j"


def test_compaction_settings_defaults():
    s = Settings(compact_threshold_chars=4000, compact_keep_recent=4)
    assert s.compact_threshold_chars == 4000
    assert s.compact_keep_recent == 4
    assert s.refl_interval_minutes == 10


def test_context_trigger_settings_defaults():
    s = Settings(learn_trace_threshold=5, daily_review_hour=7)
    assert s.learn_trace_threshold == 5
    assert s.daily_review_hour == 7


def test_llm_settings_defaults():
    s = Settings(llm_temperature=0.2, llm_max_tokens=2048)
    assert s.llm_temperature == 0.2
    assert s.llm_max_tokens == 2048
