"""The only place OpenTelemetry and logging are configured.

**One sink** (`architecture.md`, "Observability"): logs, traces and metrics from
the web process, the worker and every door go to the one
`OTEL_EXPORTER_OTLP_ENDPOINT` — ClickStack — and nothing writes anywhere else.
No second logging config, no file handler, no separate APM agent, no `print`.

Two halves, and they are deliberately decoupled:

* **Tracing is always on.** A real `TracerProvider` is installed whether or not
  an endpoint is configured, because `trace_id` and `span_id` go onto every log
  line and a no-op provider would leave those blank on a laptop — exactly where
  you are reading them. Spans with nowhere to go cost a few allocations.
* **Export is on only when an endpoint is set.** No endpoint (a laptop, the
  test suite) means no exporter, no instrumentation patching and no network:
  the process behaves identically, it just does not ship. Set the endpoint
  (`docker compose --profile observability up`) and the same code ships.

`configure()` is idempotent and is called from `apps.core.apps.CoreConfig.ready`,
which is the one point every entrypoint passes through — `manage.py`, the ASGI
server, the Temporal worker and pytest alike — so no entrypoint has to remember.

The Temporal side is `TracingInterceptor`, attached in `apps.workflows.client`
so that a trace crosses the process boundary between the service that started a
workflow and the worker that ran it.
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

# The name every span, log record and metric is attributed to. `web` and
# `worker` are the two this template ships; a product adds its own by setting
# DJB_SERVICE_NAME on the process.
DEFAULT_SERVICE_NAME = "web"

# The instrumentation this process turns on when export is enabled. Each is
# imported lazily, so a deployment that trims one of the packages still starts.
INSTRUMENTORS: tuple[tuple[str, str], ...] = (
    ("opentelemetry.instrumentation.django", "DjangoInstrumentor"),
    ("opentelemetry.instrumentation.psycopg", "PsycopgInstrumentor"),
    ("opentelemetry.instrumentation.redis", "RedisInstrumentor"),
    ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
)

_configured = False


def _add_trace_ids(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Put the current span's ids on the log line.

    This is the join between a log search and a trace waterfall: without it,
    "show me the logs for this slow request" is a text search over timestamps.
    """
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def _configure_structlog() -> None:
    """JSON on stdout, with the bound context and the trace ids on every line.

    `merge_contextvars` is what makes `core.context.bind()` at the door reach a
    log line written four calls deeper without anybody passing it along.

    `cache_logger_on_first_use` stays off on purpose: it is a real speed-up and
    it makes `structlog.testing.capture_logs` silently miss loggers that were
    built before the test started, which turns an observability test into one
    that cannot fail.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            _add_trace_ids,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def _resource() -> Resource:
    from django.conf import settings

    return Resource.create(
        {
            "service.name": str(getattr(settings, "OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)),
            "service.version": str(getattr(settings, "TEMPLATE_VERSION", "0.1.0")),
            "deployment.environment": str(getattr(settings, "DJB_ENVIRONMENT", "local")),
        }
    )


def _start_export(endpoint: str, provider: TracerProvider) -> None:
    """Ship spans and log records to the one endpoint, and patch the libraries."""
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )

    logger_provider = LoggerProvider(resource=provider.resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )
    logging.getLogger().addHandler(LoggingHandler(logger_provider=logger_provider))

    for module_name, class_name in INSTRUMENTORS:
        try:
            module = __import__(module_name, fromlist=[class_name])
        except ImportError:  # pragma: no cover - a trimmed deployment
            continue
        getattr(module, class_name)().instrument(tracer_provider=provider)


def configure() -> None:
    """Install logging and tracing. Idempotent; called from `CoreConfig.ready`."""
    global _configured
    if _configured:
        return
    _configured = True

    from django.conf import settings

    _configure_structlog()

    provider = TracerProvider(resource=_resource())
    trace.set_tracer_provider(provider)

    endpoint = str(getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")).rstrip("/")
    if endpoint:
        _start_export(endpoint, provider)


def get_tracer(name: str) -> Tracer:
    """The tracer for a module. `core.service` uses it for every service span."""
    return trace.get_tracer(name)
