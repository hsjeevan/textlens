# TextLens

A FastAPI service that analyses uploaded `.txt` files. It reports word and
sentence counts, the top keywords, tone (sentiment) and themes. Each upload is
processed in the background by a Prefect flow, and run status and results are
cached in Redis. A Streamlit dashboard sits in front of the API.

```
Browser ──► Streamlit dashboard ──► POST /upload ──► validate & save file ──► Prefect flow (background thread)
                                          │                                     read → tokenize → stats | keywords | tone | themes
                                          ▼                                     (step outputs + final result cached in Redis)
                                      202 {run_id}
                                    GET /insights/{run_id} ◄── run status / result from Redis
```

All commands below are for **Windows PowerShell**, run from the repository root.

## Quick start on Kubernetes (recommended)

This is the main way to run TextLens. It targets **Docker Desktop's built-in
Kubernetes**, which can use locally built images without a registry.

**Prerequisites**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/), running,
  with Kubernetes turned on (Settings → Kubernetes → Enable Kubernetes)
- `kubectl` (Docker Desktop installs it). Check it points at Docker Desktop:

```powershell
kubectl config current-context    # expect: docker-desktop
```

**1. Build the images**

```powershell
docker compose build
```

This builds `textlens-api:latest` (from `Dockerfile`) and
`textlens-frontend:latest` (from `Dockerfile.frontend`). The first build takes
a few minutes.

**2. Deploy**

```powershell
kubectl create namespace textlens --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n textlens -f k8s\
kubectl rollout status -n textlens deploy/textlens-redis
kubectl rollout status -n textlens deploy/textlens-api
kubectl rollout status -n textlens deploy/textlens-frontend
```

The first line creates the namespace, and does nothing if it already exists.

**3. Open the dashboard**

All Services are internal to the cluster, so forward them to your machine.
Each `port-forward` keeps running until you stop it, so start them as hidden
background processes:

```powershell
Start-Process kubectl -ArgumentList 'port-forward -n textlens svc/textlens-frontend 8501:80' -WindowStyle Hidden
Start-Process kubectl -ArgumentList 'port-forward -n textlens svc/textlens-api 8000:80' -WindowStyle Hidden
```

| What | URL |
|---|---|
| Dashboard (upload a `.txt` here) | http://localhost:8501 |
| API docs | http://localhost:8000/docs |

The dashboard talks to the API inside the cluster, so the API port-forward is
only needed for the API docs or for calling the API yourself. To keep a
port-forward in the foreground instead, run the same `kubectl port-forward …`
command in its own terminal and press `Ctrl+C` to stop it.

If port 8000 or 8501 is already in use, change the left-hand number, for
example `8088:80`.

### Managing the deployment

| Task | Command |
|---|---|
| Check status | `kubectl get pods -n textlens` |
| Stop the app (keep everything deployed) | `kubectl scale deploy --all -n textlens --replicas=0` |
| Start it again | `kubectl apply -n textlens -f k8s\` |
| Redeploy after code changes | `docker compose build` then `kubectl rollout restart -n textlens deploy/textlens-api deploy/textlens-frontend` |
| Follow API logs | `kubectl logs -n textlens deploy/textlens-api -f` |
| Follow dashboard logs | `kubectl logs -n textlens deploy/textlens-frontend -f` |
| Stop the port-forwards | `Get-Process kubectl \| Stop-Process` (stops **every** running `kubectl`) |
| Remove everything | `kubectl delete namespace textlens` |

`kubectl apply` restores the replica counts in the manifests (Redis 1, API 2,
dashboard 1). Redis keeps no data, so stopping it clears past run results.

### What gets deployed

`k8s\deployment.yaml` defines three Deployments and `k8s\service.yaml` three
ClusterIP Services, all in the `textlens` namespace:

| Component | Deployment / Service | Replicas | Connects to |
|---|---|---|---|
| Redis | `textlens-redis` | 1 | — |
| API | `textlens-api` | 2 | Redis via `REDIS_URL=redis://textlens-redis:6379/0` |
| Dashboard | `textlens-frontend` | 1 | API via `TEXTLENS_API_URL=http://textlens-api` |

The hostnames are Service DNS names, so all three must be in the same namespace.

### Troubleshooting

```powershell
kubectl get pods -n textlens
kubectl describe pod -n textlens -l app.kubernetes.io/name=textlens-api        # e.g. image pull errors
kubectl logs -n textlens deploy/textlens-api
kubectl exec -n textlens deploy/textlens-frontend -- python -c "import requests; print(requests.get('http://textlens-api/health').text)"
```

The last command checks that the dashboard pod can reach the API.

- **`ErrImagePull` / `ImagePullBackOff`:** the cluster can't see your local
  image. Rebuild with `docker compose build`, and check you're on the
  `docker-desktop` context.
- **The dashboard says it can't reach the API:** check the API pods are
  `Running` and `1/1` ready.
