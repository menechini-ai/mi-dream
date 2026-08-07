from neo4j import AsyncGraphDatabase

from mi_dream.config import settings

_driver: AsyncGraphDatabase | None = None


def get_driver() -> AsyncGraphDatabase:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            notifications_disabled_classifications=["UNRECOGNIZED"],
        )
    return _driver
