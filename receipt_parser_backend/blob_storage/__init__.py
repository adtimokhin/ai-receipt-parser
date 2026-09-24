"""Blob storage overlay: async S3-compatible client for original document files.

Public surface:

* :func:`~receipt_parser_backend.blob_storage.client.get_session` - the
  process-wide :class:`~aioboto3.Session`, created by the app lifespan.
* :func:`~receipt_parser_backend.blob_storage.client.ensure_bucket` - idempotent
  bootstrap, run once at startup.
* :func:`~receipt_parser_backend.blob_storage.client.upload_bytes` /
  :func:`~receipt_parser_backend.blob_storage.client.download_bytes` /
  :func:`~receipt_parser_backend.blob_storage.client.delete_object` - thin
  helpers over the configured bucket.
"""

from receipt_parser_backend.blob_storage.client import (
    delete_object,
    download_bytes,
    ensure_bucket,
    get_session,
    upload_bytes,
)

__all__ = ["delete_object", "download_bytes", "ensure_bucket", "get_session", "upload_bytes"]
