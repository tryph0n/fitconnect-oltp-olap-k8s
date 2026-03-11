# FitConnect Pipeline

OLTP-to-OLAP pipeline for a fitness application. Extracts data from PostgreSQL (transactional source), loads it into ClickHouse (analytical destination) using dlt, and runs on K3s.

## Architecture

- **PostgreSQL 16** -- OLTP source database with WAL logical replication enabled for CDC.
- **dlt** -- Extract-Load tool. Reads from PostgreSQL (via `sql_database` source) and writes to ClickHouse.
- **ClickHouse** -- OLAP destination. Column-oriented storage for analytical queries. Optional S3 backend for persistent storage.
- **K3s** -- Lightweight Kubernetes distribution. All components run as StatefulSets and Jobs in the `fitconnect` namespace.

Data flow: CSV files --> PostgreSQL (seed) --> dlt (extract-load) --> ClickHouse.

## Prerequisites

- K3s (or any Kubernetes cluster)
- kubectl
- Docker (to build/push the image)
- uv (for local development)

## Quick Start

Deploy in this exact order:

```bash
# 0. Create .env from the example (default values work out of the box)
cp .env.example .env

# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Create secret from .env file
kubectl create secret generic fitconnect-env --from-env-file=.env -n fitconnect

# 3. Deploy PostgreSQL
kubectl apply -f k8s/postgres/service.yaml
kubectl apply -f k8s/postgres/statefulset.yaml

# 4. Deploy ClickHouse
kubectl apply -f k8s/clickhouse/service.yaml
kubectl apply -f k8s/clickhouse/statefulset.yaml

# 5. Wait for pods to be ready
kubectl wait --for=condition=ready pod/postgres-0 -n fitconnect --timeout=60s
kubectl wait --for=condition=ready pod/clickhouse-0 -n fitconnect --timeout=60s

# 6. Run seed (load CSV -> PostgreSQL)
kubectl apply -f k8s/pipeline/job-seed.yaml
kubectl wait --for=condition=complete job/fitconnect-seed -n fitconnect --timeout=120s

# 7. Configure CDC
kubectl apply -f k8s/pipeline/job-cdc.yaml
kubectl wait --for=condition=complete job/fitconnect-cdc -n fitconnect --timeout=120s

# 8. Run pipeline (PostgreSQL -> ClickHouse)
kubectl apply -f k8s/pipeline/job-pipeline.yaml
kubectl wait --for=condition=complete job/fitconnect-pipeline -n fitconnect --timeout=120s
```

## Teardown

Delete everything and start fresh:

```bash
# Delete all resources in the namespace (jobs, pods, services, secrets, PVCs)
kubectl delete namespace fitconnect

# Wait for namespace to be fully removed
kubectl wait --for=delete namespace/fitconnect --timeout=120s
```

After teardown, re-run the Quick Start steps to redeploy from scratch.

## Building the Docker Image

For those who want to rebuild the image instead of using `sambot961/fitconnect-pipeline:latest`:

```bash
docker build -t <your-dockerhub>/fitconnect-pipeline:latest .
docker push <your-dockerhub>/fitconnect-pipeline:latest
```

Update the image reference in `k8s/pipeline/job-seed.yaml`, `k8s/pipeline/job-cdc.yaml`, and `k8s/pipeline/job-pipeline.yaml` accordingly.

## Local Development

```bash
uv sync
cp .env.example .env
# Default values work as-is for K3s; adjust hosts/passwords if needed
uv run fc-seed
uv run fc-cdc
uv run fc-pipeline
```

## Verification

```bash
# Row counts (dlt prefixes table names with dataset name)
kubectl exec -n fitconnect clickhouse-0 -- clickhouse-client --password changeme \
  --query "
    SELECT 'user', count(*) FROM fitconnect.fitconnect___user
    UNION ALL SELECT 'profile', count(*) FROM fitconnect.fitconnect___profile
    UNION ALL SELECT 'exercise', count(*) FROM fitconnect.fitconnect___exercise
    UNION ALL SELECT 'workout', count(*) FROM fitconnect.fitconnect___workout
    UNION ALL SELECT 'workout_exercise', count(*) FROM fitconnect.fitconnect___workout_exercise
  "
# Expected: user 10, profile 10, exercise 10, workout 104, workout_exercise 426
```

## Security

The default values in `.env.example` work out of the box for a quick demo. For production, change the passwords in your `.env` file. Never commit `.env` to version control.
