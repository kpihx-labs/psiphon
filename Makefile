.DEFAULT_GOAL := help
SHELL := /bin/sh

PKG_NAME     := psiphon
PKG_DIR_NAME := psiphon
PKG_DIR      := src/$(PKG_DIR_NAME)
VERSION      := $(shell grep -m 1 version pyproject.toml | tr -s ' ' | tr -d '"' | tr -d "'" | cut -d= -f2 | xargs)

UV     := $(shell command -v uv 2>/dev/null || echo uv)
PYTHON := $(UV) run --offline --no-sync python

PY_FILES := $(wildcard $(PKG_DIR)/*.py)

.PHONY: help sync check smoke test-live uv-install uv-link uv-uninstall build publish uv-build uv-publish push push-tags status log release

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

# ── Quality ──────────────────────────────────────────────────────────────────

sync:  ## Synchronize the source checkout environment
	@$(UV) sync --offline --frozen

check: smoke build  ## Offline lint, format, types, tests and installed-wheel smoke
	@ruff check src tests
	@ruff format --check src tests
	@$(PYTHON) -m py_compile $(PY_FILES)
	@pyright --pythonpath .venv/bin/python $(PKG_DIR)
	@$(UV) run --offline --no-sync pytest -q -m 'not live'

test-live: sync  ## Explicit unprivileged proxy survey (NOT packet-tunnel validation)
	@$(UV) run --offline --no-sync psiphon bench --all --proxy

smoke: sync  ## Import smoke test for this checkout
	@$(PYTHON) -c "import $(PKG_DIR_NAME)" || (echo "❌ smoke test failed"; exit 1)
	@echo "✅ smoke test passed"

# ── Install / Uninstall (uv tool) ────────────────────────────────────────────

uv-install: build  ## Install a built wheel locally; engine setup is a separate explicit command
	@$(UV) tool install --offline dist/$(PKG_NAME)-$(VERSION)-py3-none-any.whl --force

uv-link:  ## Install editable (dev) — CLI always uses the current checkout
	@$(UV) tool install --editable . --force
	@echo "✅ $(PKG_NAME) linked (editable)"

uv-uninstall:  ## Uninstall the uv tool
	@$(UV) tool uninstall $(PKG_NAME)
	@echo "✅ $(PKG_NAME) uninstalled"

# ── Build / Publish ──────────────────────────────────────────────────────────

build:  ## Build sdist + wheel offline (package includes defaults and upstream license)
	@echo "🏗️  Building $(PKG_NAME) v$(VERSION)..."
	@$(UV) build --offline

uv-build: build  ## Compatibility alias for build

publish: check  ## Explicit publish, run only inside an approved with-env tmux pane
	@echo "🚀 Publishing v$(VERSION) to PyPI..."
	@$(UV) publish dist/$(PKG_NAME)-$(VERSION)-py3-none-any.whl dist/$(PKG_NAME)-$(VERSION).tar.gz

uv-publish: publish  ## Compatibility alias for publish

# ── Git ───────────────────────────────────────────────────────────────────────

push:  ## Push current branch to all remotes
	@set -e; branch="$$(git branch --show-current)"; \
	for remote in github gitlab; do \
		url="$$(git remote get-url "$$remote")"; \
		case "$$url" in git@*:*|ssh://*) ;; *) echo "SSH remote required: $$remote"; exit 1;; esac; \
	done; \
	for remote in github gitlab; do \
		echo "==> pushing $$branch to $$remote"; \
		git push "$$remote" "$$branch"; \
	done

push-tags:  ## Push all tags to all remotes
	@set -e; for remote in github gitlab; do git push "$$remote" --tags; done

status:  ## git status --short
	@git status --short

log:  ## Last 10 commits oneline
	@git log --oneline -10

release: check push uv-publish push-tags  ## Full release: check → push → publish → push tags
