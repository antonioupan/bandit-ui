"""One-off migration: import existing file-based scan results and repository
configs into MongoDB.

Run inside the container:
    docker compose exec bandit-ui python migrate_to_mongo.py

Safe to re-run: every record is upserted by id.
"""
import asyncio
import json
from pathlib import Path

import db

SCAN_RESULTS_DIR = Path("/app/scan_results")
CONFIG_DIR = Path("/app/config")


async def main():
    scans = 0
    if SCAN_RESULTS_DIR.exists():
        for result_file in SCAN_RESULTS_DIR.glob("*.json"):
            try:
                with open(result_file, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                print(f"  skipped unreadable {result_file.name}")
                continue
            data.setdefault("scan_id", result_file.stem)
            await db.save_scan(result_file.stem, data)
            scans += 1

    repos = 0
    if CONFIG_DIR.exists():
        for config_file in CONFIG_DIR.glob("repo_*.json"):
            try:
                with open(config_file, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                print(f"  skipped unreadable {config_file.name}")
                continue
            data.setdefault("id", config_file.stem.replace("repo_", ""))
            await db.save_repository(data)
            repos += 1

    print(f"Migrated {scans} scan(s) and {repos} repository config(s) into MongoDB.")


if __name__ == "__main__":
    asyncio.run(main())
