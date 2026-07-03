#!/usr/bin/env python3
"""Инициализация схемы динамического словаря DictEntity в Neo4j."""

from app.dictionary.store import EntityDictionaryStore


def main() -> None:
    store = EntityDictionaryStore()
    try:
        store.ensure_schema()
        count = store.count()
        print(f"DictEntity schema ready. Existing entries: {count}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