- **`localhost:8501` doesn't load:** the port-forward has stopped (they exit
  when pods are restarted). Start it again.

**Using minikube or kind instead:** these clusters can't see your local Docker
images. Load both images after building:

```powershell
minikube image load textlens-api:latest; minikube image load textlens-frontend:latest
# or
kind load docker-image textlens-api:latest textlens-frontend:latest
```

The manifests set `imagePullPolicy: IfNotPresent`, so no registry is needed.

### Deployment notes

- **Redis is a cache, not a database.** It has no persistence and all keys
  expire, so restarting the Redis pod clears run statuses and cached results.
  Point `REDIS_URL` at a managed or persistent Redis for anything long-lived.
- **Runs belong to the pod that received the upload.** Any API replica can
  answer `GET /insights`, but the flow runs in the receiving pod's thread pool.
  If that pod stops before a queued run starts, the run stays `pending` until
  it expires. Moving to a Prefect deployment with a separate worker would
  remove this limit.
- **The dashboard runs as a single replica.** Streamlit keeps each browser
  session in memory, so more replicas would need sticky sessions.
- **Root filesystems are read-only.** The only writable path in each pod is
  `/tmp`, an `emptyDir`. The API keeps uploads and Prefect's local database
  there; the dashboard uses it as `HOME`.
- **The first upload on each API pod is slower** by a few seconds while
  Prefect starts its local server.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Multipart upload with a `file` field (`.txt`, UTF-8, ≤ 5 MB). Returns `202 {run_id, status, status_url}` |
| `GET` | `/insights/{run_id}` | Returns `status`: `pending` → `running` → `completed` / `failed`. Includes `result` once completed, or `error` if failed |
| `GET` | `/health` | Liveness check |

Interactive docs are served at `/docs`. With the API port-forward running:

```powershell
$run = curl.exe -s -F "file=@sample.txt" http://localhost:8000/upload | ConvertFrom-Json
$run    # run_id, status, status_url
Invoke-RestMethod "http://localhost:8000/insights/$($run.run_id)"
```

Use `curl.exe`, not `curl`: in Windows PowerShell, `curl` is an alias for
`Invoke-WebRequest`, which doesn't accept `-F`.

## Configuration

API settings:

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `UPLOAD_DIR` | `uploads` | Where uploads are stored until their flow finishes |
| `TEXTLENS_MAX_CONCURRENT_RUNS` | `4` | Flow runs processed at once, per API process |
| `TEXTLENS_RUN_TTL_SECONDS` | `86400` | How long run status records are kept |
| `TEXTLENS_CACHE_TTL_SECONDS` | `604800` | How long cached analysis results are kept |
| `PREFECT_API_URL` | *(unset)* | Point at a Prefect server; if unset, Prefect runs a temporary local one |

Dashboard settings:

| Variable | Default | Purpose |
|---|---|---|
| `TEXTLENS_API_URL` | `http://localhost:8000` | Base URL of the API |

Theme and upload limit settings for the dashboard are in `.streamlit\config.toml`.
On Kubernetes, the values are set in the `env:` sections of `k8s\deployment.yaml`.

## Alternative: Docker Compose

Runs the same three services without Kubernetes. Use one or the other, not
both: Compose starts its own Redis and API, and both setups use ports 8000 and
8501 on your machine.

```powershell
docker compose up -d --build
```

The dashboard is then at http://localhost:8501 and the API docs at
http://localhost:8000/docs, with no port-forward needed.

| Task | Command |
|---|---|
| Start (or apply code changes) | `docker compose up -d --build` |
| Stop, keeping containers | `docker compose stop` |
| Start again after stopping | `docker compose start` |
| Restart one service | `docker compose restart api` (or `frontend`, `redis`) |
| Stop and remove everything | `docker compose down` |
| Check status | `docker compose ps` |
| Follow logs | `docker compose logs -f` (add `api` for one service) |

`restart` doesn't pick up code changes; rerun `docker compose up -d --build`
for that. If port 8000, 8501 or 6379 is already in use, change the left-hand
number under `ports:` in `docker-compose.yml`.

## Local development

Needs a recent Python (tested on 3.14; the Docker images use 3.14 too) and
Docker Desktop for Redis. The first run downloads NLTK data, so it needs
internet access.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
docker compose up -d redis          # Redis on localhost:6379
uvicorn main:app --reload           # API on localhost:8000
```

If `Activate.ps1` is blocked by the execution policy, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

Run the tests (they use in-memory fakeredis, so Redis isn't needed):

```powershell
pytest -q
```

Run the dashboard against the local API, in a second terminal with the venv
activated:

```powershell
pip install -r requirements-frontend.txt
$env:TEXTLENS_API_URL = "http://localhost:8000"
streamlit run app.py                # opens on localhost:8501
```

`TEXTLENS_API_URL` already defaults to `http://localhost:8000`, so the second
line is only needed when the API runs somewhere else.

Stop the Kubernetes port-forwards first if they're running, since they also use
ports 8000 and 8501.
