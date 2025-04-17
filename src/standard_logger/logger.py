# logger.py
"""
Main StandardLogger implementation using LoggerConfig for setup.

Provides user-facing logger class and setup function. Relies on
logger_internals for helper functions and constants.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 [Yanai Klugman/Kardome]

# =============================================================================
# Imports
# =============================================================================
from __future__ import annotations

import logging
import os
import sys

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, overload  # Keep Any for _log overload compat

from rich.align import AlignMethod
from rich.box import ROUNDED, Box

# --- Rich Imports (Type Hints & Objects) ---
from rich.console import Console, RenderableType
from rich.padding import PaddingDimensions
from rich.panel import Panel as RichPanel  # Alias to avoid clash
from rich.progress import Progress, ProgressColumn, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.style import StyleType
from rich.text import TextType
from rich.traceback import Traceback

# --- Internal Imports ---
from .logger_internals import (
    DEFAULT_APP_AUTHOR,
    DEFAULT_APP_NAME,
    DEFAULT_RICH_PANEL_WIDTH,
    # Constants
    FILE_PROGRESS_COLUMNS,
    TASK_COUNT_PROGRESS_COLUMNS,
    ExcInfoInput,
    # Types
    ExcInfoType,
    ExtraData,
    # Exceptions
    LoggerSetupError,
    LoguruInterceptHandler,
    # Filters
    _ascii_progress_context,  # Import fallback class
    _AsciiProgressTracker,
    _configure_loguru_console_sink,
    # Helpers
    _configure_root_logger,
    _get_default_log_file_path,
    _install_rich_traceback_hook,
    _render_ascii_panel,
    _render_ascii_rule,
    _setup_loguru_file_sink,
    _setup_rich_console_handler,
    loguru_sink_handler,
)


# =============================================================================
# Configuration
# =============================================================================
@dataclass
class LoggerConfig:
    """
    Configuration settings for the StandardLogger.

    Attributes
    ----------
    app_name : str
        Application name, used for default log path generation via platformdirs.
        (default: "PythonApp").
    app_author : str | None
        Application author, used for default log path generation via platformdirs.
        Set to None to omit author directory level. (default: "Kardome").
    console_level : int
        Minimum level for console output (default: logging.INFO).
    use_rich_console : bool
        If True, use RichHandler for console; otherwise, use Loguru's
        console sink (default: True).
    use_simple_tracebacks : bool
        If True, use basic Python traceback on console. If False (default),
        use enhanced traceback (Rich if Rich Console is ON, Loguru otherwise).
        (default: False).
    console_time_format : str
        Time format string for console logs (default: '[%X]'). Passed to
        RichHandler or used in Loguru format string.
    show_locals_on_exception : bool
        If using Rich tracebacks (`use_rich_console=True` and
        `use_simple_tracebacks=False`), whether to show local variables
        (default: False).
    log_file_path : str | Path | Literal[False] | None
        Path for the log file. None auto-generates, False disables file logging
        (default: None).
    file_level : int
        Minimum level for file output (default: logging.DEBUG).
    log_file_format : str | None
        Loguru format string for text file logs (used if `serialize=False`).
        None uses internal default. `{extra}` must be included manually
        to show the extra dict in text logs. (default: None).
    log_file_rotation : str | int
        Loguru rotation setting (size/time, e.g., "10 MB", "1 day") (default: '10 MB').
    log_file_retention : str | int
        Loguru retention setting (time/count, e.g., "7 days", 5) (default: '7 days').
    log_file_serialize : bool
        If True, logs to file in JSON format, automatically including 'extra'
        data (default: True).
    """

    app_name: str = DEFAULT_APP_NAME
    app_author: str | None = DEFAULT_APP_AUTHOR
    # Console
    console_level: int = logging.INFO
    use_rich_console: bool = True
    use_simple_tracebacks: bool = False
    console_time_format: str = '[%X]'
    show_locals_on_exception: bool = False
    # File
    log_file_path: str | Path | Literal[False] | None = None
    file_level: int = logging.DEBUG
    log_file_format: str | None = None
    log_file_rotation: str | int = '10 MB'
    log_file_retention: str | int = '7 days'
    log_file_serialize: bool = True  # Default to JSON

    def __post_init__(self):
        """Validate configuration settings after initialization."""
        self._validate_level('console_level', logging.INFO)
        self._validate_level('file_level', logging.DEBUG)

    def _validate_level(self, attr_name: str, default_level: int) -> None:
        """Helper to validate a logging level attribute."""
        level = getattr(self, attr_name)
        valid = False

        try:
            if isinstance(level, str):
                level_int_candidate = logging.getLevelName(level.upper())
                if isinstance(level_int_candidate, int):
                    valid = True
                # else: String was not a valid level name, valid remains False
            elif isinstance(level, int):
                logging.getLevelName(level)  # Check if int level is valid (raises ValueError if not)
                valid = True
            # Else: Type is wrong, valid remains False
        except (TypeError, ValueError, AttributeError):
            valid = False  # Ensure invalid on exception

        if not valid:
            logging.warning(
                f"Invalid {attr_name} '{getattr(self, attr_name)}'. "
                f'Using default {logging.getLevelName(default_level)}.',
            )
            # Set the attribute to the valid default integer level
            setattr(self, attr_name, default_level)


# --- Default Configuration Instance ---
DEFAULT_LOGGER_CONFIG = LoggerConfig()

# --- Global Rich Console Instance ---
_rich_console = Console(stderr=True)


# =============================================================================
# Standard Logger Class
# =============================================================================
class StandardLogger(logging.Logger):
    """
    Custom Logger integrating Rich features (if enabled) with ASCII fallbacks.

    Configured via LoggerConfig passed to setup_logging. Emphasizes structured
    file logging (JSON default) and effective use of the 'extra' dictionary.
    Supports standard Python logging formatting styles. Obtain instances via
    `logging.getLogger(__name__)` after calling `setup_logging`.
    """

    # --- Class Attributes ---
    FILE_PROGRESS_COLUMNS = FILE_PROGRESS_COLUMNS
    TASK_COUNT_PROGRESS_COLUMNS = TASK_COUNT_PROGRESS_COLUMNS

    # --- Instance Attributes Set by setup_logging ---
    # These class variables store config state needed by instance methods.
    # Assumes setup_logging is called once per process.
    _show_locals_in_traceback_cls: bool = False
    _use_rich_console_cls: bool = True
    _use_simple_tracebacks_cls: bool = False

    # --- Internal Helpers ---
    def _create_rich_progress(
        self: StandardLogger,
        columns: list[ProgressColumn | str],
        *,
        transient: bool,
        disable: bool,
    ) -> Progress:
        """Internal helper to create a Rich Progress instance."""
        from rich.progress import Progress

        return Progress(
            *columns,
            console=_rich_console,
            auto_refresh=True,
            refresh_per_second=10,
            transient=transient,
            disable=disable,
        )

    def _print_rich_traceback(
        self: StandardLogger,
        exc_info: ExcInfoType,
        *,
        show_locals: bool,
    ) -> None:
        """Internal helper to format and print a Rich Traceback."""
        import traceback as tbmod
        import types

        exc_type, exc_value, exc_traceback = exc_info
        tb_actual: types.TracebackType | None
        # Defensive: Only pass TracebackType or None to Rich
        if isinstance(exc_traceback, tbmod.TracebackException):
            # Try to extract __traceback__ from the exception value
            tb_actual = exc_value.__traceback__ if hasattr(exc_value, '__traceback__') else None
        elif isinstance(exc_traceback, types.TracebackType) or exc_traceback is None:
            tb_actual = exc_traceback
        else:
            tb_actual = None
        rich_tb: Traceback = Traceback.from_exception(
            exc_type=exc_type,
            exc_value=exc_value,
            traceback=tb_actual,
            show_locals=show_locals,
            word_wrap=True,
        )
        _rich_console.print(rich_tb)

    # --- Public Methods ---
    def panel(
        self: StandardLogger,
        renderable: RenderableType,
        *,
        title: TextType | None = None,
        style: StyleType = 'none',
        border_style: StyleType = 'blue',
        padding: PaddingDimensions = (0, 1),
        highlight: bool = False,
        box: Box = ROUNDED,
        compact: bool = False,
        width: int | None = None,
    ) -> None:
        """
        Prints a Rich Panel or a simple ASCII/UTF-8 fallback to the console.

        Parameters
        ----------
        renderable : object
            Content to display. Rich renderable or object convertible to string.
        title : TextType | None, optional
            Title for the panel. Defaults to None.
        style : StyleType, optional
            Rich only: Style for panel content. Defaults to 'none'.
        border_style : StyleType, optional
            Rich only: Style for panel border. Defaults to "blue".
        padding : tuple[int, int] | int, optional
            Rich only: Padding inside panel. Defaults to (0, 1).
        highlight : bool, optional
            Rich only: Highlight the panel. Defaults to False.
        box : rich.box.Box, optional
            Rich only: Box style for border. Defaults to rich.box.ROUNDED.
        compact : bool, optional
            If True, panel width adapts to content. If False (default), panel
            uses a fixed width if possible. Defaults to False.
        width : int | None, optional
            Rich only: Manually set panel width. Overrides compact/default width.
            Defaults to None.

        Examples
        --------
        >>> import logging
        >>> from kardome_logger import StandardLogger  # Needed for cast/isinstance
        >>> from typing import cast
        >>> log = cast(StandardLogger, logging.getLogger(__name__))  # Assuming setup
        >>> log.panel('Processing complete!', title='Status', border_style='green')
        >>> from rich.table import Table
        >>> table = Table('Name', 'Value')
        ... table.add_row('CPU', '75%')
        >>> log.panel(table, title='System Metrics', compact=True)
        """
        if StandardLogger._use_rich_console_cls:
            panel_width = width
            if panel_width is None and not compact:
                panel_width = DEFAULT_RICH_PANEL_WIDTH

            content = renderable.renderable if isinstance(renderable, RichPanel) else renderable
            panel_widget = RichPanel(
                content,
                title=title,
                title_align='left',
                border_style=border_style,
                padding=padding,
                highlight=highlight,
                expand=False,
                box=box,
                width=panel_width,
            )
            _rich_console.print(panel_widget)
        else:
            _render_ascii_panel(renderable, title, compact=compact)

    def progress(
        self: StandardLogger,
        *,
        file_progress: bool = False,
        task_counter: bool = False,
        transient: bool = False,
        disable: bool = False,
        description: str | None = 'Processing...',
    ) -> Progress | AbstractContextManager[_AsciiProgressTracker]:
        """
        Create Rich Progress context manager or an ASCII fallback tracker.

        Examples see :meth:`~panel` docstring for logger setup.
        Also see README.md for detailed examples.

        Parameters see :meth:`~panel` docstring and README.md.

        Returns see :meth:`~panel` docstring and README.md.
        """
        if disable:

            @contextmanager
            def noop_context() -> Iterator[None]:
                yield None

            return noop_context()  # type: ignore

        if StandardLogger._use_rich_console_cls:
            columns: list[ProgressColumn | str]
            match (file_progress, task_counter):
                case (True, True):
                    raise ValueError('file_progress and task_counter cannot both be True')
                case (True, False):
                    columns = list(FILE_PROGRESS_COLUMNS)
                case (False, True):
                    columns = list(TASK_COUNT_PROGRESS_COLUMNS)
                case _:  # Default spinner layout
                    desc = description if description is not None else ''
                    columns = [
                        TextColumn(f'[progress.description]{desc}'),
                        SpinnerColumn(),
                        TimeElapsedColumn(),
                    ]
            return self._create_rich_progress(columns=columns, transient=transient, disable=disable)
        return _ascii_progress_context(self, description)

    def rule(
        self: StandardLogger,
        title: TextType = '',
        *,
        characters: str = '─',
        style: StyleType = 'rule.line',
        align: AlignMethod = 'center',
    ) -> None:
        """
        Prints a horizontal rule line with an optional title.

        Uses Rich Rule when Rich console is enabled, otherwise prints an
        ASCII/UTF-8 approximation to stderr.

        Parameters
        ----------
        title : str | rich.text.Text, optional
            Text to render in the rule. Defaults to "".
        characters : str, optional
            Character(s) used to draw the line (first char used in fallback).
            Defaults to "─".
        style : str | rich.style.Style, optional
            Rich only: Style of Rule line and text. Defaults to "rule.line".
        align : Literal["left", "center", "right"], optional
            How to align the title. Defaults to "center".

        Examples
        --------
        >>> import logging
        >>> from kardome_logger import StandardLogger  # Needed for cast/isinstance
        >>> from typing import cast
        >>> log = cast(StandardLogger, logging.getLogger(__name__))  # Assuming setup
        >>> log.rule('Section Start')
        >>> log.rule('[bold red]Warning Zone[/]', characters='*')  # Rich markup
        """
        if StandardLogger._use_rich_console_cls:
            _rich_console.rule(title, characters=characters, style=style, align=align)
        else:
            _render_ascii_rule(title, characters=characters, align=align)

    # --- Overridden Standard Logging Methods ---
    # Justification for > 20 lines: Simple signature overrides provide clear API
    # and type safety, preferred over a single complex method.
    @overload
    def _log(
        self: StandardLogger,
        level: int,
        msg: object,
        args: tuple[()],
        exc_info: ExcInfoInput = ...,
        extra: ExtraData | None = ...,
        *,
        stack_info: bool = ...,
        stacklevel: int = ...,
    ) -> None: ...
    @overload
    def _log(
        self: StandardLogger,
        level: int,
        msg: object,
        args: tuple[object, ...],
        exc_info: ExcInfoInput = ...,
        extra: ExtraData | None = ...,
        *,
        stack_info: bool = ...,
        stacklevel: int = ...,
    ) -> None: ...

    def _log(
        self: StandardLogger,
        level: int,
        msg: object,
        args: tuple[object, ...],
        exc_info: ExcInfoInput = None,
        extra: ExtraData | None = None,
        *,
        stack_info: bool = False,
        stacklevel: int = 1,
    ) -> None:
        """Internal logging. Use level-specific methods e.g., logger.info()."""
        import traceback as tbmod

        exc_info_to_pass: tuple[type[BaseException], BaseException, TracebackType | None] | None = None
        if (
            isinstance(exc_info, tuple)
            and len(exc_info) == 3
            and isinstance(exc_info[2], tbmod.TracebackException)
        ):
            exc_type, exc_val, _ = exc_info
            tb = (
                exc_val.__traceback__ if exc_val is not None and hasattr(exc_val, '__traceback__') else None
            )
            if exc_type is not None and exc_val is not None:
                exc_info_to_pass = (exc_type, exc_val, tb)
            else:
                exc_info_to_pass = None
        else:
            exc_info_to_pass = exc_info  # type: ignore

        super()._log(
            level,
            msg,
            args,
            exc_info_to_pass,
            extra,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )

    def debug(
        self: StandardLogger,
        msg: object,
        *args: object,
        extra: ExtraData | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        exc_info: ExcInfoInput = None,
    ) -> None:
        """Logs DEBUG message. Supports standard formatting args. Use `extra` dict for context."""
        if self.isEnabledFor(logging.DEBUG):
            self._log(
                logging.DEBUG,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
            )

    def info(
        self: StandardLogger,
        msg: object,
        *args: object,
        extra: ExtraData | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        exc_info: ExcInfoInput = None,
    ) -> None:
        """Logs INFO message. Supports standard formatting args. Use `extra` dict for context."""
        if self.isEnabledFor(logging.INFO):
            self._log(
                logging.INFO,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
            )

    def warning(
        self: StandardLogger,
        msg: object,
        *args: object,
        extra: ExtraData | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        exc_info: ExcInfoInput = None,
    ) -> None:
        """Logs WARNING message. Supports standard formatting args. Use `extra` dict for context."""
        if self.isEnabledFor(logging.WARNING):
            self._log(
                logging.WARNING,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
            )

    def error(
        self: StandardLogger,
        msg: object,
        *args: object,
        extra: ExtraData | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        exc_info: ExcInfoInput = None,
    ) -> None:
        """Logs ERROR message. Supports standard formatting args. Use `extra` dict for context."""
        if self.isEnabledFor(logging.ERROR):
            self._log(
                logging.ERROR,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
            )

    def critical(
        self: StandardLogger,
        msg: object,
        *args: object,
        extra: ExtraData | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        exc_info: ExcInfoInput = None,
    ) -> None:
        """Logs CRITICAL message. Supports standard formatting args. Use `extra` dict for context."""
        if self.isEnabledFor(logging.CRITICAL):
            self._log(
                logging.CRITICAL,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
            )

    def exception(
        self: StandardLogger,
        msg: object,
        *args: object,
        exc_info: ExcInfoInput = True,
        extra: ExtraData | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        show_locals: bool | None = None,
    ) -> None:
        """
        Logs ERROR message including exception information. Supports formatting args.

        Console traceback format depends on config flags. File logs always include
        full traceback (with locals) via Loguru.

        Parameters
        ----------
        msg : object
            Log message format string or object.
        *args : object
            Arguments merged into msg using string formatting.
        exc_info : ExcInfoInput, optional
            Exception info source (default: True).
        extra : ExtraData | None, optional
            Dictionary of extra data.
        stack_info : bool, optional
            Include stack info (default: False).
        stacklevel : int, optional
            Adjust stack frame level (default: 1).
        show_locals : bool | None, optional
            Overrides config `show_locals_on_exception` for console Rich TBs.
            If None (default), config setting is used. Ignored otherwise.
        """
        # Justification for > 20 lines: Core exception logic based on flags.
        # Determine if manual Rich TB printing is needed
        should_print_manual_rich_tb = (
            StandardLogger._use_rich_console_cls and not StandardLogger._use_simple_tracebacks_cls
        )

        # --- Determine Exception Info ---
        actual_exc_info: ExcInfoType | tuple[None, None, None] = (None, None, None)
        if exc_info is True:
            current_exc = sys.exc_info()
            # Ensure all 3 parts are captured, even if None
            actual_exc_info = current_exc if current_exc[0] else (None, None, None)  # type: ignore
        elif isinstance(exc_info, tuple):  # Basic validation...
            if len(exc_info) == 3 and (
                exc_info[0] is None
                or (isinstance(exc_info[0], type) and issubclass(exc_info[0], BaseException))
            ):
                actual_exc_info = exc_info  # type: ignore
            else:
                self.warning(f'Invalid tuple for exc_info: {exc_info}. Ignoring.')
        elif exc_info not in (False, None):
            self.warning(f'Invalid type for exc_info: {type(exc_info)}. Ignoring.')

        has_exception = actual_exc_info[0] is not None
        log_extra = extra.copy() if extra else {}

        # --- Suppress Console Handler (if needed) ---
        log_extra['suppress_console'] = has_exception and should_print_manual_rich_tb

        # --- Log the Record ---
        self._log(
            logging.ERROR,
            msg,
            args,
            exc_info=actual_exc_info,
            extra=log_extra,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
        )

        # --- Manual Rich Traceback Print (if needed) ---
        if has_exception and should_print_manual_rich_tb:
            show_locals_final = (
                show_locals if show_locals is not None else StandardLogger._show_locals_in_traceback_cls
            )
            self._print_rich_traceback(actual_exc_info, show_locals=show_locals_final)  # type: ignore


# =============================================================================
# Main Setup Function
# =============================================================================
def setup_logging(config: LoggerConfig) -> tuple[bool, Path | None]:
    """
    Initializes and configures the root logger based on LoggerConfig.

    Sets the global logger class to StandardLogger, so subsequent calls to
    `logging.getLogger(name)` will return configured StandardLogger instances.

    Parameters
    ----------
    config : LoggerConfig
        The configuration object specifying logger settings.

    Returns
    -------
    tuple[bool, Path | None]
        A tuple containing:
            - A boolean indicating if file logging was successfully enabled.
            - The actual Path object used for file logging, or None.

    Raises
    ------
    LoggerSetupError
        If critical errors occur during setup (e.g., directory permissions).
    """

    # Use default config if none provided
    effective_config = config if config is not None else LoggerConfig()

    # Helper for critical errors during setup
    def _raise_critical(msg: str, exc: Exception, *, re_raise: bool = False) -> None:
        logging.critical(f'LOGGER SETUP FAILURE: {msg}', exc_info=exc)
        if re_raise:
            raise exc
        raise LoggerSetupError(msg) from exc

    actual_log_path: Path | None = None
    file_logging_enabled = False
    file_logging_error_reason: str | None = None
    root_logger: StandardLogger | None = None  # Type hint adjusted

    try:
        # --- Validate Config ---
        try:
            effective_config.__post_init__()
        except Exception as e:
            logging.warning(f'LoggerConfig validation/normalization issue: {e}')

        # --- Install Uncaught Exception Hook ---
        if effective_config.use_rich_console and not effective_config.use_simple_tracebacks:
            try:
                _install_rich_traceback_hook(
                    _rich_console,
                    show_locals=effective_config.show_locals_on_exception,
                )
            except Exception as hook_e:
                logging.warning(f'Failed to install Rich traceback hook: {hook_e}', exc_info=hook_e)

        # --- File Path Determination ---
        # This section now handles adding the default suffix
        if effective_config.log_file_path is False:
            logging.debug('File logging explicitly disabled by config.')
            file_logging_error_reason = 'Explicitly disabled'

        elif effective_config.log_file_path is None:  # Auto-generate default path
            try:
                # CHANGE: Get the base path (stem) without extension
                base_log_path = _get_default_log_file_path(
                    effective_config.app_name,
                    effective_config.app_author,
                )
                # CHANGE: Determine suffix based on serialization config
                default_suffix = '.jsonl' if effective_config.log_file_serialize else '.log'
                # CHANGE: Apply the determined suffix
                actual_log_path = base_log_path.with_suffix(default_suffix)
                # Ensure parent dir exists (may have been created by _get_default_log_file_path)
                actual_log_path.parent.mkdir(parents=True, exist_ok=True)

            except LoggerSetupError as e_path:
                file_logging_error_reason = f'{e_path.args[0] if e_path.args else e_path}'
                logging.exception(f'Config Error: {file_logging_error_reason}. File logging disabled.')
            except Exception as e_path_unexp:
                file_logging_error_reason = 'Unexpected error generating default log path'
                logging.exception(
                    f'{file_logging_error_reason}. File logging disabled.', exc_info=e_path_unexp,
                )

        elif isinstance(effective_config.log_file_path, (str, Path)):  # User-specified path
            user_path = Path(effective_config.log_file_path).resolve()
            try:
                user_path.parent.mkdir(parents=True, exist_ok=True)
                if not os.access(str(user_path.parent), os.W_OK):
                    raise PermissionError(f'No write permission for log directory: {user_path.parent}')
                # CHANGE: Assign the user's resolved path directly, respecting their extension
                actual_log_path = user_path
            except PermissionError as e_perm:
                file_logging_error_reason = f'Permission denied for log directory: {user_path.parent}'
                logging.exception(
                    f'Config Error: {file_logging_error_reason}. File logging disabled.', exc_info=e_perm,
                )
            except Exception as e_user_path:
                file_logging_error_reason = f"Error accessing specified log path '{user_path}'"
                logging.exception(
                    f'{file_logging_error_reason}. File logging disabled.', exc_info=e_user_path,
                )

        else:  # Invalid type for log_file_path
            file_logging_error_reason = (
                f'Invalid log_file_path type: {type(effective_config.log_file_path)}.'
            )
            logging.error(f'Config Error: {file_logging_error_reason}. File logging disabled.')

        # Ensure path is None if any error occurred during path setup
        if file_logging_error_reason and actual_log_path is not None:
            actual_log_path = None

        # --- Determine Minimum Processing Level & Configure Root Logger ---
        min_level = effective_config.console_level
        if actual_log_path:
            min_level = min(min_level, effective_config.file_level)

        root_logger = _configure_root_logger(StandardLogger, min_level)  # Type hint fixed here

        # --- Set Class Variables on StandardLogger ---
        StandardLogger._show_locals_in_traceback_cls = effective_config.show_locals_on_exception
        StandardLogger._use_rich_console_cls = effective_config.use_rich_console
        StandardLogger._use_simple_tracebacks_cls = effective_config.use_simple_tracebacks

        # --- Setup Loguru Sinks & Interception ---
        loguru_sink_handler.remove()
        # Type hint check: root_logger will be StandardLogger or None if setup fails earlier
        if root_logger:
            root_logger.addHandler(LoguruInterceptHandler())
        else:
            # This case should be unlikely if _configure_root_logger raises on failure, but defensive
            _raise_critical(
                'Root logger configuration failed unexpectedly.', RuntimeError('Root logger is None'),
            )

        # --- Configure Console Output ---
        if effective_config.use_rich_console:
            rich_handler = _setup_rich_console_handler(
                _rich_console,
                effective_config.console_level,
                effective_config.console_time_format,
                use_simple_tracebacks=effective_config.use_simple_tracebacks,
            )
            rich_handler.tracebacks_show_locals = (
                effective_config.show_locals_on_exception and not effective_config.use_simple_tracebacks
            )
            if root_logger:  # Add handler only if root logger exists
                root_logger.addHandler(rich_handler)
        else:
            _configure_loguru_console_sink(
                effective_config.console_level,
                effective_config.console_time_format,
            )

        # --- Configure File Sink (Via Loguru) ---
        if actual_log_path:  # Proceed only if a valid path was determined
            try:
                _setup_loguru_file_sink(
                    log_file_path=actual_log_path,  # Use the potentially suffixed path
                    level=effective_config.file_level,
                    file_format=effective_config.log_file_format,  # Only used if serialize=False
                    rotation=effective_config.log_file_rotation,
                    retention=effective_config.log_file_retention,
                    serialize=effective_config.log_file_serialize,
                )
                file_logging_enabled = True
            except LoggerSetupError as e_sink:
                file_logging_error_reason = (
                    e_sink.args[0] if e_sink.args else 'Loguru file sink configuration failed'
                )
                logging.exception(f'{file_logging_error_reason}. File logging disabled.', exc_info=e_sink)
            except Exception as e_sink_unexp:
                file_logging_error_reason = 'Unexpected error setting up file sink'
                logging.exception(
                    f'{file_logging_error_reason}. File logging disabled.', exc_info=e_sink_unexp,
                )
            # If sink setup failed, ensure we report it as disabled
            if not file_logging_enabled:
                actual_log_path = None  # Clear path if sink setup failed

        # --- Final Summary Log ---
        status = 'ENABLED' if file_logging_enabled else 'DISABLED'
        # Ensure level_name uses the config value, not the potentially adjusted min_level
        level_name = logging.getLevelName(effective_config.file_level)
        path_info = (
            f'Path: {actual_log_path}'
            if actual_log_path
            else f'Reason: {file_logging_error_reason or "N/A"}'
        )
        console_type = 'Rich' if effective_config.use_rich_console else 'Loguru StdErr'
        tb_cfg = effective_config.use_simple_tracebacks
        tb_type = 'Simple' if tb_cfg else ('Rich' if effective_config.use_rich_console else 'Loguru')
        locals_info = (
            f'(Locals: {"Yes" if effective_config.show_locals_on_exception and not tb_cfg else "No"})'
            if not tb_cfg
            else ''
        )

        summary_log = logging.getLogger('standard_logger.setup')
        summary_log.info(
            f'Logging Setup: Console={console_type}@{logging.getLevelName(effective_config.console_level)} '
            f'Traceback={tb_type}{locals_info} | '
            f'File={status}@{level_name} {path_info}',  # Path info now reflects final path/reason
        )

    # --- Critical Error Handling ---
    except LoggerSetupError as critical_error:
        _raise_critical(f'CRITICAL LOGGER SETUP FAILED: {critical_error}', critical_error, re_raise=True)
    except Exception as unexpected_error:
        _raise_critical('UNEXPECTED CRITICAL LOGGER SETUP ERROR', unexpected_error)
    else:
        return file_logging_enabled, actual_log_path
    return False, None
