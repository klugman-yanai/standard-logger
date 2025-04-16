# __init__.py
"""
Kardome Standard Logger Package.

Provides a configurable logging setup integrating standard logging, Rich, and Loguru.
Offers enhanced logging features like panels, progress bars, and rules, with
ASCII fallbacks.

Main entry points:
- setup_logging: Function to initialize and configure the logging system.
- LoggerConfig: Dataclass for specifying configuration options.
- StandardLogger: The custom logger class (useful for type hints/isinstance).
- LoggerSetupError: Custom exception raised on critical setup failures.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 [Yanai Klugman/Kardome]

import importlib.metadata

# --- Public API Imports ---
# Bring the essential user-facing components directly into the package namespace
# This allows users to write `from kardome_logger import setup_logging` etc.
from .logger import LoggerConfig, LoggerSetupError, StandardLogger, setup_logging

# --- Versioning ---
# Standard way to define package version using installed package metadata
# Falls back gracefully if the package is not installed (e.g., during development/testing)
try:
    # __name__ will be 'kardome_logger' when this package is imported
    # importlib.metadata looks up the version associated with this installed package name.
    __version__ = importlib.metadata.version(__name__)
except importlib.metadata.PackageNotFoundError:
    # Package is not installed (e.g., running directly from source, tests)
    __version__ = "0.0.0"  # Or "unknown", common fallback

# --- __all__ Definition ---
# Explicitly defines the public API exposed by `from kardome_logger import *`
# While `import *` is discouraged, defining __all__ is good practice for libraries:
# 1. Documents the intended public interface.
# 2. Prevents accidental import of internal names or modules (like importlib).
# 3. Helps static analysis tools understand the public API.
__all__ = [
    "LoggerConfig",
    "LoggerSetupError",
    "StandardLogger",
    "__version__",
    "setup_logging",
]
