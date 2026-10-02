# TextLens

A FastAPI service that analyses uploaded `.txt` files. It reports word and
sentence counts, the top keywords, tone (sentiment) and themes. Each upload is
processed in the background by a Prefect flow, and run status and results are
cached in Redis. A React dashboard (served by nginx, which also proxies
`/api/*` to the API) sits in front of it.

```
Browser ──► React dashboard (nginx) ──► POST /upload ──► validate & save file ──► Prefect flow (background thread)
                                              │                                     read → tokenize → stats | keywords | tone | themes
                                              ▼                                     (step outputs + final result cached in Redis)
                                          202 {run_id}
                                        GET /insights/{run_id} ◄── run status / result from Redis
```

Run all commands from the repository root. Most commands work in any shell.
Where Windows and macOS differ, both versions are shown: **PowerShell** for
Windows, and **zsh/bash** for macOS (and Linux).

## Quick start on Kubernetes (recommended)

This is the main way to run TextLens. It targets **Docker Desktop's built-in
Kubernetes**, which can use locally built images without a registry.

**Prerequisites**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/), running,
  with Kubernetes turned on (Settings → Kubernetes → Enable Kubernetes)
- `kubectl` (Docker Desktop installs it). Check it points at Docker Desktop:

```shell
kubectl config current-context    # expect: docker-desktop
```

**1. Build the images**

```shell
docker compose build
```

This builds `textlens-api:latest` (from `Dockerfile`) and
`textlens-frontend:latest` (from `Dockerfile.frontend`). The first build takes
a few minutes.

**Then, only if your cluster runs in kind mode**, copy the images into the
cluster. Check the node name with `kubectl get nodes`. If it's
`desktop-control-plane`, Docker Desktop is running Kubernetes with kind. That
node has its own image store, so it doesn't see what `docker compose build`
produced. (If the node is called `docker-desktop`, skip this step.)

Windows (PowerShell):

```powershell
docker save textlens-api:latest textlens-frontend:latest -o "$env:TEMP\textlens.tar"
docker cp "$env:TEMP\textlens.tar" desktop-control-plane:/textlens.tar
docker exec desktop-control-plane ctr -n k8s.io images import --all-platforms /textlens.tar
docker exec desktop-control-plane rm /textlens.tar
Remove-Item "$env:TEMP\textlens.tar"
```

macOS (zsh/bash):

```bash
docker save textlens-api:latest textlens-frontend:latest -o "${TMPDIR:-/tmp}/textlens.tar"
docker cp "${TMPDIR:-/tmp}/textlens.tar" desktop-control-plane:/textlens.tar
docker exec desktop-control-plane ctr -n k8s.io images import --all-platforms /textlens.tar
docker exec desktop-control-plane rm /textlens.tar
rm "${TMPDIR:-/tmp}/textlens.tar"
```

Repeat this after every rebuild. Otherwise the pods keep running the old image.

**2. Deploy**

```shell
kubectl create namespace textlens --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n textlens -f k8s/
kubectl rollout status -n textlens deploy/textlens-redis
kubectl rollout status -n textlens deploy/textlens-api
kubectl rollout status -n textlens deploy/textlens-frontend
```

The first line creates the namespace, and does nothing if it already exists.

**3. Open the dashboard**

The API and dashboard Services are `LoadBalancer` type, and Docker Desktop
publishes them on `localhost`, so they're reachable as soon as the rollout
finishes. No port-forward is needed.

| What | URL |
|---|---|
| Dashboard (upload a `.txt` here) | http://localhost:8501 |
| API docs | http://localhost:8000/docs |

Check that both Services show `localhost` under `EXTERNAL-IP`:

```shell
kubectl get svc -n textlens
```

If one shows `<pending>`, something else on your machine already holds port
8000 or 8501: an old `kubectl port-forward`, the Docker Compose setup, or a
local `uvicorn` / `npm run dev`. Stop it (`lsof -i :8501` shows what's using
the port) and the Service picks up the port by itself. To use other ports,
change `port:` for that Service in `k8s/service.yaml` and apply again.

### Managing the deployment

| Task | Command |
|---|---|
| Check status | `kubectl get pods -n textlens` |
| Stop the app (keep everything deployed) | `kubectl scale deploy --all -n textlens --replicas=0` |
| Start it again | `kubectl apply -n textlens -f k8s/` |
| Redeploy after code changes | `docker compose build`, then copy the images into the cluster in kind mode (see step 1), then `kubectl rollout restart -n textlens deploy/textlens-api deploy/textlens-frontend` |
| Follow API logs | `kubectl logs -n textlens deploy/textlens-api -f` |
| Follow dashboard logs | `kubectl logs -n textlens deploy/textlens-frontend -f` |
| Remove everything | `kubectl delete namespace textlens` |

`kubectl apply` restores the replica counts in the manifests (Redis 1, API 2,
dashboard 2). Redis keeps no data, so stopping it clears past run results.

### What gets deployed

`k8s/deployment.yaml` defines three Deployments and `k8s/service.yaml` three
Services, all in the `textlens` namespace. Redis is internal (`ClusterIP`); the
API (port 8000) and dashboard (port 8501) are `LoadBalancer` Services published
on `localhost`:

