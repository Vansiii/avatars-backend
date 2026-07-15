"""Middleware that attaches security headers to all HTTP responses.

Headers applied:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: no-referrer
- Permissions-Policy: restricted set
- Content-Security-Policy (strict for API, relaxed for docs)
- Strict-Transport-Security (behind ENABLE_HSTS flag)
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings


_API_CSP = (
    "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

_DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://cdn.jsdelivr.net; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Headers applied to all responses
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )

        # CSP: strict for API, relaxed for docs
        if request.url.path in _DOCS_PATHS:
            csp_value = _DOCS_CSP
        else:
            csp_value = _API_CSP

        if settings.CSP_REPORT_ONLY:
            csp_header = "Content-Security-Policy-Report-Only"
        else:
            csp_header = "Content-Security-Policy"

        csp_line = csp_value
        if settings.CSP_REPORT_URI:
            csp_line += f"; report-uri {settings.CSP_REPORT_URI}"

        response.headers[csp_header] = csp_line

        # HSTS (only when enabled)
        if settings.ENABLE_HSTS:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
