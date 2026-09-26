"""Private object storage with tenant-prefixed keys and short-lived URLs.

Every key starts with ``tenants/<tenant_id>/`` (ADR 0001, spec section 11), so an
object can never be addressed outside its tenant by construction. Buckets stay
private; the only browser access is a presigned GET that expires in minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol
from uuid import UUID


def source_prefix(tenant_id: UUID, source_id: UUID) -> str:
    return f"tenants/{tenant_id}/sources/{source_id}"


def original_key(tenant_id: UUID, source_id: UUID, extension: str) -> str:
    ext = extension.lower().lstrip(".")
    if not ext.isalnum() or len(ext) > 8:
        raise ValueError("invalid file extension")
    return f"{source_prefix(tenant_id, source_id)}/original.{ext}"


def page_image_key(tenant_id: UUID, source_id: UUID, page_no: int) -> str:
    return f"{source_prefix(tenant_id, source_id)}/pages/{page_no:05d}.png"


def figure_image_key(tenant_id: UUID, source_id: UUID, page_no: int, figure_no: int) -> str:
    return f"{source_prefix(tenant_id, source_id)}/figures/{page_no:05d}-{figure_no:03d}.png"


def require_tenant_key(tenant_id: UUID, key: str) -> None:
    """Refuse any key that is not inside the caller's tenant prefix."""
    if not key.startswith(f"tenants/{tenant_id}/") or ".." in key:
        raise PermissionError("object key is outside the tenant prefix")


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def put_file(self, key: str, fileobj: BinaryIO, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def signed_get_url(self, key: str, seconds: int) -> str: ...


@dataclass(slots=True)
class S3ObjectStore:
    """boto3-backed store for MinIO / RustFS / S3."""

    endpoint: str
    bucket: str
    access_key: str
    secret_key: str
    region: str = "us-east-1"
    public_endpoint: str | None = None

    def _client(self, endpoint: str | None = None) -> Any:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=endpoint or self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client().put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def put_file(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        self._client().upload_fileobj(
            fileobj, self.bucket, key, ExtraArgs={"ContentType": content_type}
        )

    def get(self, key: str) -> bytes:
        response = self._client().get_object(Bucket=self.bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def delete_prefix(self, prefix: str) -> int:
        if not prefix.startswith("tenants/"):
            raise PermissionError("refusing to delete outside a tenant prefix")
        client = self._client()
        deleted = 0
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
                deleted += len(keys)
        return deleted

    def signed_get_url(self, key: str, seconds: int) -> str:
        url: str = self._client(self.public_endpoint).generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=seconds
        )
        return url


@dataclass(slots=True)
class MemoryObjectStore:
    """In-process store for tests."""

    objects: dict[str, tuple[bytes, str]]

    def __init__(self) -> None:
        self.objects = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def put_file(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def get(self, key: str) -> bytes:
        return self.objects[key][0]

    def delete_prefix(self, prefix: str) -> int:
        doomed = [key for key in self.objects if key.startswith(prefix)]
        for key in doomed:
            del self.objects[key]
        return len(doomed)

    def signed_get_url(self, key: str, seconds: int) -> str:
        return f"memory://{key}?expires={seconds}"
