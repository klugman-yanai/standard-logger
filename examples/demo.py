# ./examples/demo.py
"""
Demonstration script for the kardome_logger package.

Showcases various configurations and features like:
- Different console/file levels and formats (LoggerConfig).
- Rich vs. Loguru console output.
- Enhanced vs. Simple Tracebacks.
- Structured (JSON) vs. Text file logging.
- Custom methods: panel, rule, progress (with ASCII fallbacks).
- Using the 'extra' dictionary.
- Handling exceptions via logger.exception().
- Auto vs. Explicit log file paths.
- Disabling file logging.
"""

import logging
import sys
import time
import traceback  # Needed for manually passing exc_info tuple example

from pathlib import Path
from typing import cast

# --- Assuming standard_logger is installed in the environment (.venv) ---
try:
    from standard_logger import (
        LoggerConfig,
        LoggerSetupError,
        StandardLogger,
        setup_logging,
    )
except ImportError:
    print("Error: standard_logger not found in the current environment.")
    print("Please ensure the package is installed in your virtual environment")
    print("(e.g., using 'uv pip install .' or 'uv pip install -e .')")
    sys.exit(1)

from rich.progress import TaskID
from rich.table import Table
from rich.text import Text

# ==================================================
# Helper Function to Get Logger
# ==================================================


def get_logger(name: str) -> StandardLogger:
    """Gets a logger instance and casts it for type checking custom methods."""
    # Casting is necessary for static type checkers (like Pyright/Mypy)
    # to recognize the custom methods (panel, rule, progress) on the
    # logger instance returned by logging.getLogger().
    return cast(StandardLogger, logging.getLogger(name))


# ==================================================
# Demo Configuration 1: Rich Console, JSON File (Defaults)
# ==================================================
def demo_rich_json():
    """Demonstrates default-like setup: Rich Console, JSON file logging."""
    print("\n" + "=" * 60)
    print(" Demo 1: Rich Console, JSON File Logging ".center(60, "="))
    print("=" * 60)

    # Configure logger: Rich console, JSON file, show locals in tracebacks
    config = LoggerConfig(
        app_name="DemoAppRich",  # Separate log dir for this demo run
        app_author="KardomeDemo",
        console_level=logging.DEBUG,  # Show debug messages on console for demo
        file_level=logging.DEBUG,  # Log debug messages to file
        log_file_serialize=True,  # Explicitly use JSON format (default)
        show_locals_on_exception=True,  # Show local variables in Rich tracebacks
        # log_file_path=Path("./logs/demo1_rich.log"), # Example: Override default path
    )

    try:
        file_enabled, log_path = setup_logging(config)
        print("\nLogging initialized via setup_logging().")
        print(f"  File logging enabled: {file_enabled}")
        if log_path:
            print(f"  Log file path: {log_path}")
        print(f"  Console output via: {'Rich' if config.use_rich_console else 'Loguru'}")
        print(f"  Traceback type: {'Simple' if config.use_simple_tracebacks else 'Enhanced'}")
        print("-" * 60)
    except LoggerSetupError as e:
        print(f"CRITICAL SETUP FAILED for Demo 1: {e}", file=sys.stderr)
        # Attempt to print traceback details if possible
        traceback.print_exc()
        return  # Cannot continue this demo

    # Get a logger instance (casting needed for custom methods)
    log = get_logger("demo.rich_json")

    # --- Standard Logging ---
    print("\n-> Standard Logging Methods:")
    log.debug("This is a debug message.", extra={"user_id": "dbg001", "scope": "test"})
    log.info("Standard informational message.")
    log.info("Info with formatting: %s=%d", "value", 100, extra={"calculation": True})
    log.warning("A warning occurred.", extra={"code": "W01", "details": None})
    log.error("An error occurred processing data.", extra={"data_id": 12345})
    log.critical("Critical system failure imminent!", extra={"system": "auth", "status": "offline"})

    # --- Exception Logging ---
    print("\n-> Exception Logging (Rich Traceback with Locals):")
    x: int = 0
    y: int = 0
    try:
        x = 1
        y = 0
        intermediate = x * 5
        result = intermediate / y  # noqa: F841
    except ZeroDivisionError:
        log.exception(
            "Caught division by zero.",  # Message
            extra={"operation": "divide", "x": x, "y": y},  # Context
            show_locals=None,  # Use config setting (True in this case)
            # show_locals=False # Example: Override config for this specific call
        )
        print("\n-> Manually passing exception info (tuple):")
        # You can also pass the exception info tuple explicitly
        log.exception("Error logged with explicit exc_info tuple.")

    # --- Custom Methods (Rich Output) ---
    print("\n-> Custom Method: rule")
    log.rule("Rich Rule Example")
    log.info("Content between rules.")
    log.rule("[bold red]Styled Rule[/]", characters="*")

    print("\n-> Custom Method: panel")
    log.panel("Simple text content in a default panel.", title="Info Panel")
    log.panel(
        "This panel is compact, adapting its width.\nIt uses a different border style.",
        title="Compact Panel",
        compact=True,
        border_style="yellow",
    )

    # Panel with a Rich Table inside
    table = Table("Item", "Status", "Details", title="Processing Status")
    table.add_row("Task 1", "[green]DONE[/]", "Completed successfully")
    table.add_row("Task 2", "[yellow]PENDING[/]", "Waiting for resources")
    table.add_row("Task 3", "[red]FAILED[/]", Text("See logs for details", style="italic"))
    log.panel(table, title="Panel with Rich Table", border_style="magenta", padding=(1, 2))

    print("\n-> Custom Method: progress (Rich Progress)")
    items = 50
    log.info("Starting Rich task count progress...")
    with log.progress(task_counter=True, description="Processing items...") as p:
        task_id = p.add_task("items", total=items)
        for _i in range(items):
            time.sleep(0.03)
            p.update(TaskID(task_id), advance=1)
    log.info("Rich task count finished.")

    time.sleep(0.5)

    log.info("Starting Rich file transfer progress...")
    file_size = 1_500_000  # bytes
    with log.progress(file_progress=True, description="Downloading data.bin...") as p:
        task_id = p.add_task("download", total=file_size)
        processed = 0
        while processed < file_size:
            advance = min(file_size - processed, 120_000)
            time.sleep(0.05)
            p.update(TaskID(task_id), advance=advance)
            processed += advance
    log.info("Rich file transfer finished.")

    time.sleep(0.5)

    log.info("Starting Rich indeterminate progress...")
    with log.progress(description="Working...") as p:
        p.add_task("working", total=None)  # total=None for spinner
        time.sleep(3)
    log.info("Rich indeterminate task finished.")


