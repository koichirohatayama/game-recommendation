"""構造化ロギングのセットアップとヘルパー。"""

from __future__ import annotations

import logging
from typing import Any

import structlog

DEFAULT_LOG_LEVEL = "INFO"


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level

    normalized = level.upper()
    if normalized in logging._nameToLevel:  # type: ignore[attr-defined]
        return logging._nameToLevel[normalized]  # type: ignore[attr-defined]
    msg = f"Unsupported log level: {level}"
    raise ValueError(msg)


def configure_logging(level: str | int = DEFAULT_LOG_LEVEL, *, json_output: bool = False) -> None:
    """structlog を用いたロギング設定を行う。

    Args:
        level: 文字列または数値で表現したログレベル。
        json_output: True の場合 JSON 形式で出力する。
    """

    log_level = _coerce_level(level)
    logging.basicConfig(level=log_level, format="%(message)s")

    processors: list[structlog.types.Processor] = [
        structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """共有ロガーを取得し、必要に応じて初期バインド値を設定。"""

    logger = structlog.stdlib.get_logger(name)
    if initial_values:
        return logger.bind(**initial_values)
    return logger


__all__ = ["DEFAULT_LOG_LEVEL", "configure_logging", "get_logger"]
