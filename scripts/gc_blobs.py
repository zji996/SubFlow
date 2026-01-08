from __future__ import annotations

import argparse
import asyncio

from subflow.config import Settings
from subflow.services import BlobStore


async def _main() -> int:
    parser = argparse.ArgumentParser(description="GC unreferenced blobs (ref_count=0).")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    settings = Settings()
    store = BlobStore(settings)
    deleted = await store.gc_unreferenced(limit=int(args.limit), dry_run=bool(args.dry_run))
    print(f"gc_unreferenced deleted={deleted} dry_run={bool(args.dry_run)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

