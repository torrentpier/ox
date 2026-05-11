"""S3-compatible client for Cloudflare R2."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

log = logging.getLogger(__name__)


@dataclass
class R2Client:
    bucket: str
    endpoint: str
    public_base: str
    access_key: str
    secret_key: str
    s3: Any = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.s3 = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 5, "mode": "standard"},
                # Default is 10; our ThreadPool reaches 16, and verify is
                # almost all concurrent HEADs.
                max_pool_connections=64,
            ),
            region_name="auto",
        )

    def head(self, key: str) -> dict[str, Any] | None:
        try:
            return self.s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404", "NotFound"):
                return None
            raise

    def put(self, key: str, body: bytes, content_type: str | None = None) -> None:
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": body}
        if content_type:
            kwargs["ContentType"] = content_type
        self.s3.put_object(**kwargs)

    def public_url(self, key: str) -> str:
        return self.public_base.rstrip("/") + "/" + quote(key, safe="/")


def from_env() -> R2Client:
    """Build an R2Client from `.env` (loaded if present) and the environment.

    Required vars: R2_BUCKET, R2_ENDPOINT, R2_PUBLIC_URL, R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY.
    """
    load_dotenv()
    return R2Client(
        bucket=os.environ["R2_BUCKET"],
        endpoint=os.environ["R2_ENDPOINT"],
        public_base=os.environ["R2_PUBLIC_URL"],
        access_key=os.environ["R2_ACCESS_KEY_ID"],
        secret_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
