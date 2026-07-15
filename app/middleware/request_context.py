"""Middleware that provides request-scoped context.

Generates or propagates X-Request-ID and stores request metadata
in contextvars for use by the structured logging system.
"""

import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import correlation_id_var, request_id_var, user_id_var


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Capture request metadata into contextvars.

    - Generates X-Request-ID if not present in the incoming request
    - Stores request_id and correlation_id in contextvars
    - Clears contextvars in a finally block
    """

    async def dispatch(self, request: Request, call_next):
        # Generate or propagate request ID
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        correlation_id = request.headers.get("X-Correlation-ID", req_id)

        # Set context vars
        request_id_var.set(req_id)
        correlation_id_var.set(correlation_id)

        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            # Clear context vars to prevent leakage between requests
            request_id_var.set("")
            user_id_var.set("")
            correlation_id_var.set("")
