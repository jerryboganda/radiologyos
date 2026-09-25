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
	gh workflow run verify-production-rls.yml --ref main; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; $runId = gh run list --workflow verify-production-rls.yml --limit 1 --json databaseId --jq '.[0].databaseId'; if (-not $runId) { Write-Error 'Unable to find the dispatched production RLS run'; exit 1 }; gh run watch $runId --exit-status

types:
	python scripts/generate_openapi_types.py

ci:
	$ref = git rev-parse --abbrev-ref HEAD; $sha = git rev-parse HEAD; $started = [DateTime]::UtcNow; gh workflow run ci.yml --ref $ref; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; $runId = $null; for ($attempt = 0; $attempt -lt 30 -and -not $runId; $attempt++) { Start-Sleep -Seconds 2; $runs = gh run list --workflow ci.yml --commit $sha --limit 5 --json databaseId,createdAt | ConvertFrom-Json; $run = $runs | Where-Object { [DateTime]$_.createdAt -ge $started.AddSeconds(-5) } | Select-Object -First 1; if ($run) { $runId = $run.databaseId } }; if (-not $runId) { Write-Error 'Unable to find the dispatched CI run'; exit 1 }; gh run watch $runId --exit-status

security-scan: ci
