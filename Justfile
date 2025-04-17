#!/usr/bin/env just --justfile --working-directory .

# --- Shell Configuration ---
# For PowerShell 7 on Windows:
set shell := ["pwsh", "-Command"]
# For bash/sh on Linux/macOS:
# set shell := ["bash", "-c"]

# --- Default Task ---
# List available tasks by default when running `just`
default: list

# --- Variables ---
VENV_DIR := ".venv"
SRC_DIR := "src"
PACKAGE_NAME := "standard_logger"


# --- Environment Setup ---

# Setup: Create venv and install dependencies from pyproject.toml
setup:
    @echo "--- Setting up virtual environment using uv ---"
    @# Create venv if it doesn't exist (using pwsh syntax via explicit shell)
    @if (-not (Test-Path "{{VENV_DIR}}")) { uv venv }
    @echo "--- Syncing dependencies from pyproject.toml ---"
    uv pip sync pyproject.toml

# Install: Alias for setup
install: setup

# Update: Sync dependencies based on pyproject.toml
update:
    @echo "--- Updating dependencies ---"
    uv pip sync pyproject.toml

# Optional: Task to install dev extras explicitly if needed
# install-dev:
#    @echo "--- Installing development extras ---"
#    uv pip install .[dev,test] # Adjust extras as defined in pyproject.toml


# --- Quality & Testing ---

# Lint: Run Ruff linter
lint:
    @echo "--- Running Ruff linter ---"
    @uv run ruff check {{SRC_DIR}} examples tests

# Format-Check: Check formatting with Ruff
format-check:
    @echo "--- Checking formatting with Ruff ---"
    @uv run ruff format --check {{SRC_DIR}} examples tests

# Format: Apply formatting with Ruff
format:
    @echo "--- Formatting code with Ruff ---"
    @uv run ruff format {{SRC_DIR}} examples tests

# Type-Check: Run Pyright type checker
type-check:
    @echo "--- Running Pyright type checker ---"
    @uv run pyright

# Check: Run all static checks
check: format-check lint type-check

# Test: Run tests using pytest
test:
    @echo "--- Running tests with pytest ---"
    @uv run pytest tests/

# Coverage: Run tests and generate coverage report
coverage:
    @echo "--- Running tests with coverage ---"
    @uv run pytest --cov={{PACKAGE_NAME}} --cov-report=term-missing tests/
    @echo "--- Generating HTML coverage report ---"
    @uv run coverage html


# --- Development ---

# Demo: Run the example demo script
demo:
    @echo "--- Running examples/demo.py ---"
    @uv run python -m examples.demo


# --- Build & Clean ---

# Clean: Remove build artifacts, caches using git clean
clean:
    @echo "--- Cleaning build artifacts and caches ---"
    @# Use git clean -fdX (force, directories, ignore rules respecting .gitignore)
    @git clean -fdX dist build {{SRC_DIR}}/*.egg-info htmlcov .pytest_cache .ruff_cache .pyright_cache
    @echo "Clean finished. Virtual environment '{{VENV_DIR}}' not removed."

# Clean-All: Clean build artifacts AND the virtual environment
clean-all: clean
    @echo "--- Removing virtual environment ---"
    @# Use PowerShell syntax via explicit shell
    @if (Test-Path "{{VENV_DIR}}") { Remove-Item -Recurse -Force "{{VENV_DIR}}" }
    @echo "Virtual environment '{{VENV_DIR}}' removed."

# Build: Clean and build wheel/sdist using uv
build: clean
    @echo "--- Building package (wheel and sdist) using uv ---"
    @uv build
    @echo "--- Contents of dist/ directory: ---"
    @# Use PowerShell Get-ChildItem (ls is an alias)
    @Get-ChildItem -Path dist | Format-Table -AutoSize


# --- Release & Publish ---

# Release: Tag version, push tag, build artifacts
release version:
    @echo "--- Preparing release: {{version}} ---"
    @# Check for clean working directory
    @git diff --quiet --exit-code; if ($LASTEXITCODE -ne 0) { Write-Error "Error: Working directory is not clean."; exit 1 }
    @# Check if version tag already exists
    @git rev-parse {{version}} -q --verify > $null; if ($LASTEXITCODE -eq 0) { Write-Error "Error: Tag '{{version}}' already exists."; exit 1 }
    @echo "--- Tagging version {{version}} ---"
    @git tag {{version}} -m "Release version {{version}}"
    @echo "--- Pushing tag {{version}} to origin ---"
    @git push origin {{version}}
    @just build
    @echo "--- Release {{version}} tagged and built successfully ---"

# Publish: Upload package artifacts to PyPI
# Requires twine (`uv pip install twine`) and PyPI credentials configured
publish: build
    @echo "--- Publishing package to PyPI ---"
    @# Check if twine is installed
    @uv run python -m twine --version *>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { Write-Error "Error: twine not found. Install with 'uv pip install twine'"; exit 1 }
    @uv run python -m twine upload dist/*
    @echo "--- Publishing attempted. Check PyPI. ---"

# Publish-Test: Upload package artifacts to TestPyPI
publish-test: build
    @echo "--- Publishing package to TestPyPI ---"
    @# Check if twine is installed
    @uv run python -m twine --version *>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { Write-Error "Error: twine not found. Install with 'uv pip install twine'"; exit 1 }
    @uv run python -m twine upload --repository testpypi dist/*
    @echo "--- Publishing to TestPyPI attempted. Check test.pypi.org. ---"


# --- Help / List Tasks ---

# List: List available tasks (Default action)
list:
    @just --list

# Help: Show detailed help for tasks
help:
    @just --list --unsorted --verbose
