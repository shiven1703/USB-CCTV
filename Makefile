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
	QT_QPA_PLATFORM=offscreen uv run pytest tests/unit tests/contract tests/integration tests/fault_injection

test-integration:
	QT_QPA_PLATFORM=offscreen uv run pytest --no-cov tests/integration || test $$? -eq 5

test-faults:
	QT_QPA_PLATFORM=offscreen uv run pytest --no-cov tests/fault_injection || test $$? -eq 5

audit:
	uv export --all-groups --no-hashes --no-emit-project --output-file /tmp/usb-cctv-recorder-audit.txt
	uv run pip-audit --strict --requirement /tmp/usb-cctv-recorder-audit.txt

package:
	UV_CACHE_DIR=/tmp/usb-cctv-uv-cache uv run python scripts/build_deb.py

verify-package: package
	UV_CACHE_DIR=/tmp/usb-cctv-uv-cache uv run python scripts/verify_package.py dist/usb-cctv-recorder_*_amd64.deb

ci: lint typecheck test test-integration test-faults audit package verify-package
