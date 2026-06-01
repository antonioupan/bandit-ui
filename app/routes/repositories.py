from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any
import json
import subprocess
import shutil
import schedule
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
import uuid
import os

import db
from routes.scan import relativize_paths

router = APIRouter()

REPOS_DIR = Path("/app/repositories")
REPOS_DIR.mkdir(exist_ok=True)

class Repository(BaseModel):
    name: str
    git_url: Optional[str] = None
    branch: str = "main"
    scan_schedule: Optional[str] = None  # cron-like: "daily", "weekly", "hourly"
    scan_config: Dict[str, Any] = {}

class ScanConfig(BaseModel):
    severity_level: str = "all"  # all, low, medium, high
    confidence_level: str = "all"  # all, low, medium, high
    exclude_paths: list = []
    include_tests: list = []
    exclude_tests: list = []

@router.post("/api/repositories")
async def create_repository(repo: Repository, background_tasks: BackgroundTasks):
    """Add a new repository for scanning"""
    repo_id = str(uuid.uuid4())
    repo_data = repo.dict()
    repo_data["id"] = repo_id
    repo_data["created_at"] = datetime.now().isoformat()
    repo_data["last_scan"] = None

    # Save repository config
    await db.save_repository(repo_data)

    # If it's a Git repo, clone it
    if repo.git_url:
        background_tasks.add_task(clone_repository, repo_id, repo.git_url, repo.branch)
    
    # Schedule scans if specified
    if repo.scan_schedule:
        schedule_repository_scan(repo_id, repo.scan_schedule)
    
    return {"repository_id": repo_id, "message": "Repository added successfully"}

@router.get("/api/repositories")
async def list_repositories():
    """List all configured repositories"""
    return {"repositories": await db.list_repositories()}

@router.get("/api/repositories/{repo_id}")
async def get_repository(repo_id: str):
    """Get repository details"""
    repo_data = await db.get_repository(repo_id)
    if repo_data is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo_data

@router.put("/api/repositories/{repo_id}")
async def update_repository(repo_id: str, repo: Repository):
    """Update repository configuration"""
    existing_data = await db.get_repository(repo_id)
    if existing_data is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Update with new data
    repo_data = repo.dict()
    repo_data.update({
        "id": repo_id,
        "created_at": existing_data.get("created_at"),
        "updated_at": datetime.now().isoformat(),
        "last_scan": existing_data.get("last_scan")
    })

    await db.save_repository(repo_data)
    return {"message": "Repository updated successfully"}

@router.delete("/api/repositories/{repo_id}")
async def delete_repository(repo_id: str):
    """Delete a repository configuration"""
    # Removes the repo config and all of its scans from the database
    await db.delete_repository(repo_id)

    repo_dir = REPOS_DIR / repo_id
    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    return {"message": "Repository deleted successfully"}

@router.post("/api/repositories/{repo_id}/scan")
async def trigger_repository_scan(repo_id: str, background_tasks: BackgroundTasks):
    """Manually trigger a scan for a repository"""
    repo_data = await db.get_repository(repo_id)
    if repo_data is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    background_tasks.add_task(scan_repository, repo_id, repo_data)

    return {"message": "Scan triggered successfully", "repository_id": repo_id}

@router.get("/api/repositories/{repo_id}/scans")
async def get_repository_scans(repo_id: str):
    """Get scan history for a repository"""
    return {"scans": await db.list_repository_scan_summaries(repo_id)}

async def clone_repository(repo_id: str, git_url: str, branch: str = "main"):
    """Clone a Git repository"""
    repo_dir = REPOS_DIR / repo_id
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    
    try:
        result = subprocess.run([
            "git", "clone", "--branch", branch, "--depth", "1", git_url, str(repo_dir)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Failed to clone repository {repo_id}: {result.stderr}")
    except Exception as e:
        print(f"Error cloning repository {repo_id}: {str(e)}")

async def scan_repository(repo_id: str, repo_data: dict):
    """Scan a repository with Bandit"""
    repo_dir = REPOS_DIR / repo_id
    if not repo_dir.exists():
        # Try to clone if it doesn't exist
        if repo_data.get("git_url"):
            await clone_repository(repo_id, repo_data["git_url"], repo_data.get("branch", "main"))
    
    if not repo_dir.exists():
        print(f"Repository directory not found for {repo_id}")
        return
    
    scan_config = repo_data.get("scan_config", {})
    
    # Build Bandit command
    cmd = ["bandit", "-r", str(repo_dir), "-f", "json", "--exit-zero"]
    
    if scan_config.get("severity_level") != "all":
        cmd.extend(["--severity-level", scan_config["severity_level"]])
    
    if scan_config.get("confidence_level") != "all":
        cmd.extend(["--confidence-level", scan_config["confidence_level"]])
    
    if scan_config.get("exclude_paths"):
        cmd.extend(["-x", ",".join(scan_config["exclude_paths"])])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="/")
        
        if result.stdout:
            scan_data = json.loads(result.stdout)
        else:
            scan_data = {"results": [], "metrics": {}, "errors": [result.stderr]}

        # Strip the container's internal repo path from all filenames
        relativize_paths(scan_data, repo_dir)

        # Add scan metadata
        scan_id = f"repo_{repo_id}_{int(time.time())}"
        scan_data["scan_id"] = scan_id
        scan_data["repository_id"] = repo_id
        scan_data["scan_date"] = datetime.now().isoformat()
        scan_data["scan_type"] = "repository"

        await db.save_scan(scan_id, scan_data)

        # Update repository's last scan time
        await db.set_repository_last_scan(repo_id, datetime.now().isoformat())

    except Exception as e:
        print(f"Error scanning repository {repo_id}: {str(e)}")

def schedule_repository_scan(repo_id: str, schedule_type: str):
    """Schedule periodic scans for a repository"""
    # This is a simplified scheduler - in production, use Celery or similar
    def run_scan():
        import asyncio

        async def _do():
            repo_data = await db.get_repository(repo_id)
            if repo_data:
                await scan_repository(repo_id, repo_data)

        try:
            asyncio.run(_do())
        except Exception as e:
            print(f"Scheduled scan failed for {repo_id}: {e}")

    if schedule_type == "hourly":
        schedule.every().hour.do(run_scan)
    elif schedule_type == "daily":
        schedule.every().day.at("02:00").do(run_scan)
    elif schedule_type == "weekly":
        schedule.every().week.do(run_scan)

# Background scheduler thread
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler thread
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()