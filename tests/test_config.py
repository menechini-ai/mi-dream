import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.config import Settings


def test_settings_defaults():
    s = Settings(neo4j_uri="bolt://localhost:7687", tenant_id="test")
    assert s.tenant_id == "test"
    assert s.neo4j_uri.startswith("bolt://")


def test_settings_reflection_cron_default():
    s = Settings(neo4j_uri="bolt://localhost:7687", tenant_id="test")
    assert s.reflection_cron == "0 */6 * * *"


def test_settings_neo4j_database_default():
    s = Settings(neo4j_uri="bolt://localhost:7687", tenant_id="test")
    assert s.neo4j_database == "neo4j"
