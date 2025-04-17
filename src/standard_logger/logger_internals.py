# logger_internals.py
"""Internal constants, helpers, handlers, and types for the StandardLogger."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 [Yanai Klugman/Kardome]  # Update Year/Name

# =============================================================================
# Imports
# =============================================================================
import logging
import math
import os
import shutil
import sys
import time
import traceback

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import TracebackType
from typing import Any, TypeAlias, TypeVar, cast

import platformdirs

from loguru import logger as loguru_sink_handler
from rich.align import AlignMethod
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    FileSizeColumn,
    MofNCompleteColumn,
    ProgressColumn,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text, TextType
from rich.traceback import install as install_rich_tracebacks

# =============================================================================
# Type Aliases
# =============================================================================
if sys.version_info >= (3, 12):
    ExcInfoType: TypeAlias = tuple[
        type[BaseException],
        BaseException,
        traceback.TracebackException | None,
    ]
    ExcInfoInput: TypeAlias = bool | ExcInfoType | tuple[None, None, None] | None
    ExtraData: TypeAlias = dict[str, object]
else:
    # Fallback Any for TracebackType compatibility pre-3.11/3.12 TracebackException changes
    ExcInfoType = tuple[type[BaseException], BaseException, Any | TracebackType | None]
    ExcInfoInput = bool | ExcInfoType | tuple[None, None, None] | None
    ExtraData = dict[str, object]

# TypeVar for configuring logger instance helper
TLogger = TypeVar('TLogger', bound=logging.Logger)


# =============================================================================
# Custom Exceptions
# =============================================================================
class LoggerSetupError(Exception):
    """Custom exception for critical errors during logger setup."""

    pass


# =============================================================================
# Constants
# =============================================================================
DEFAULT_CONSOLE_TIME_FORMAT: str = '[%X]'
DEFAULT_LOGURU_CONSOLE_FORMAT: str = (
    '<green>{time:HH:mm:ss}</green> | '
    '<level>{level.name: <8}</level> | '
    '<cyan>{name}:{line:<4}</cyan> - '
    '<level>{message}</level>'
)
DEFAULT_TEXT_LOG_FORMAT: str = (
    '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}'
)
# Note: Default format does *not* include {extra}. Must be added manually if desired in text logs.
DEFAULT_FILE_TEXT_LOG_FORMAT: str = DEFAULT_TEXT_LOG_FORMAT + '\n{exception}'
DEFAULT_LOG_DIRECTORY_NAME: str = 'logs'  # Used only in CWD fallback path
DEFAULT_LOG_FILENAME_PREFIX: str = 'kardome_log_'
DEFAULT_APP_AUTHOR: str = 'Kardome'  # Default author for platformdirs path
DEFAULT_APP_NAME: str = 'PythonApp'  # Default app name if not specified
DEFAULT_RICH_PANEL_WIDTH: int = 88
DEFAULT_ASCII_PANEL_WIDTH: int = 78

# --- Rich Progress Column Definitions ---
DEFAULT_SPINNER_COLUMNS_TPL: tuple[ProgressColumn, ...] = (
    TextColumn('[progress.description]{task.description}'),
    SpinnerColumn(),
    TimeElapsedColumn(),
)
FILE_PROGRESS_COLUMNS: tuple[ProgressColumn, ...] = (
    TextColumn('[progress.description]{task.description}'),
    BarColumn(),
    FileSizeColumn(),
    TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
    TransferSpeedColumn(),
    TimeRemainingColumn(),
)
TASK_COUNT_PROGRESS_COLUMNS: tuple[ProgressColumn, ...] = (
    TextColumn('[progress.description]{task.description}'),
    BarColumn(),
    MofNCompleteColumn(),
    TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
    TimeRemainingColumn(),
)


# =============================================================================
# Custom Filters & Handlers
# =============================================================================
class SuppressConsoleFilter(logging.Filter):
    """Prevents records with 'suppress_console=True' extra data from RichHandler."""

    # Applied only when Rich Console is ON and Simple Tracebacks are OFF.
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out records if suppress_console is True in extra."""
        return not getattr(record, 'suppress_console', False)


