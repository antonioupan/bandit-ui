"""MongoDB storage layer for scans and repositories.

The raw uploaded source and cloned repos stay on the filesystem; this module
persists scan *results/metadata* and repository configs. All callers are async
(FastAPI routes / background tasks), so we use motor.
"""
import os
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongo:27017")
DB_NAME = os.environ.get("MONGO_DB", "bandit_ui")

VALID_SEVERITIES = ("HIGH", "MEDIUM", "LOW")

_client: Optional[AsyncIOMotorClient] = None
_indexes_ready = False


def get_db():
    """Return the database handle, creating the client lazily on first use so
    motor binds to the running event loop."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URL)
    return _client[DB_NAME]


async def _ensure_indexes():
    global _indexes_ready
    if _indexes_ready:
        return
    db = get_db()
    await db.scans.create_index("generated_at")
    await db.scans.create_index("repository_id")
    await db.scans.create_index("scan_date")
    _indexes_ready = True


def _sanitize_for_mongo(scan_data: Dict[str, Any]) -> Dict[str, Any]:
    """Bandit's ``metrics`` is keyed by filename, and filenames contain dots/
    slashes which are illegal as Mongo field names. Keep only ``_totals`` under
    ``metrics`` and move the per-file entries into a list."""
    metrics = scan_data.get("metrics")
    if isinstance(metrics, dict):
        by_file = [
            {"filename": k, **(v if isinstance(v, dict) else {"value": v})}
            for k, v in metrics.items()
            if k != "_totals"
        ]
        scan_data["metrics"] = {"_totals": metrics.get("_totals", {})}
        if by_file:
            scan_data["metrics_by_file"] = by_file
    return scan_data


def recompute_totals(results: List[dict]) -> Dict[str, int]:
    """Severity counts excluding false positives."""
    counts = {f"SEVERITY.{s}": 0 for s in VALID_SEVERITIES}
    for result in results:
        if not isinstance(result, dict) or result.get("false_positive"):
            continue
        key = f"SEVERITY.{result.get('issue_severity', '')}"
        if key in counts:
            counts[key] += 1
    return counts


# --- Scans -----------------------------------------------------------------

async def save_scan(scan_id: str, scan_data: Dict[str, Any]) -> None:
    await _ensure_indexes()
    doc = _sanitize_for_mongo({**scan_data, "scan_id": scan_data.get("scan_id", scan_id)})
    doc["_id"] = scan_id
    await get_db().scans.replace_one({"_id": scan_id}, doc, upsert=True)


async def get_scan(scan_id: str) -> Optional[Dict[str, Any]]:
    return await get_db().scans.find_one({"_id": scan_id}, {"_id": 0})


async def scan_exists(scan_id: str) -> bool:
    return await get_db().scans.count_documents({"_id": scan_id}, limit=1) > 0


async def delete_scan(scan_id: str) -> None:
    await get_db().scans.delete_one({"_id": scan_id})


def _summary_pipeline(match: Optional[dict] = None, sort_field: str = "generated_at"):
    pipeline = []
    if match:
        pipeline.append({"$match": match})
    pipeline += [
        {"$project": {
            "_id": 0,
            "scan_id": {"$ifNull": ["$scan_id", {"$toString": "$_id"}]},
            "generated_at": "$generated_at",
            "scan_date": "$scan_date",
            "metrics": {"$ifNull": ["$metrics._totals", {}]},
            "total_issues": {
                "$size": {"$filter": {
                    "input": {"$ifNull": ["$results", []]},
                    "as": "r",
                    "cond": {"$ne": ["$$r.false_positive", True]},
                }},
            },
        }},
        {"$sort": {sort_field: -1}},
    ]
    return pipeline


async def list_scan_summaries() -> List[Dict[str, Any]]:
    await _ensure_indexes()
    cursor = get_db().scans.aggregate(_summary_pipeline())
    return await cursor.to_list(length=None)


async def triage_issue(scan_id: str, index: int, severity: Optional[str],
                       false_positive: Optional[bool]):
    """Update a single finding with a targeted ``$set`` so concurrent triage of
    different issues can't clobber each other. Returns the updated issue dict,
    or the sentinel strings ``"not_found"`` / ``"out_of_range"``."""
    db = get_db()
    doc = await db.scans.find_one({"_id": scan_id}, {"results": 1, "metrics": 1})
    if not doc:
        return "not_found"

    results = doc.get("results", [])
    if index < 0 or index >= len(results):
        return "out_of_range"

    issue = results[index]
    set_fields: Dict[str, Any] = {}

    if severity is not None:
        if "original_severity" not in issue:
            original = issue.get("issue_severity")
            set_fields[f"results.{index}.original_severity"] = original
            issue["original_severity"] = original
        set_fields[f"results.{index}.issue_severity"] = severity
        issue["issue_severity"] = severity

    if false_positive is not None:
        set_fields[f"results.{index}.false_positive"] = false_positive
        issue["false_positive"] = false_positive

    # Recompute severity totals from the now-updated results.
    existing_totals = doc.get("metrics", {}).get("_totals", {})
    set_fields["metrics._totals"] = {**existing_totals, **recompute_totals(results)}

    await db.scans.update_one({"_id": scan_id}, {"$set": set_fields})
    return issue


# --- Repositories ----------------------------------------------------------

async def save_repository(repo_data: Dict[str, Any]) -> None:
    repo_id = repo_data["id"]
    doc = {**repo_data, "_id": repo_id}
    await get_db().repositories.replace_one({"_id": repo_id}, doc, upsert=True)


async def get_repository(repo_id: str) -> Optional[Dict[str, Any]]:
    return await get_db().repositories.find_one({"_id": repo_id}, {"_id": 0})


async def list_repositories() -> List[Dict[str, Any]]:
    cursor = get_db().repositories.find({}, {"_id": 0})
    return await cursor.to_list(length=None)


async def delete_repository(repo_id: str) -> None:
    db = get_db()
    await db.repositories.delete_one({"_id": repo_id})
    await db.scans.delete_many({"repository_id": repo_id})


async def set_repository_last_scan(repo_id: str, timestamp: str) -> None:
    await get_db().repositories.update_one(
        {"_id": repo_id}, {"$set": {"last_scan": timestamp}}
    )


async def list_repository_scan_summaries(repo_id: str) -> List[Dict[str, Any]]:
    await _ensure_indexes()
    cursor = get_db().scans.aggregate(
        _summary_pipeline({"repository_id": repo_id}, sort_field="scan_date")
    )
    return await cursor.to_list(length=None)
