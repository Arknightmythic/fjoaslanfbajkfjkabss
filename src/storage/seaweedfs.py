from functools import lru_cache
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


@lru_cache(maxsize=1)
def get_s3_client():
    """Return an S3-compatible client configured for SeaweedFS."""
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "http://127.0.0.1:8333")
    access_key = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("SEAWEEDFS_ACCESS_KEY")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("SEAWEEDFS_SECRET_KEY")
    if not access_key or not secret_key:
        raise RuntimeError("S3 credentials are not configured")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def ensure_bucket_exists(client=None, bucket: str | None = None) -> str:
    client = client or get_s3_client()
    bucket = bucket or os.getenv("S3_BUCKET", "chatbot-documents")
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
            raise
        try:
            client.create_bucket(Bucket=bucket)
        except ClientError as create_error:
            create_code = str(create_error.response.get("Error", {}).get("Code", ""))
            if create_code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise
    return bucket


def get_knowledge_ingest_prefix(source_type: str = "faq") -> str:
    """Return the SeaweedFS prefix eligible for the given knowledge source type."""
    from src.knowledge.source_types import ingest_prefix_for

    return ingest_prefix_for(source_type)
