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

# LensGuard on Amazon EKS with Elastic Beanstalk Cluster Mode

LensGuard is a read-only Docker and Kubernetes debugging dashboard. It monitors pods and nodes, detects risks, deduplicates alerts, imports security scan reports (Trivy, Docker Scout, SonarQube), and stores history in MySQL. This README explains how it is deployed on **AWS Elastic Beanstalk Cluster Mode**, which runs applications as workloads on an Amazon EKS cluster that Elastic Beanstalk creates and manages.

> Items marked **[fill in]** are specific to your account or choices and should be completed before publishing.

---

## Contents

1. [What is Cluster Mode](#what-is-cluster-mode)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Deploy](#deploy)
5. [Configuration](#configuration)
6. [Database (RDS MySQL)](#database-rds-mysql)
7. [Verify the deployment](#verify-the-deployment)
8. [CI/CD](#cicd)
9. [Security notes](#security-notes)
10. [Cost notes](#cost-notes)
11. [Troubleshooting](#troubleshooting)
12. [References](#references)

---

## What is Cluster Mode

Elastic Beanstalk (announced September 17, 2026) now has two deployment modes:

| | Standard Mode | Cluster Mode |
|---|---|---|
| Runs on | A dedicated environment per application | A shared EKS cluster with several applications |
| Managed by | Elastic Beanstalk | Elastic Beanstalk creates and operates the cluster |
| Nodes | EC2 instances in the environment | EKS Auto Mode nodes |
| Deployments | Classic deployment policies | Kubernetes rolling updates |
| Cluster access | n/a | A normal EKS cluster, so `kubectl` works, but cluster settings are limited to what Elastic Beanstalk exposes |

In this project, LensGuard runs as a deployment in an Elastic Beanstalk-created namespace (`eb-lensguard-dev`), configured through a ConfigMap (`app-configmap`) that Elastic Beanstalk labels as its own.

---

## Architecture

```
GitHub (code) ──► GitHub Actions ──► Docker build ──► Trivy scan
                                          │                │
                                          ▼                ▼
                              Elastic Beanstalk      POST /api/reports/import
                              (Cluster Mode, EKS)           │
                                          │                 │
                         ┌────────────────┴─────────────────┴──────┐
                         │  EKS cluster (Auto Mode nodes)          │
                         │  namespace: eb-lensguard-dev            │
                         │  deployment: deployment-lensguard-dev   │
                         │   FastAPI backend + dashboard (port 8000)│
                         │   read-only collector (list/get only)   │
                         └───────────────────┬─────────────────────┘
                                             │ private network
                                             ▼
                                  Amazon RDS for MySQL
                          (logs, reports, metrics, alert state)
```

| Component | Location in repo |
|---|---|
| CI pipeline (tests, build, Trivy, optional upload) | `.github/workflows/ci.yml` |
| Report import (Trivy, Docker Scout, SonarQube) | `backend/app/reports.py` |
| Read-only collector | `backend/app/collector.py`, `k8s/rbac.yaml` |
| Rules, service, API | `backend/app/rules.py`, `service.py`, `main.py` |
| Data models (MySQL) | `backend/app/models.py` |
| Alert engine (detect, deduplicate, resolve) | `backend/app/alerts.py` |
| Slack and email notifications (optional) | `backend/app/notify.py` |
| AI explanations (optional, opt-in) | `backend/app/ai.py` |
| Dashboard | `backend/app/static/index.html` |

---

## Prerequisites

- An AWS account and a region where Elastic Beanstalk is available. Cluster Mode is offered in the commercial regions where Elastic Beanstalk runs. This project uses **us-west-2**.
- AWS CLI v2 configured with permissions for Elastic Beanstalk, EKS, IAM, and RDS.
- `kubectl` installed locally.
- An application source repository with a `Dockerfile` **[fill in: or source-only deploy]**.
- An RDS MySQL instance in a VPC the cluster can reach (see [Database](#database-rds-mysql)).
- Permission to create IAM roles that Elastic Beanstalk uses for the cluster and nodes. If the console asks for a cluster role, it needs a trust policy for the EKS service.

---

## Deploy

### Option A: Console

1. Open the **Elastic Beanstalk** console and choose **Create environment**.
2. Select **Cluster Mode**.
3. Create or pick the application (`lensguard`) and the environment name **[fill in]**.
4. Provide the application source (a ZIP or a container image reference) **[fill in]**.
5. Choose the VPC and subnets. Use subnets that can route to the RDS instance.
6. Add environment properties (see [Configuration](#configuration)).
7. Review and create. Elastic Beanstalk creates the EKS cluster, node pool, and add-ons if they do not exist yet, then deploys the application.

### Option B: AWS CLI

The environment tier for Cluster Mode is `Name=Cluster,Type=EKS`:

```bash
aws elasticbeanstalk create-environment \
  --region us-west-2 \
  --application-name lensguard \
  --environment-name lensguard-dev \
  --tier Name=Cluster,Type=EKS
  # add the remaining options your setup needs, see the Developer Guide
```

The full set of parameters (source bundle, roles, networking) is in the Elastic Beanstalk Developer Guide linked under [References](#references). Record the exact command you used here **[fill in]**.

### Option C: GitHub Actions

Elastic Beanstalk provides a GitHub Action that deploys directly from a repository as part of CI/CD. See [CI/CD](#cicd).

---

## Configuration

LensGuard reads its settings from environment variables, delivered through the `app-configmap` ConfigMap:

| Variable | Purpose | Example |
|---|---|---|
| `PORT` | HTTP port | `8000` |
| `COLLECT_INTERVAL` | Seconds between cluster collection cycles | `30` |
| `CPU_ALERT_PCT` | CPU alert threshold (%) | `85` |
| `MEM_ALERT_PCT` | Memory alert threshold (%) | `85` |
| `IGNORED_NAMESPACES` | Namespaces to skip | `kube-system,local-path-storage` |
| `DATABASE_URL` | SQLAlchemy URL for MySQL | see below |
| `MYSQL_HOST`, `MYSQL_PORT` | Database host and port | RDS endpoint, `3306` |
| `NOTIFY_MIN_SEVERITY` | Lowest severity that notifies | `warning` |
| `SLACK_WEBHOOK_URL` | Optional Slack alerts | empty |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `EMAIL_FROM`, `EMAIL_TO` | Optional email alerts | empty |
| `OPENAI_ENABLED`, `OPENAI_MODEL` | Optional AI explanations (opt-in) | `false`, `gpt-4o-mini` |

`DATABASE_URL` format:

```
mysql+pymysql://<user>:<password>@<rds-endpoint>:3306/lensguard
```

**Do not commit real values.** Use placeholders in the repository and see [Security notes](#security-notes) for moving the password into a secret.

---

## Database (RDS MySQL)

LensGuard stores logs, imported reports, metrics, and alert state in MySQL on a **private** RDS instance (not publicly accessible).

Requirements:
- The RDS instance and the EKS cluster must share network reachability (same VPC, or peering).
- The RDS security group must allow inbound TCP **3306** from the cluster's node or pod security group.
- A database named `lensguard` and a dedicated user with access to it.

Because the instance is private, it is reachable from inside the cluster but not from a laptop on the internet. To inspect it, run a temporary client pod:

```bash
kubectl run mysql-client -n eb-lensguard-dev --image=mysql:8 --restart=Never -- sleep 3600
kubectl wait --for=condition=Ready pod/mysql-client -n eb-lensguard-dev --timeout=120s

kubectl exec -it mysql-client -n eb-lensguard-dev -- \
  mysql --connect-timeout=10 -h <rds-endpoint> -u <user> -p lensguard
```

Enter the password at the prompt. Then:

```sql
SHOW TABLES;
SELECT table_name, table_rows
FROM information_schema.tables WHERE table_schema = DATABASE();
SELECT NOW();
```

Clean up when finished:

```bash
kubectl delete pod mysql-client -n eb-lensguard-dev
```

---

## Verify the deployment

Point `kubectl` at the cluster Elastic Beanstalk created **[fill in: cluster name]**:

```bash
aws eks update-kubeconfig --region us-west-2 --name <cluster-name>
kubectl get pods -n eb-lensguard-dev
kubectl get deploy -n eb-lensguard-dev
kubectl logs deploy/deployment-lensguard-dev -n eb-lensguard-dev --tail=50
```

Check the API through a port-forward:

```bash
kubectl port-forward -n eb-lensguard-dev deploy/deployment-lensguard-dev 8000:8000
curl -s localhost:8000/api/health
curl -s "localhost:8000/api/metrics?minutes=60" | head -c 500
```

Confirm data is stored: count rows in the metrics table, wait one collection interval (30 seconds by default), and count again. A rising count means the app is writing to RDS.

Expected dashboard behavior: pods, nodes, cluster CPU and memory, open alerts, and imported security reports all load, and demo workloads in `lensguard-demo` appear as failing (`ErrImagePull`, `CrashLoopBackOff`, `Pending`).

---

## CI/CD

The pipeline in `.github/workflows/ci.yml`:

1. Runs tests.
2. Builds the Docker image.
3. Scans it with Trivy.
4. Optionally uploads the report to LensGuard through `POST /api/reports/import`.

Deployment to Elastic Beanstalk can be added with the Elastic Beanstalk GitHub Action, which deploys from the repository on each merge **[fill in: workflow snippet once added]**. Deployments in Cluster Mode are Kubernetes rolling updates (by default, one extra pod at a time and no unavailable pods), so a bad release does not take down the running version if readiness checks fail.

---

## Security notes

- **Read-only by design.** The collector uses list and get calls only, limited by `k8s/rbac.yaml`. LensGuard never changes the cluster. Remediation is manual.
- **Keep secrets out of ConfigMaps.** ConfigMaps are stored in plain text. Put the database password in a Kubernetes Secret or AWS Secrets Manager (Cluster Mode supports Secrets Manager integration) and build `DATABASE_URL` from it. Rotate any password that has been displayed in logs, screenshots, or chat.
- **Private database.** Keep RDS non-public and restrict port 3306 to the cluster's security group.
- **Do not expose admin tools.** If you use Adminer or similar, reach it with `kubectl port-forward` only, and delete it afterwards.
- **Protect the dashboard.** The dashboard can be reached by internet crawlers if exposed publicly. Put it behind authentication or an allow-list before sharing the URL.
- **Optional integrations are opt-in.** OpenAI explanations are disabled by default (`OPENAI_ENABLED=false`).

---

## Cost notes

Cluster Mode has no extra Elastic Beanstalk charge, but you pay for the resources it creates:

- The EKS cluster (hourly per-cluster fee).
- EKS Auto Mode charges on the nodes Elastic Beanstalk provisions.
- EC2 compute, the RDS instance, and any load balancers or data transfer.

Cluster Mode is not eligible for the AWS Free Tier. Delete the environment and the RDS instance when the demo or hackathon is over to stop charges:

```bash
aws elasticbeanstalk terminate-environment --region us-west-2 --environment-name lensguard-dev
```

Check the Elastic Beanstalk and EKS pricing pages for current rates.

---

## Troubleshooting

| Symptom | Likely cause and check |
|---|---|
| `mysql` times out from your laptop | The RDS is private. Connect from inside the cluster or through an SSM tunnel. |
| `ERROR 1045 Access denied (using password: NO)` | The password was not sent. Use `kubectl exec -it` into a running client pod and type the password at the prompt. |
| `ERROR 1045 Access denied (using password: YES)` | The password does not match the RDS user. Check the secret or ConfigMap value. |
| Pods stuck in `Pending` | No node satisfies the request, selector, or taint. Run `kubectl describe pod`. |
| `ImagePullBackOff` or `ErrImagePull` | Wrong image tag or registry permissions. |
| `CrashLoopBackOff` | Read `kubectl logs --previous`. Common causes are bad config or an unreachable database. |
| Dashboard loads but no history | App cannot write to MySQL. Check `DATABASE_URL`, security group rules, and pod logs. |
| Cluster settings cannot be changed | In Cluster Mode, Elastic Beanstalk owns the cluster. Use the Elastic Beanstalk API, CLI, or console rather than editing cluster infrastructure directly. |

---

## References

- AWS release note: Elastic Beanstalk Cluster Mode (September 17, 2026)
- AWS What's New: Elastic Beanstalk Cluster Mode
- AWS Elastic Beanstalk Developer Guide, Cluster Mode concepts
- Amazon EKS Auto Mode documentation
- Trivy, Docker Scout, and SonarQube documentation for report formats