class LoguruInterceptHandler(logging.Handler):
    """Redirects ALL standard logging records to configured Loguru sinks."""

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record, intercepting it for Loguru."""
        try:
            level = loguru_sink_handler.level(record.levelname).name
        except ValueError:
            level = record.levelno  # Fallback to level number

        frame = logging.currentframe()
        depth = 2
        # Find the frame that originated the logging call
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # Loguru handles the exception info automatically via its 'exception' opt
        loguru_sink_handler.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),  # Let Loguru handle final formatting
        )


# =============================================================================
# Setup Helper Functions
# =============================================================================
def _handle_raise(error: Exception, message: str) -> None:
    """Helper function to raise LoggerSetupError, satisfying Ruff's TRY301."""
    # Allows raising from an except block without violating TRY301.
    raise LoggerSetupError(message) from error


def _get_default_log_file_path(app_name: str, app_author: str | None) -> Path:
    """
    Generates the default platform-specific log file path stem (no extension).

    Constructs path like .../AppAuthor/AppName/Logs/prefix_timestamp. Falls back
    cautiously to './logs/prefix_timestamp' if platform-specific paths fail.
    The final extension (.log or .jsonl) is added later based on config.

    Parameters are the same as before...
    Raises are the same as before...

    Returns
    -------
    Path
        The resolved Path object for the default log file stem (directory + prefix + timestamp).
    """
    log_dir: Path | None = None
    setup_error: Exception | None = None

    # --- Try Platform-Specific Directory ---
    try:
        platform_log_dir: Path = Path(
            platformdirs.user_log_path(
                appname=app_name,
                appauthor=app_author,
            ),
        )
        platform_log_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(str(platform_log_dir), os.W_OK):
            raise PermissionError(f'No write permission for platform log directory: {platform_log_dir}')
        log_dir = platform_log_dir
        logging.debug(f'Using platform default log directory: {log_dir}')

    except Exception as e:
        logging.warning(f"Failed to use platform log path: {e}. Falling back to CWD.")
        logging.debug("Platform path exception details:", exc_info=e)

        # --- Fallback to CWD/logs ---
        try:
            fallback_dir: Path = Path.cwd() / DEFAULT_LOG_DIRECTORY_NAME
            fallback_dir.mkdir(parents=True, exist_ok=True)
            if not os.access(str(fallback_dir), os.W_OK):
                raise PermissionError(f'No write permission for fallback directory: {fallback_dir}')
            log_dir = fallback_dir
            logging.warning(f'Using fallback log directory: {log_dir}')
        except Exception as fallback_e:
            logging.exception("Fallback log directory setup failed.", exc_info=fallback_e)
            setup_error = fallback_e

    # --- Raise If Critical Failure During Fallback ---
    if setup_error:
        _handle_raise(setup_error, 'Could not establish any writable default log directory.')

    # --- Final Check ---
    if log_dir is None:
        raise RuntimeError("log_dir is none")

    # --- Generate Filename STEM (no extension) ---
    timestamp: str = time.strftime('%Y%m%d_%H%M%S')
    # CHANGE: Generate only the stem part of the filename
    filename_stem: str = f'{DEFAULT_LOG_FILENAME_PREFIX}{timestamp}'
    # CHANGE: Return the path including the stem but no suffix
    base_log_path: Path = log_dir / filename_stem

    logging.debug(f'Default log path stem determined: {base_log_path}')
    # CHANGE: Return the base path without suffix
    return base_log_path


def _configure_root_logger(
    logger_class: type[TLogger],
    min_level: int,
) -> TLogger:
    """Sets the global logger class and configures the root logger."""
    # Set the custom class globally BEFORE getting any logger instance
    logging.setLoggerClass(logger_class)

    root_logger = logging.getLogger()  # Get root logger
    root_logger.setLevel(min_level)  # Set minimum level root will process

    # Clear any *existing* handlers from root logger to prevent duplication
    # if setup_logging is called multiple times.
    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    # Subsequent logging.getLogger(name) calls will return logger_class instances
    # Cast needed because getLogger() type hint is still logging.Logger
    return cast(TLogger, root_logger)