# ==================================================
# Demo Configuration 2: Loguru Console, Text File, ASCII Fallbacks
# ==================================================
def demo_loguru_text_ascii():
    """Demonstrates Loguru Console, Text file logging, ASCII fallbacks."""
    print("\n" + "=" * 60)
    print(" Demo 2: Loguru Console, Text File, ASCII Fallbacks ".center(60, "="))
    print("=" * 60)

    # Configure logger: Loguru console, TEXT file, simple tracebacks (affects Rich only)
    config = LoggerConfig(
        app_name="DemoAppLoguru",  # Different name -> potentially different log dir
        app_author="KardomeDemo",
        console_level=logging.INFO,  # Loguru console only shows INFO and above
        use_rich_console=False,  # Use Loguru sink for console
        use_simple_tracebacks=True,  # Flag mainly affects RichHandler; Loguru console uses its own tracebacks
        log_file_path="logs/demo2_loguru_explicit.log",  # Explicit relative path
        file_level=logging.DEBUG,  # File logs DEBUG messages
        log_file_serialize=False,  # Use TEXT format for file
        # Custom format string for the text file, INCLUDING {extra} manually
        log_file_format='{time:HH:mm:ss.SSS} | {level: <7} | {name}:{line: <3} | {message} | EXTRA={extra}\n{exception}',
        log_file_rotation="500 KB",  # Rotate after 500 KB for demo
        log_file_retention=3,  # Keep only last 3 log files
    )

    try:
        # Ensure the explicit logs directory exists
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)

        file_enabled, log_path = setup_logging(config)
        print("\nLogging initialized via setup_logging().")
        print(f"  File logging enabled: {file_enabled}")
        if log_path:
            print(f"  Log file path: {log_path}")
        print(f"  Console output via: {'Rich' if config.use_rich_console else 'Loguru'}")
        print(f"  File format: {'JSON' if config.log_file_serialize else 'Text'}")
        print(f"  Text Log Format: '{config.log_file_format if not config.log_file_serialize else 'N/A'}'")
        print("-" * 60)
    except (LoggerSetupError, PermissionError, OSError) as e:
        print(f"CRITICAL SETUP FAILED for Demo 2: {e}", file=sys.stderr)
        traceback.print_exc()
        return  # Cannot continue

    log = get_logger("demo.loguru_ascii")

    # --- Standard Logging ---
    print("\n-> Standard Logging Methods (Note console level is INFO):")
    log.debug("This debug message goes ONLY to the file.", extra={"file_only": True})
    log.info("Info message on Loguru console and file.", extra={"val": "A"})
    log.warning("Warning on Loguru console and file.", extra={"val": "B"})
    log.error("Error message on Loguru console and file.", extra={"val": "C"})

    # --- Exception logging (Loguru console traceback) ---
    print("\n-> Exception Logging (Loguru Console Traceback):")
    my_list: list[int] = []
    try:
        my_list = [1, 2]
        _ = my_list[5]
    except IndexError:
        log.exception("Caught expected IndexError.", extra={"index": 5, "list_len": len(my_list)})

    # --- Custom Methods (ASCII Fallbacks) ---
    print("\n-> Custom Method: rule (ASCII Fallback)")
    log.rule("ASCII Rule Example")
    log.info("Content after ASCII rule.")
    log.rule("Rule with different chars", characters="=-*", align="left")

    print("\n-> Custom Method: panel (ASCII Fallback)")
    log.panel("Simple ASCII panel content.", title="ASCII Panel")
    log.panel("Compact\nASCII\nPanel\nLine 3", title="Compact ASCII", compact=True)

    table = Table("Col 1")
    table.add_row("Row 1")
    log.panel(table, title="Fallback for Table Object")

    print("\n-> Custom Method: progress (ASCII Fallback)")
    items = 40
    log.info("Starting ASCII task count progress...")
    # Note: ASCII progress context manager yields a tracker object
    with log.progress(task_counter=True, description="ASCII Counting...") as p_ascii:
        # Fallback tracker API is simple but compatible for basic use
        task_id = p_ascii.add_task("counting", total=items)
        for _i in range(items):
            time.sleep(0.05)
            p_ascii.update(TaskID(task_id), advance=1)  # Update the single task
    log.info("ASCII Task count finished.")

    time.sleep(0.5)

    log.info("Starting ASCII indeterminate progress...")
    with log.progress(description="ASCII Working...") as p_ascii:
        # Add task mainly for description in ASCII mode when indeterminate
        p_ascii.add_task("working", total=None)
        time.sleep(3)
    log.info("ASCII Indeterminate task finished.")