| Component | Deployment / Service | Replicas | Connects to |
|---|---|---|---|
| Redis | `textlens-redis` | 1 | - |
| API | `textlens-api` | 2 | Redis via `REDIS_URL=redis://textlens-redis:6379/0` |
| Dashboard | `textlens-frontend` | 2 | API via `TEXTLENS_API_URL=http://textlens-api:8000` (nginx proxies `/api/*` there) |

The hostnames are Service DNS names, so all three must be in the same namespace.

### Troubleshooting

```shell
kubectl get pods -n textlens
kubectl describe pod -n textlens -l app.kubernetes.io/name=textlens-api        # e.g. image pull errors
kubectl logs -n textlens deploy/textlens-api
kubectl exec -n textlens deploy/textlens-frontend -- wget -qO- http://127.0.0.1:8080/api/health
```

The last command checks that the dashboard's nginx can proxy to the API.

- **`ErrImagePull` / `ImagePullBackOff`:** the cluster can't see your local
  image. Rebuild with `docker compose build`, and check you're on the
  `docker-desktop` context.
- **The dashboard says it can't reach the API:** check the API pods are
  `Running` and `1/1` ready.
- **The UI doesn't change after a redeploy:** the cluster is in kind mode and
  still has the old image. Check with
  `kubectl exec -n textlens deploy/textlens-frontend -- ls /usr/share/nginx/html/assets`
  (the bundle file names change with every build). Copy the
  images into the cluster (step 1), then run `rollout restart` again.
- **`localhost:8501` or `localhost:8000` doesn't load:** run
  `kubectl get svc -n textlens`. An `EXTERNAL-IP` of `<pending>` means the port
  is taken on your machine; see step 3.

**Using minikube or kind instead:** these clusters can't see your local Docker
images. Load both images after building:

```shell
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
- **The dashboard is stateless.** It is a static React bundle; all UI state
  lives in the browser, so it scales to any number of replicas.
- **Root filesystems are read-only.** The only writable path in each pod is
  `/tmp`, an `emptyDir`. The API keeps uploads and Prefect's local database
  there; nginx keeps its pid and temp files there. The dashboard also mounts an
  `emptyDir` at `/etc/nginx/conf.d`, where nginx renders its config from the
  template at startup.
- **The first upload on each API pod is slower** by a few seconds while
  Prefect starts its local server.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Multipart upload with a `file` field (`.txt`, UTF-8, ≤ 5 MB). Returns `202 {run_id, status, status_url}` |
| `GET` | `/insights/{run_id}` | Returns `status`: `pending` → `running` → `completed` / `failed`. Includes `result` once completed, or `error` if failed |
| `GET` | `/health` | Liveness check |

Interactive docs are served at `/docs`. With the app running on Kubernetes (or
Docker Compose):

Windows (PowerShell):

```powershell
$run = curl.exe -s -F "file=@sample.txt" http://localhost:8000/upload | ConvertFrom-Json
$run    # run_id, status, status_url
Invoke-RestMethod "http://localhost:8000/insights/$($run.run_id)"
```

Use `curl.exe`, not `curl`: in Windows PowerShell, `curl` is an alias for
`Invoke-WebRequest`, which doesn't accept `-F`.

macOS (zsh/bash):

```bash
run_id=$(curl -s -F "file=@sample.txt" http://localhost:8000/upload | python3 -c "import sys, json; print(json.load(sys.stdin)['run_id'])")
curl -s "http://localhost:8000/insights/$run_id" | python3 -m json.tool
```

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
| `TEXTLENS_API_URL` | `http://localhost:8000` | Base URL of the API that nginx (or the Vite dev server) proxies `/api/*` to |

The dashboard's source is in `frontend/` (Vite + React + TypeScript); its styles
are in `frontend/src/styles.css` and the nginx config in
`frontend/nginx.conf.template`.
On Kubernetes, the values are set in the `env:` sections of `k8s/deployment.yaml`.

## Alternative: Docker Compose

Runs the same three services without Kubernetes. Use one or the other, not
both: Compose starts its own Redis and API, and both setups use ports 8000 and
8501 on your machine.

```shell
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

Create and activate a virtual environment.

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate
```

If `Activate.ps1` is blocked by the execution policy, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

macOS (zsh/bash):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Then, in either shell:

```shell
pip install -r requirements-dev.txt
docker compose up -d redis          # Redis on localhost:6379
uvicorn main:app --reload           # API on localhost:8000
```

Run the tests (they use in-memory fakeredis, so Redis isn't needed):

```shell
pytest -q
```

Run the dashboard against the local API, in a second terminal. It needs
Node.js 20.19+ or 22.12+ (Vite 8 needs one of these):

```shell
cd frontend
npm install
npm run dev                         # opens on localhost:8501
```

The Vite dev server proxies `/api/*` to `TEXTLENS_API_URL` (default
`http://localhost:8000`), so set that variable only when the API runs somewhere
else. `npm run build` type-checks and writes the production bundle to
`frontend/dist/`.

If the Kubernetes deployment is running, it already holds ports 8000 and 8501.
Remove it first with `kubectl delete namespace textlens`.
