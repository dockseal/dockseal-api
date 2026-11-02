import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.openai import OpenAIIntegration

from app.core.config import get_settings

FILTERED = "[filtrado]"
MAX_EXCEPTION_VALUE = 300

_SENSITIVE_FRAGMENTS = (
    "password", "senha", "token", "secret", "api_key", "apikey",
    "authorization", "cookie", "jwt",
)
_SENSITIVE_KEYS = {
    "username", "email", "prompt", "prompts", "content", "text",
    "extracted_text", "file", "files", "document", "documents",
    "body", "messages", "input", "output", "cpf", "cnpj", "phone", "telefone",
}


def _is_sensitive(key) -> bool:
    name = str(key).lower()
    return name in _SENSITIVE_KEYS or any(f in name for f in _SENSITIVE_FRAGMENTS)


def _redact(value, depth: int = 0):
    if depth > 6:
        return FILTERED
    if isinstance(value, dict):
        return {
            k: FILTERED if _is_sensitive(k) else _redact(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in value]
    return value


def _scrub(event, hint):
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        if "headers" in request:
            request["headers"] = _redact(request["headers"])

    # Do usuário, mantém só o id (sem e-mail, nome ou IP).
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if "id" in user else {}

    if "extra" in event:
        event["extra"] = _redact(event["extra"])

    crumbs = event.get("breadcrumbs")
    values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
    for crumb in values or []:
        if isinstance(crumb, dict) and "data" in crumb:
            crumb["data"] = _redact(crumb["data"])

    # Mensagens de exceção longas (ex.: erros de validação) podem repetir o conteúdo enviado.
    exceptions = (event.get("exception") or {}).get("values") or []
    for exc in exceptions:
        value = exc.get("value")
        if isinstance(value, str) and len(value) > MAX_EXCEPTION_VALUE:
            exc["value"] = value[:MAX_EXCEPTION_VALUE] + "...[truncado]"

    return event


def _make_traces_sampler(rate: float):
    def sampler(sampling_context):
        path = (sampling_context.get("asgi_scope") or {}).get("path", "")
        if path == "/health":
            return 0
        parent = sampling_context.get("parent_sampled")
        if parent is not None:
            return 1.0 if parent else 0
        return rate

    return sampler


def init_sentry() -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        traces_sampler=_make_traces_sampler(settings.sentry_traces_sample_rate),
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        integrations=[
            # Logs não viram breadcrumb nem evento: podem conter texto de documentos.
            # Os erros chegam ao Sentry pelas exceções, não pelos logs.
            LoggingIntegration(level=None, event_level=None),
            # Mede as chamadas à OpenAI sem gravar prompts nem respostas.
            OpenAIIntegration(include_prompts=False),
        ],
        before_send=_scrub,
        before_send_transaction=_scrub,
    )


def report_exception(exc: BaseException, **tags: str) -> None:
    """Reporta uma exceção tratada, com tags. Não faz nada se o Sentry estiver desligado."""
    with sentry_sdk.new_scope() as scope:
        for key, value in tags.items():
            scope.set_tag(key, value)
        sentry_sdk.capture_exception(exc)