def _setup_rich_console_handler(
    console: Console,
    level: int,
    time_format: str,
    *,
    use_simple_tracebacks: bool,
) -> RichHandler:
    """Configures and returns the RichHandler."""
    # RichHandler's tracebacks are used internally unless simple_tracebacks is True.
    use_rich_tb_internally = not use_simple_tracebacks
    console_handler = RichHandler(
        level=level,
        console=console,
        rich_tracebacks=use_rich_tb_internally,
        tracebacks_show_locals=False,  # Controlled later via logger class attribute access
        markup=True,
        show_path=False,
        show_time=True,
        log_time_format=time_format,
        omit_repeated_times=False,
    )
    # Add suppression filter ONLY if Rich tracebacks active internally,
    # prevents double printing when logger.exception manually prints rich TB.
    if use_rich_tb_internally:
        console_handler.addFilter(SuppressConsoleFilter())
    return console_handler


def _configure_loguru_console_sink(level: int, time_format: str) -> None:
    """Configures Loguru's default stderr sink (used when Rich is OFF)."""
    # Loguru provides enhanced tracebacks by default in this mode.
    # Modify default format slightly to incorporate user's time preference.
    loguru_format = (
        f'<green>{{time:{time_format}}}</green> | '
        '<level>{level.name: <8}</level> | '
        '<cyan>{name}:{line:<4}</cyan> - '
        '<level>{message}</level>'
    )
    try:
        # Remove default sink (ID 0) before re-adding configured one
        # Prevents duplicates if setup called multiple times with Rich OFF.
        with suppress(ValueError):
            loguru_sink_handler.remove(0)

        loguru_sink_handler.add(
            sys.stderr,
            level=level,
            format=loguru_format,
            colorize=True,
            enqueue=True,  # Safer for threads/processes
            catch=True,  # Loguru handles its own sink errors
        )
    except Exception as e:
        # Use basic print as logger might not be fully setup
        print(f'ERROR: Failed Loguru console sink config: {e}', file=sys.stderr)


def _setup_loguru_file_sink(
    log_file_path: Path,
    level: int,
    file_format: str | None,
    rotation: str | int,
    retention: str | int,
    *,
    serialize: bool,
) -> None:
    """Configures the Loguru FILE sink."""
    setup_error: Exception | None = None
    err_msg = ''

    sink_kwargs: dict[str, Any] = {
        'sink': log_file_path,
        'level': level,
        'rotation': rotation,
        'retention': retention,
        'encoding': 'utf-8',
        'enqueue': True,
        'catch': True,
        'serialize': serialize,
    }
    # Only add 'format' kwarg if *not* serializing (JSON)
    if not serialize:
        sink_kwargs['format'] = file_format if file_format is not None else DEFAULT_FILE_TEXT_LOG_FORMAT

    try:
        loguru_sink_handler.add(**sink_kwargs)
    except Exception as e:
        err_msg = f"Failed to configure Loguru file sink: '{log_file_path}'"
        logging.exception(err_msg, exc_info=e)  # Log details before raising
        setup_error = e

    if setup_error:
        _handle_raise(setup_error, err_msg)


def _install_rich_traceback_hook(console: Console, *, show_locals: bool) -> None:
    """Installs the Rich traceback hook for uncaught exceptions."""
    # `suppress=[]` ensures Rich handles standard exceptions.
    # We could add specific library paths (like our own) here to suppress
    # frames from those libraries if desired in the future.
    install_rich_tracebacks(show_locals=show_locals, console=console, suppress=[])


