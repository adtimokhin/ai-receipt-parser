"""A minimal in-memory Mongo stand-in for repository-level tests.

Supports just what ``sessions/repository.py`` uses: single-field equality
filters, ``sort`` on ``find_one``, upserting ``replace_one``, ``insert_one``
with a generated ``ObjectId``, and ``delete_one``. Not a general Mongo fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bson import ObjectId

Document = dict[str, Any]


@dataclass
class _InsertResult:
    inserted_id: ObjectId


class FakeMongoCollection:
    def __init__(self) -> None:
        self._docs: list[Document] = []

    async def find_one(
        self, filter: Document, sort: list[tuple[str, int]] | None = None
    ) -> Document | None:
        matches = [doc for doc in self._docs if _matches(doc, filter)]
        if sort:
            for field, direction in reversed(sort):
                matches.sort(key=lambda d: d[field], reverse=direction < 0)
        return dict(matches[0]) if matches else None

    async def replace_one(
        self, filter: Document, replacement: Document, upsert: bool = False
    ) -> None:
        for index, doc in enumerate(self._docs):
            if _matches(doc, filter):
                self._docs[index] = dict(replacement)
                return
        if upsert:
            self._docs.append(dict(replacement))

    async def insert_one(self, document: Document) -> _InsertResult:
        doc = dict(document)
        doc["_id"] = ObjectId()
        self._docs.append(doc)
        return _InsertResult(inserted_id=doc["_id"])

    async def delete_one(self, filter: Document) -> None:
        for index, doc in enumerate(self._docs):
            if _matches(doc, filter):
                del self._docs[index]
                return


def _matches(doc: Document, filter: Document) -> bool:
    return all(doc.get(key) == value for key, value in filter.items())


class FakeMongoDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, FakeMongoCollection] = {}

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return self._collections.setdefault(name, FakeMongoCollection())
