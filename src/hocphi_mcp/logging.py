"""structlog -> JSON, moi ban ghi 1 dong tren stdout.

Ban toi thieu cho U3: `severity` (Cloud Logging doc truong nay de phan loai muc do) va
`message`. U5 them `logging.googleapis.com/trace`, request-id, su kien `tool_call`.
"""

import hashlib
import logging
import os
import re
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


def _severity_from_level(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Cho log cua thu vien (stdlib): `level` -> `severity`."""
    event_dict["severity"] = _SEVERITY.get(event_dict.pop("level", "info"), "DEFAULT")
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Goi 1 lan luc khoi dong process.

    Ca log cua ta (structlog) lan log cua thu vien (uvicorn, mcp... qua stdlib `logging`)
    deu ra MOT dong JSON tren stdout, de Cloud Logging doc duoc `severity`/`message`."""
    threshold = logging.getLevelNamesMapping()[level.upper()]
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_severity,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _rename_event_to_message,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(threshold),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,  # de test doi duoc stdout; chi phi khong dang ke
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                _severity_from_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _rename_event_to_message,
                structlog.processors.JSONRenderer(ensure_ascii=False),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(threshold)
    # httpx ghi 1 dong INFO cho moi request — trung voi su kien `upstream_call` cua ta.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Ngu canh request (U5) ───────────────────────────────────────────────────
_SALT = os.urandom(
    16
)  # rieng tung process: bam IP khong noi duoc giua cac instance/lan chay


def hash_client(ip: str) -> str:
    """Bam cat ngan cua IP de log nhom cac request cung nguon MA KHONG luu IP tho."""
    return hashlib.sha256(_SALT + ip.encode()).hexdigest()[:12]


def parse_cloud_trace(header: str | None, project: str | None) -> str | None:
    """`X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1` -> `projects/P/traces/TRACE_ID`.

    Cloud Logging dung truong `logging.googleapis.com/trace` de gan dong log vao trace cua
    request. Khong co project id (chay local) thi khong phat ra truong nay."""
    if not header or not project:
        return None
    trace_id = header.split("/", 1)[0].strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", trace_id):
        return None
    return f"projects/{project}/traces/{trace_id}"
