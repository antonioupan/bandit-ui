# Bandit UI

A web interface for running [Bandit](https://github.com/PyCQA/bandit), the Python
security static analysis tool. Upload a project or point it at a Git repository,
run a scan, and triage the findings from your browser — no command line required.

Built with FastAPI, MongoDB, and a lightweight HTML/JS frontend, packaged to run
with Docker Compose.

## Features

- **Scan uploaded projects** — upload a folder from the browser and scan it with Bandit.
- **Scan Git repositories** — register a repo by URL/branch and scan it on demand.
- **Scheduled scans** — configure repositories to rescan on a recurring schedule (hourly/daily/weekly).
- **Findings triage** — adjust a finding's severity or mark it as a false positive.
- **Persistent results** — scan results and repository configs are stored in MongoDB.
- **Dashboard & history** — browse past scans and per-repository scan history.
- **Path-safe by design** — uploaded paths are sandboxed against traversal, and
  internal container paths are stripped from results before they reach the UI.

## Quick start

The fastest way to run Bandit UI is with Docker Compose:

```bash
git clone <your-fork-url> bandit-ui
cd bandit-ui
docker compose up --build
```

Then open <http://localhost:8082> in your browser.

This starts two services:

| Service     | Description                       | Port (host) |
|-------------|-----------------------------------|-------------|
| `bandit-ui` | FastAPI app + Bandit              | `8082`      |
| `mongo`     | MongoDB 8 (scan & repo storage)   | `27017`     |

MongoDB data is persisted to `./mongo_data` via a host bind mount, so scans
survive container restarts.

## Usage

1. **Upload & scan a project** — go to the **Scan** page, choose a project
   folder, upload it, and start the scan. When it finishes you'll be taken to a
   results view.
2. **Scan a repository** — register a repository (name, Git URL, branch, and an
   optional scan schedule), then trigger a scan from its entry.
3. **Triage findings** — in the results view you can change a finding's severity
   or flag it as a false positive; changes are saved back to the scan record.

## API

The frontend is driven by a small REST API. Highlights:

**Scans**

| Method   | Path                                         | Description                          |
|----------|----------------------------------------------|--------------------------------------|
| `POST`   | `/api/scan/upload`                           | Upload project files                 |
| `POST`   | `/api/scan/start/{scan_id}`                  | Start a Bandit scan                  |
| `GET`    | `/api/scan/status/{scan_id}`                 | Check scan status                    |
| `GET`    | `/api/scan/results/{scan_id}`                | Get scan results                     |
| `PATCH`  | `/api/scan/results/{scan_id}/issues/{index}` | Update a finding (severity / FP)     |
| `GET`    | `/api/scan/list`                             | List all scans                       |
| `DELETE` | `/api/scan/{scan_id}`                         | Delete a scan                        |

**Repositories**

| Method   | Path                                | Description                       |
|----------|-------------------------------------|-----------------------------------|
| `POST`   | `/api/repositories`                 | Register a repository             |
| `GET`    | `/api/repositories`                 | List repositories                 |
| `GET`    | `/api/repositories/{repo_id}`       | Get a repository                  |
| `PUT`    | `/api/repositories/{repo_id}`       | Update a repository               |
| `DELETE` | `/api/repositories/{repo_id}`       | Delete a repository               |
| `POST`   | `/api/repositories/{repo_id}/scan`  | Trigger a scan                    |
| `GET`    | `/api/repositories/{repo_id}/scans` | List a repository's scan history  |

A `GET /health` endpoint is available for health checks.

## Configuration

The app is configured via environment variables (set in `docker-compose.yml`):

| Variable    | Default                 | Description               |
|-------------|-------------------------|---------------------------|
| `MONGO_URL` | `mongodb://mongo:27017` | MongoDB connection string |
| `MONGO_DB`  | `bandit_ui`             | Database name             |

## Project structure

```
app/
  main.py            # FastAPI app; auto-registers routers from routes/
  db.py              # MongoDB (motor) storage layer
  routes/            # API + page routes (scan, repositories, dashboard, …)
  templates/         # Jinja2 HTML templates
  static/            # CSS / JS / images
build/
  requirements.txt   # Python dependencies
Dockerfile
docker-compose.yml
```

## Development

The Compose setup mounts `./app` into the container and runs Uvicorn with
`--reload`, so edits to the Python source reload automatically.

To run without Docker you'll need Python 3.12, a running MongoDB, and Bandit
available on the path:

```bash
pip install -r build/requirements.txt
cd app
MONGO_URL=mongodb://localhost:27017 python -m uvicorn main:app --reload --port 8000
```

## Related projects

- [Bandit](https://github.com/PyCQA/bandit) — the underlying Python security
  static analysis tool, maintained by [PyCQA](https://github.com/PyCQA).
  Documentation: <https://bandit.readthedocs.io/>.

## License

Licensed under the [Apache License 2.0](LICENSE).
