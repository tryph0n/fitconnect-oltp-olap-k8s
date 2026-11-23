# FitConnect on Kubernetes (k3d, K3s or any cluster in the current kubectl context).
# `make help` lists the targets.

NS := fitconnect
KUBECTL ?= kubectl
TIMEOUT ?= 300s
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
IMAGE ?= ghcr.io/tryph0n/fitconnect-pipeline:$(VERSION)
# S3=moto stores the ClickHouse tables in a local S3 server (moto) instead of the pod volume.
S3 ?=

ifneq ($(filter-out moto,$(S3)),)
$(error S3 must be empty or moto, not "$(S3)")
endif

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
.PHONY: help env up seed cdc-setup pipeline consumer demo-cdc cdc-reset down lint test image

# Runs a Job again from its manifest and waits for it; prints its log.
define run_job
	$(KUBECTL) delete job $(1) -n $(NS) --ignore-not-found
	$(KUBECTL) apply -f k8s/pipeline/$(2)
	$(KUBECTL) wait --for=condition=complete job/$(1) -n $(NS) --timeout=$(TIMEOUT) \
		|| { $(KUBECTL) logs job/$(1) -n $(NS) --tail=50; exit 1; }
	$(KUBECTL) logs job/$(1) -n $(NS) --tail=20
endef

# The setup Job with `--reset`, under another name (used by cdc-reset).
RESET_PATCH := [{"op": "replace", "path": "/metadata/name", "value": "fitconnect-cdc-reset"}, \
	{"op": "add", "path": "/spec/template/spec/containers/0/args", "value": ["--reset"]}]

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

env: ## Write .env from .env.example with random passwords (never overwrites .env)
	@if [ -e .env ]; then echo ".env exists: delete it first to make a new one" >&2; exit 1; fi
	@pg=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
	ch=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
	umask 077; \
	sed -e "s/^PG_PASSWORD=\$$/PG_PASSWORD=$$pg/" -e "s/^POSTGRES_PASSWORD=\$$/POSTGRES_PASSWORD=$$pg/" \
		-e "s/^CH_PASSWORD=\$$/CH_PASSWORD=$$ch/" -e "s/^CLICKHOUSE_PASSWORD=\$$/CLICKHOUSE_PASSWORD=$$ch/" \
		.env.example > .env
	@echo "Wrote .env with new random passwords"

up: ## Deploy the databases, load the snapshot and start the CDC consumer (S3=moto: S3 storage)
	@test -f .env || { echo "No .env: run make env first" >&2; exit 1; }
	@echo "kubectl context: $$($(KUBECTL) config current-context)"
	$(KUBECTL) apply -f k8s/namespace.yaml
	$(KUBECTL) create secret generic fitconnect-env -n $(NS) --from-env-file=.env \
		--dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) apply -f k8s/postgres/service.yaml -f k8s/postgres/statefulset.yaml
ifeq ($(S3),moto)
	$(KUBECTL) apply -f k8s/s3-moto/
	$(KUBECTL) rollout status deployment/moto -n $(NS) --timeout=$(TIMEOUT)
	$(KUBECTL) apply -f k8s/clickhouse/configmap.yaml -f k8s/clickhouse/service.yaml
	$(KUBECTL) patch --local -f k8s/clickhouse/statefulset.yaml \
		--patch-file k8s/clickhouse/s3-patch.yaml -o yaml | $(KUBECTL) apply -f -
else
	$(KUBECTL) apply -f k8s/clickhouse/service.yaml -f k8s/clickhouse/statefulset.yaml
endif
	$(KUBECTL) rollout status statefulset/postgres -n $(NS) --timeout=$(TIMEOUT)
	$(KUBECTL) rollout status statefulset/clickhouse -n $(NS) --timeout=$(TIMEOUT)
	@$(MAKE) --no-print-directory seed cdc-setup pipeline consumer

seed: ## Run the seed Job: CSV files to PostgreSQL (skips tables that have rows)
	$(call run_job,fitconnect-seed,job-seed.yaml)

cdc-setup: ## Run the CDC setup Job: publication, replication slot, ClickHouse tables
	$(call run_job,fitconnect-cdc-setup,job-cdc-setup.yaml)

pipeline: ## Run the snapshot Job: PostgreSQL tables to ClickHouse (once per table)
	$(call run_job,fitconnect-pipeline,job-pipeline.yaml)

consumer: ## Start the CDC consumer Deployment
	$(KUBECTL) apply -f k8s/pipeline/deployment-cdc-consumer.yaml
	$(KUBECTL) rollout status deployment/fitconnect-cdc-consumer -n $(NS) --timeout=$(TIMEOUT)

demo-cdc: ## Change two rows in PostgreSQL and wait until ClickHouse shows them
	NS=$(NS) KUBECTL="$(KUBECTL)" scripts/demo-cdc.sh

cdc-reset: ## Stop the consumer, recreate the slot, empty the ClickHouse CDC tables, load a new snapshot
	$(KUBECTL) scale deployment/fitconnect-cdc-consumer -n $(NS) --replicas=0
	$(KUBECTL) wait --for=delete pod -l app=fitconnect-cdc-consumer -n $(NS) --timeout=$(TIMEOUT)
	$(KUBECTL) delete job fitconnect-cdc-reset -n $(NS) --ignore-not-found
	$(KUBECTL) patch --local -f k8s/pipeline/job-cdc-setup.yaml --type json -o yaml -p '$(RESET_PATCH)' \
		| $(KUBECTL) apply -f -
	$(KUBECTL) wait --for=condition=complete job/fitconnect-cdc-reset -n $(NS) --timeout=$(TIMEOUT) \
		|| { $(KUBECTL) logs job/fitconnect-cdc-reset -n $(NS) --tail=50; exit 1; }
	$(KUBECTL) logs job/fitconnect-cdc-reset -n $(NS) --tail=20
	@$(MAKE) --no-print-directory pipeline
	$(KUBECTL) scale deployment/fitconnect-cdc-consumer -n $(NS) --replicas=1
	$(KUBECTL) rollout status deployment/fitconnect-cdc-consumer -n $(NS) --timeout=$(TIMEOUT)

down: ## Delete the namespace and all its data
	$(KUBECTL) delete namespace $(NS) --ignore-not-found --timeout=$(TIMEOUT)

lint: ## Check the code with ruff
	uv run ruff check .
	uv run ruff format --check .

test: ## Run the unit tests, then the integration tests (needs Docker)
	uv run pytest -q
	uv run pytest -q -m integration

image: ## Build the pipeline image with the tag of the manifests
	docker build -t $(IMAGE) .
