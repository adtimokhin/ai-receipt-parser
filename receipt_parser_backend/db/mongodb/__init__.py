"""MongoDB overlay: PyMongo async client (``AsyncMongoClient``), no ODM (D-008).

Public surface:

* :func:`~receipt_parser_backend.db.mongodb.client.get_client` - the process-wide
  :class:`~pymongo.AsyncMongoClient`, created by the app lifespan.
* :func:`~receipt_parser_backend.db.mongodb.client.get_database` - the configured
  database handle.

Model your documents as plain Pydantic v2 classes at the API boundary and
convert to and from ``dict`` for ``insert_one`` / ``find_one``; map the
``ObjectId`` ``_id`` to a string field. Keep an ``ensure_indexes`` routine and
call it from a startup hook if the service needs indexes.
"""

from receipt_parser_backend.db.mongodb.client import get_client, get_database

__all__ = ["get_client", "get_database"]
