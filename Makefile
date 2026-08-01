.PHONY: bootstrap format lint typecheck test test-integration test-faults audit package verify-package ci

bootstrap:
	uv sync --all-groups

format:
	uv run ruff format src tests scripts

lint:
	uv run ruff format --check src tests scripts
	uv run ruff check src tests scripts

typecheck:
	uv run mypy

test:
	QT_QPA_PLATFORM=offscreen uv run pytest tests/unit tests/contract

test-integration:
	# Phase 1 has no integration tests; preserve all failures except pytest's empty-suite status.
	QT_QPA_PLATFORM=offscreen uv run pytest --no-cov tests/integration || test $$? -eq 5

test-faults:
	# Phase 1 has no fault-injection tests; preserve all failures except pytest's empty-suite status.
	QT_QPA_PLATFORM=offscreen uv run pytest --no-cov tests/fault_injection || test $$? -eq 5

audit:
	uv export --all-groups --no-hashes --no-emit-project --output-file /tmp/usb-cctv-recorder-audit.txt
	uv run pip-audit --strict --requirement /tmp/usb-cctv-recorder-audit.txt

package:
	uv build

verify-package: package
	uv run python -m zipfile -t dist/*.whl

ci: lint typecheck test test-integration test-faults audit package verify-package