# ==================================================
# Demo Configuration 3: File Logging Disabled
# ==================================================
def demo_no_file():
    """Demonstrates disabling file logging entirely."""
    print("\n" + "=" * 60)
    print(" Demo 3: File Logging Disabled ".center(60, "="))
    print("=" * 60)

    config = LoggerConfig(
        app_name="DemoAppNoFile",
        console_level=logging.INFO,  # Only INFO and above on console
        log_file_path=False,  # <--- Key change: Disable file logging
        use_rich_console=True,  # Use Rich console
        use_simple_tracebacks=False,  # Use enhanced Rich tracebacks
    )

    try:
        file_enabled, log_path = setup_logging(config)
        print("\nLogging initialized via setup_logging().")
        print(f"  File logging enabled: {file_enabled}")  # Should be False
        print(f"  Log file path: {log_path}")  # Should be None
        print(f"  Console output via: {'Rich' if config.use_rich_console else 'Loguru'}")
        print("-" * 60)
    except LoggerSetupError as e:
        print(f"CRITICAL SETUP FAILED for Demo 3: {e}", file=sys.stderr)
        traceback.print_exc()
        return

    log = get_logger("demo.no_file")
    log.debug("This debug message is silenced (console level is INFO).")
    log.info("This message appears only on the Rich console.")
    log.warning("This warning appears only on the Rich console.")
    # Custom methods still work on console
    log.rule("Rule without file logging")
    try:
        _ = 1 / 0
    except ZeroDivisionError:
        log.exception("Exception logged only to console.")


# ==================================================
# Main Execution Logic
# ==================================================
if __name__ == "__main__":
    print("=" * 70)
    print(" Kardome Logger Full Demo Script ".center(70, "="))
    print("=" * 70)
    # Run the demos sequentially
    demo_rich_json()

    print("\n>>> Press Enter to continue to Demo 2 (Loguru Console, Text File)...")
    input()

    demo_loguru_text_ascii()

    print("\n>>> Press Enter to continue to Demo 3 (File Logging Disabled)...")
    input()

    demo_no_file()

    print("\n" + "=" * 70)
    print(" Demo Finished ".center(70, "="))
    print("=" * 70)
    print("\nCheck console output above for behavior in each demo setup.")
    print("Check for log files:")
    print(" - Platform-specific user log directory for 'KardomeDemo/DemoAppRich'")
    print(" - './logs/demo2_loguru_explicit.log' (relative to execution dir)")
    print("(Log files are created only if file logging was enabled and successful).")
    print("-" * 70)
