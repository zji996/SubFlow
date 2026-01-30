#!/usr/bin/env python3
"""Cleanup orphan artifacts in the artifact store that are not associated with any project."""

from __future__ import annotations

import argparse
import asyncio

from subflow.config import Settings
from subflow.repositories import DatabasePool, ProjectRepository
from subflow.storage import get_artifact_store


async def _run(*, dry_run: bool) -> None:
    settings = Settings()
    pool = await DatabasePool.get_pool(settings)
    try:
        project_repo = ProjectRepository(pool)
        store = get_artifact_store(settings)

        db_project_ids = set(await project_repo.list_all_ids())
        store_project_ids = set(await store.list_project_ids())
        orphan_ids = sorted(store_project_ids - db_project_ids)

        print(f"Database projects: {len(db_project_ids)}")
        print(f"Store projects: {len(store_project_ids)}")
        print(f"Orphan projects: {len(orphan_ids)}")

        if not orphan_ids:
            print("No orphan artifacts to clean up.")
            return

        for project_id in orphan_ids:
            if dry_run:
                print(f"[DRY-RUN] Would delete: {project_id}")
                continue
            deleted = await store.delete_project(project_id)
            print(f"Deleted {project_id}: {deleted}")
    finally:
        await DatabasePool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only list, don't delete")
    args = parser.parse_args()
    asyncio.run(_run(dry_run=bool(args.dry_run)))


if __name__ == "__main__":
    main()

