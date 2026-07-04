"""Shared Neo4j driver for application Cypher queries."""

from __future__ import annotations

from neo4j import Driver, GraphDatabase

from app.config import settings

_driver: Driver | None = None


def get_neo4j_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


def close_neo4j_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def verify_neo4j_connection() -> str:
    with get_neo4j_driver().session() as session:
        row = session.run("RETURN 'Neo4j работает!' AS message").single()
        return row["message"] if row else "OK"
