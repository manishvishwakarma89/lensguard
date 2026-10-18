# LensGuard

**AI-powered Docker & Kubernetes debugging assistant.**
Monitor clusters. Detect risks. Debug smarter.
Read-only diagnostics · Manual remediation · Configurable alerts

## How it maps to the architecture diagram

| Diagram block | Where it lives |
|---|---|
| Code & CI/CD (GitHub Actions → Docker Build → Security reports) | `.github/workflows/ci.yml` (tests, build, Trivy scan, optional upload to LensGuard) |
| Import reports (Trivy, Docker Scout, SonarQube) | `backend/app/reports.py`, `POST /api/reports/import` |
| Local Kubernetes (kind / minikube) + read-only collector | `backend/app/collector.py` (list/get only), `k8s/rbac.yaml` |
| Python + FastAPI: analyze, evaluate rules, serve APIs | `backend/app/rules.py`, `service.py`, `main.py` |
| MySQL: logs, reports, metrics, alert state | `backend/app/models.py` |
| Alert Engine: detect, deduplicate, resolve | `backend/app/alerts.py` |
| Slack & Email (optional) | `backend/app/notify.py` |
| AI Explanations (optional, opt-in, OpenAI) | `backend/app/ai.py` |
| Monitoring Dashboard (pods, nodes, cluster metrics) | `backend/app/static/index.html` (served at `/`) |

## Quick start (kind or minikube)

```bash
# 1. a local cluster with metrics-server (metrics-server is optional but gives CPU/memory charts)
kind create cluster --name lensguard
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deploy metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'   # local clusters only

# 2. MySQL
cp .env.example .env
docker compose up -d db

# 3. API + dashboard (run on the host so it can reach the kind/minikube API server)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```

Try it with deliberately broken workloads:

```bash
kubectl apply -f k8s/demo-broken.yaml
```

Within ~30 s the dashboard shows a CrashLoopBackOff, an ImagePullBackOff and a Pending pod, each with a log
tail, the related events and a manual next step. Delete the namespace and the alerts resolve themselves:

```bash
kubectl delete ns lensguard-demo
```

Import the sample security report: `curl -F file=@samples/trivy-sample.json http://localhost:8000/api/reports/import`

### Full Docker Compose
`docker compose up --build` runs MySQL and the API in containers. A kind kubeconfig points at `127.0.0.1`,
which a container cannot reach, so use this for remote clusters or export an internal one
(`kind get kubeconfig --internal`, then attach the API container to the `kind` Docker network).

### Running inside the cluster
Apply `k8s/rbac.yaml` and run the API image with `serviceAccountName: lensguard`. The role only grants
`get`/`list` on pods, pod logs, nodes, events and `metrics.k8s.io`.

## Detection rules

CrashLoopBackOff, ImagePullBackOff / ErrImagePull, OOMKilled, CreateContainerConfigError, Evicted, Pending longer than
2 minutes, failed pods, frequent restarts, NodeNotReady, high node CPU / memory, and CRITICAL / HIGH vulnerabilities
from imported reports. Thresholds are set in `.env`. Add a rule in `rules.py`: a function that returns finding dicts.

## Alert lifecycle

A finding opens an alert, keeps updating the same alert while it persists (no repeat notifications), resolves when
the problem disappears, and reopens if it comes back. Slack and email only fire on those transitions, and a burst of
more than five changes is sent as one summary.

## API

| Endpoint | Purpose |
|---|---|
| `GET /` | dashboard |
| `GET /api/health` | collector status, AI and notification flags |
| `GET /api/overview`, `/api/pods`, `/api/nodes`, `/api/metrics?minutes=60` | dashboard data |
| `GET /api/alerts?status=open` | alerts |
| `POST /api/alerts/{id}/explain` | AI explanation (only if enabled) |
| `GET /api/logs?resource=pod/ns/name` | stored log tails and events |
| `POST /api/reports/import` | multipart `file` (Trivy / Scout SARIF / SonarQube JSON) |
| `GET /api/reports`, `/api/reports/{id}` | report summaries and findings |
| `POST /api/collect` | run a collection now |
| `/docs` | interactive OpenAPI docs |

## Privacy and safety

- The collector never writes to the cluster, and LensGuard never applies fixes. It only suggests commands.
- AI explanations are off by default. When enabled, nothing is sent automatically: only the alert you click
  "Explain with AI" on is sent, with obvious secrets (passwords, tokens, bearer headers) redacted from log text.
  Redaction is best-effort, so review your logs before enabling it on sensitive clusters.
- There is no authentication on the API yet. Do not expose port 8000 beyond localhost.

## Tests

```bash
cd backend && pytest
```

## Ideas for next steps

Auth (OAuth proxy or API key), Alembic migrations, per-namespace rules, Docker container diagnostics via the Docker
socket (read-only), a Prometheus `/metrics` endpoint, and a Helm chart.