# =============================================================================
# Fallback Implementations (ASCII/UTF-8)
# =============================================================================
def _render_ascii_panel(
    renderable: object,
    title: TextType | None = None,
    *,
    compact: bool = False,
) -> None:
    """Prints a simple ASCII/UTF-8 panel representation to stderr."""
    plain_text: str
    match renderable:
        case str():
            plain_text = renderable
        case Text():
            plain_text = renderable.plain
        case Table():
            hdr = ', '.join(str(c.header) for c in renderable.columns)
            plain_text = f'[Table cols: {hdr}, {len(renderable.rows)} row(s)]'
        case int() | float() | bool():
            plain_text = str(renderable)
        case _:
            plain_text = f'[{type(renderable).__name__} object]'

    title_str = str(title) if title else None
    lines: list[str] = []
    content_lines = plain_text.splitlines()
    max_content_width = max(len(line) for line in content_lines) if content_lines else 0
    title_width = len(title_str or '')
    inner_width: int
    target_width: int
    if compact:
        # Adapt width to content or title, plus padding
        inner_width = max(max_content_width, title_width, 18)  # Min width 18
        target_width = inner_width + 4
    else:
        # Use default fixed width
        target_width = DEFAULT_ASCII_PANEL_WIDTH
        inner_width = target_width - 4

    # Use box drawing characters for a slightly nicer look than pure ASCII
    top = f'╭{"─" * (target_width - 4)}╮'
    bottom = f'╰{"─" * (target_width - 4)}╯'
    lines.append(top)
    if title_str:
        # Center title, truncate if necessary
        padded_title = f' {title_str} '.center(inner_width)
        if len(padded_title) > inner_width:
            padded_title = f' {title_str[: inner_width - 3]}… '.ljust(inner_width)
        lines.append(f'│{padded_title}│')
        lines.append(f'├{"─" * inner_width}┤')  # Separator after title
    else:
        # No title, only top border
        pass  # No title line, no separator needed immediately

    for line in content_lines:
        # Truncate content lines if they exceed inner width
        if len(line) > inner_width:
            line = line[: inner_width - 1] + '…'
        lines.append(f'│ {line.ljust(inner_width - 1)}│')  # Pad content line
    lines.append(bottom)
    print('\n'.join(lines), file=sys.stderr)


def _render_ascii_rule(
    title: TextType | None = None,
    *,
    characters: str = '─',
    align: AlignMethod = 'center',
) -> None:
    """Prints a simple ASCII/UTF-8 rule line to stderr."""
    try:
        term_width = shutil.get_terminal_size((DEFAULT_ASCII_PANEL_WIDTH + 2, 20)).columns
    except OSError:  # Fallback if terminal size detection fails (e.g., in CI)
        term_width = DEFAULT_ASCII_PANEL_WIDTH + 2

    # Use first character of `characters` or default '─'
    char = characters[0] if characters else '─'

    title_str = ''
    if isinstance(title, Text):
        title_str = title.plain  # Use plain text from Rich Text object
    elif title:
        title_str = str(title)

    if not title_str:
        # Simple rule spanning terminal width
        print(char * term_width, file=sys.stderr)
        return

    title_len = len(title_str)
    padding = 2  # Spaces around title: e.g., '── TITLE ──'
    if title_len + 2 * padding >= term_width:
        # Title too long, just print title centered
        print(title_str.center(term_width), file=sys.stderr)
        return

    # Calculate lengths for rule segments based on alignment
    total_rule_len = term_width - title_len - 2 * padding
    if align == 'center':
        left_len = total_rule_len // 2
        right_len = total_rule_len - left_len
        output = f'{char * left_len}{" " * padding}{title_str}{" " * padding}{char * right_len}'
    elif align == 'left':
        right_len = total_rule_len
        output = f'{" " * padding}{title_str}{" " * padding}{char * right_len}'
    elif align == 'right':
        left_len = total_rule_len
        output = f'{char * left_len}{" " * padding}{title_str}{" " * padding}'
    else:  # Default to center if align is invalid
        left_len = total_rule_len // 2
        right_len = total_rule_len - left_len
        output = f'{char * left_len}{" " * padding}{title_str}{" " * padding}{char * right_len}'

    # Ensure output doesn't exceed terminal width due to rounding/calculation issues
    print(output[:term_width], file=sys.stderr)


