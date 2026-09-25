SHELL := powershell.exe

.PHONY: up down check test typecheck lint migrate rls types security-scan ci

up:
	docker compose up -d
	docker compose ps

down:
	docker compose down

check:
	python -m ruff check apps packages evals scripts
	python -m mypy apps/api/app apps/worker/app
	python -m pytest -q apps/api/tests evals/checks/test_scaffolding.py evals/checks/test_preview_determinism.py
	npm --prefix apps/web run check
	npm --prefix apps/web test

test:
	python -m pytest -q

typecheck:
	python -m mypy apps/api/app apps/worker/app
	npm --prefix apps/web run check

lint:
	python -m ruff check apps packages
	npm --prefix apps/web run lint

migrate:
	python -m alembic -c alembic.ini upgrade head

rls:
	$names = @('RADBRAIN_STAGING_REVISION', 'RADBRAIN_STAGING_DEPLOYMENT_ID', 'RADBRAIN_STAGING_SECURITY_APPROVAL_REFERENCE', 'RADBRAIN_STAGING_RELEASE_APPROVAL_REFERENCE', 'RADBRAIN_STAGING_TRACE_REVIEW_REFERENCE'); foreach ($name in $names) { if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) { Write-Error "Missing $name"; exit 1 } }; $started = [DateTime]::UtcNow; gh workflow run m0-staging-rls.yml --ref main -f "revision=$($env:RADBRAIN_STAGING_REVISION)" -f "deployment_id=$($env:RADBRAIN_STAGING_DEPLOYMENT_ID)" -f "security_approval_reference=$($env:RADBRAIN_STAGING_SECURITY_APPROVAL_REFERENCE)" -f "release_approval_reference=$($env:RADBRAIN_STAGING_RELEASE_APPROVAL_REFERENCE)" -f "trace_review_reference=$($env:RADBRAIN_STAGING_TRACE_REVIEW_REFERENCE)"; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; $runId = $null; for ($attempt = 0; $attempt -lt 30 -and -not $runId; $attempt++) { Start-Sleep -Seconds 2; $runs = gh run list --workflow m0-staging-rls.yml --commit $env:RADBRAIN_STAGING_REVISION --limit 5 --json databaseId,createdAt | ConvertFrom-Json; $run = $runs | Where-Object { [DateTime]$_.createdAt -ge $started.AddSeconds(-5) } | Select-Object -First 1; if ($run) { $runId = $run.databaseId } }; if (-not $runId) { Write-Error 'Unable to find the dispatched staging RLS run'; exit 1 }; gh run watch $runId --exit-status

types:
	python scripts/generate_openapi_types.py

ci:
	$ref = git rev-parse --abbrev-ref HEAD; $sha = git rev-parse HEAD; $started = [DateTime]::UtcNow; gh workflow run ci.yml --ref $ref; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; $runId = $null; for ($attempt = 0; $attempt -lt 30 -and -not $runId; $attempt++) { Start-Sleep -Seconds 2; $runs = gh run list --workflow ci.yml --commit $sha --limit 5 --json databaseId,createdAt | ConvertFrom-Json; $run = $runs | Where-Object { [DateTime]$_.createdAt -ge $started.AddSeconds(-5) } | Select-Object -First 1; if ($run) { $runId = $run.databaseId } }; if (-not $runId) { Write-Error 'Unable to find the dispatched CI run'; exit 1 }; gh run watch $runId --exit-status

security-scan: ci
