from fastapi import APIRouter, Request, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import json
import subprocess
import tempfile
import zipfile
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime

import db
from db import VALID_SEVERITIES

router = APIRouter()

UPLOADS_DIR = Path("/app/uploads")
UPLOADS_DIR.mkdir(exist_ok=True)


class IssueUpdate(BaseModel):
    """Triage update for a single Bandit finding."""
    issue_severity: Optional[str] = None
    false_positive: Optional[bool] = None


def relativize_paths(scan_data: dict, base_path: Path) -> dict:
    """Strip the on-disk scan directory from filenames so the UI/export
    never leak the container's internal paths. Paths become relative to
    the uploaded folder / cloned repo (e.g. ``myrepo/app/views.py``)."""
    base = Path(base_path)
    prefix = str(base)

    def rel(p):
        if not isinstance(p, str):
            return p
        try:
            return str(Path(p).relative_to(base))
        except ValueError:
            return p[len(prefix):].lstrip("/\\") if p.startswith(prefix) else p

    for result in scan_data.get("results", []):
        if isinstance(result, dict) and "filename" in result:
            result["filename"] = rel(result["filename"])

    metrics = scan_data.get("metrics")
    if isinstance(metrics, dict):
        scan_data["metrics"] = {
            (k if k == "_totals" else rel(k)): v for k, v in metrics.items()
        }
    return scan_data


@router.post("/api/scan/upload")
async def upload_project(files: List[UploadFile] = File(...)):
    """Upload a project directory (its files) for scanning.

    The browser sends each file with its directory-relative path as the
    filename (set via `webkitRelativePath` on the client), so we rebuild
    the folder tree under the scan's `extracted` directory.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    scan_id = str(uuid.uuid4())
    project_dir = UPLOADS_DIR / scan_id
    extract_dir = project_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_root = extract_dir.resolve()

    saved = 0
    for upload in files:
        # Drop empty/'.'/'..' segments and leading slashes to prevent
        # writing outside the extract directory (path traversal).
        parts = [
            p for p in Path(upload.filename or "").parts
            if p not in ("", ".", "..") and not p.startswith(("/", "\\"))
        ]
        if not parts:
            continue

        dest = extract_dir.joinpath(*parts)
        try:
            dest.resolve().relative_to(extract_root)
        except ValueError:
            continue  # resolved outside the sandbox; skip

        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await upload.read()
        with open(dest, "wb") as f:
            f.write(content)
        saved += 1

    if saved == 0:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No valid files uploaded")

    return {"scan_id": scan_id, "file_count": saved}

@router.post("/api/scan/start/{scan_id}")
async def start_scan(scan_id: str, background_tasks: BackgroundTasks):
    """Start a Bandit security scan for the uploaded project"""
    project_dir = UPLOADS_DIR / scan_id
    extract_dir = project_dir / "extracted"
    
    if not extract_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Start background scan
    background_tasks.add_task(run_bandit_scan, scan_id, extract_dir)
    
    return {"message": "Scan started", "scan_id": scan_id}

@router.get("/api/scan/status/{scan_id}")
async def get_scan_status(scan_id: str):
    """Get the status of a scan"""
    if await db.scan_exists(scan_id):
        return {"status": "completed", "scan_id": scan_id}
    return {"status": "running", "scan_id": scan_id}

@router.get("/api/scan/results/{scan_id}")
async def get_scan_results(scan_id: str):
    """Get the results of a completed scan"""
    scan = await db.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan results not found")
    return scan

@router.patch("/api/scan/results/{scan_id}/issues/{index}")
async def update_issue(scan_id: str, index: int, update: IssueUpdate):
    """Triage a single finding: override its severity and/or mark it as a
    false positive. Changes are persisted and metric totals recomputed."""
    severity = None
    if update.issue_severity is not None:
        severity = update.issue_severity.upper()
        if severity not in VALID_SEVERITIES:
            raise HTTPException(status_code=400, detail="Invalid severity")

    result = await db.triage_issue(scan_id, index, severity, update.false_positive)

    if result == "not_found":
        raise HTTPException(status_code=404, detail="Scan results not found")
    if result == "out_of_range":
        raise HTTPException(status_code=404, detail="Issue not found")

    return result


@router.get("/api/scan/list")
async def list_scans():
    """List all completed scans"""
    return {"scans": await db.list_scan_summaries()}

@router.delete("/api/scan/{scan_id}")
async def delete_scan(scan_id: str):
    """Delete a scan and its results"""
    await db.delete_scan(scan_id)

    # Remove the uploaded source from the filesystem too
    project_dir = UPLOADS_DIR / scan_id
    if project_dir.exists():
        shutil.rmtree(project_dir)

    return {"message": "Scan deleted successfully"}

async def run_bandit_scan(scan_id: str, project_path: Path):
    """Run Bandit scan in background"""
    try:
        # Run Bandit command
        result = subprocess.run([
            "bandit", "-r", str(project_path),
            "-f", "json",
            "--exit-zero"  # Don't exit with error code on findings
        ], capture_output=True, text=True, cwd="/")

        # Parse JSON output
        if result.stdout:
            scan_data = json.loads(result.stdout)
        else:
            scan_data = {"results": [], "metrics": {}, "errors": [result.stderr]}

        # Strip the container's internal upload path from all filenames
        relativize_paths(scan_data, project_path)

        # Add scan metadata
        scan_data["scan_id"] = scan_id
        scan_data["scan_date"] = datetime.now().isoformat()

        await db.save_scan(scan_id, scan_data)

    except Exception as e:
        # Persist an error record so the failure is visible in the UI
        error_data = {
            "scan_id": scan_id,
            "scan_date": datetime.now().isoformat(),
            "error": str(e),
            "results": [],
            "metrics": {}
        }
        await db.save_scan(scan_id, error_data)