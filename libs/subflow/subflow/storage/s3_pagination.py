"""Shared S3 pagination helpers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_list_objects_v2(client: Any, *, bucket: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
    """Iterate over `list_objects_v2` result pages.

    This centralizes the common ContinuationToken loop used across S3/MinIO calls.
    """

    token: str | None = None
    while True:
        call_kwargs: dict[str, Any] = {"Bucket": bucket, **kwargs}
        if token:
            call_kwargs["ContinuationToken"] = token

        resp: dict[str, Any] = dict(client.list_objects_v2(**call_kwargs))
        yield resp

        if resp.get("IsTruncated"):
            token = str(resp.get("NextContinuationToken") or "")
            if not token:
                break
            continue

        break