class _AsciiProgressTracker:
    """Manages state and printing for ASCII progress fallback."""

    def __init__(self, initial_description: str | None):
        self._description = initial_description or 'Progress'
        self._total: float | None = None
        self._current: float = 0.0
        self._last_len = 0
        self._bar_width = 30
        self._start_time = time.monotonic()

    def add_task(self, description: str, total: float | None = None, **_kwargs: object) -> int:
        """Configure the single task for ASCII progress."""
        # ASCII version only really supports one task's description/total.
        self._description = description
        self._total = total
        self._current = 0.0
        self._last_len = 0
        self.update(task_id=0, advance=0.0)  # Initial print
        return 0  # Task ID is always 0 for ASCII tracker

    def update(
        self,
        task_id: int | None,  # Ignored in ASCII version
        *,
        advance: float | None = None,
        total: float | None = None,
        description: str | None = None,
    ) -> None:
        """Update progress state and reprint the ASCII progress line."""
        if description is not None:
            self._description = description
        if total is not None:
            self._total = total
        if advance is not None:
            self._current += advance

        percent = 0.0
        bar = ''
        progress_text = ''
        elapsed = time.monotonic() - self._start_time

        if self._total is not None and self._total > 0:
            # Determinate progress
            current_clamped = max(0.0, min(self._current, self._total))
            percent = (current_clamped / self._total) * 100
            filled_len = math.ceil(self._bar_width * percent / 100)
            bar_char, empty_char = '█', '░'  # Block characters look better
            bar = f'[{bar_char * filled_len}{empty_char * (self._bar_width - filled_len)}]'
            progress_text = f'{percent:.1f}% ({elapsed:.1f}s)'
        elif self._total == 0:
            # Total is zero, consider it immediately complete
            percent = 100.0
            bar = f'[{"█" * self._bar_width}]'
            progress_text = f'100.0% ({elapsed:.1f}s)'
        else:
            # Indeterminate progress (spinner)
            spinner_chars = '|/-\\'
            spinner = spinner_chars[int(time.time() * 4) % len(spinner_chars)]
            bar = f'[{spinner}]'
            progress_text = f'({elapsed:.1f}s)'

        # Assemble the final string
        progress_str = f'{self._description}: {bar} {progress_text}'.strip()

        # Clear previous line using carriage return and spaces, then print new line
        clear_line = '\r' + ' ' * self._last_len + '\r'
        print(clear_line + progress_str, end='', file=sys.stderr, flush=True)
        self._last_len = len(progress_str)  # Store length for next clear

    def _finalize_print(self) -> None:
        """Ensures 100% is printed (if applicable) and clears the line."""
        if self._total is not None and self._current >= self._total:
            # Ensure the final update shows 100% if determinate
            self.update(task_id=0, advance=0)
        # Clear the progress line completely on finalization
        clear_final = '\r' + ' ' * self._last_len + '\r'
        print(clear_final, end='', file=sys.stderr, flush=True)

    @property
    def finished(self) -> bool:
        """Check if the progress is considered finished."""
        # Finished if total is set and current progress reaches or exceeds it.
        return self._total is not None and self._current >= self._total


@contextmanager
def _ascii_progress_context(
    logger: logging.Logger,
    initial_description: str | None = None,
) -> Iterator[_AsciiProgressTracker]:
    """Context manager providing basic ASCII progress updates."""
    start_desc = initial_description or 'Progress'
    # Log the start using the actual description
    logger.info(f'Progress start: {start_desc}')
    # Attempt to clear potential leftover characters from previous prints
    print('\r' + ' ' * 80 + '\r', end='', file=sys.stderr)
    tracker = _AsciiProgressTracker(start_desc)
    try:
        yield tracker
    finally:
        tracker._finalize_print()
        # Log the end using the actual description
        logger.info(f'Progress end: {start_desc}')
