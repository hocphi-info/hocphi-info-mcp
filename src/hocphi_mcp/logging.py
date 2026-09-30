"""structlog -> JSON, moi ban ghi 1 dong tren stdout.

Ban toi thieu cho U3: `severity` (Cloud Logging doc truong nay de phan loai muc do) va
`message`. U5 them `logging.googleapis.com/trace`, request-id, su kien `tool_call`.
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SEVERITY = {
    "debug": "DEBUG",
    "info": "INFO",
    "warning": "WARNING",
    "error": "ERROR",
    "critical": "CRITICAL",
}


def _add_severity(
    _: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict["severity"] = _SEVERITY.get(method_name, "DEFAULT")
    return event_dict


def _rename_event_to_message(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict["message"] = event_dict.pop("event")
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Goi 1 lan luc khoi dong process."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_severity,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _rename_event_to_message,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
