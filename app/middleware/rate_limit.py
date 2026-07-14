"""
Middleware de Rate Limiting para proteger la API contra abuso.

Límites configurados:
- 100 requests/minuto por IP
- 20 generaciones/minuto por usuario autenticado

SOUL.md §5: protección contra abuso y DoS
"""

import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware simple de rate limiting basado en memoria.
    
    Nota: Para producción con múltiples workers, usar Redis o similar.
    Para Alpha con un solo proceso, esta implementación es suficiente.
    """
    
    def __init__(
        self,
        app,
        requests_per_minute: int = 100,
        generation_requests_per_minute: int = 20
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.generation_requests_per_minute = generation_requests_per_minute
        
        # Almacena: {identifier: [(timestamp, path), ...]}
        self.request_history: dict[str, list[tuple[float, str]]] = defaultdict(list)
    
    def _get_identifier(self, request: Request) -> str:
        """
        Obtiene identificador único del cliente.
        
        Prioridad:
        1. user_id si está autenticado
        2. IP address
        """
        # Intentar obtener user_id del estado (si el middleware de auth lo puso)
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"
        
        # Fallback a IP
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"
    
    def _clean_old_requests(self, requests: list[tuple[float, str]], window_seconds: int = 60):
        """Elimina requests fuera de la ventana de tiempo."""
        cutoff = time.time() - window_seconds
        return [(ts, path) for ts, path in requests if ts > cutoff]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Procesa el request aplicando rate limiting.
        """
        # Ignorar requests a endpoints estáticos y docs
        if request.url.path.startswith(("/media", "/docs", "/redoc", "/openapi.json")):
            return await call_next(request)
        
        identifier = self._get_identifier(request)
        current_time = time.time()
        path = request.url.path
        
        # Obtener historial y limpiar
        history = self.request_history[identifier]
        history = self._clean_old_requests(history)
        
        # Verificar límite general
        if len(history) >= self.requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes. Por favor intenta nuevamente en un minuto.",
                headers={"Retry-After": "60"}
            )
        
        # Verificar límite específico de generaciones
        if path.startswith("/api/v1/generations") and request.method == "POST":
            generation_count = sum(1 for _, p in history if p.startswith("/api/v1/generations"))
            if generation_count >= self.generation_requests_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Límite de generaciones alcanzado. Por favor intenta nuevamente en un minuto.",
                    headers={"Retry-After": "60"}
                )
        
        # Registrar request
        history.append((current_time, path))
        self.request_history[identifier] = history
        
        # Continuar con el request
        response = await call_next(request)
        
        # Agregar headers de rate limit info
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, self.requests_per_minute - len(history))
        )
        
        return response
