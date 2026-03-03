"""
Security middleware for CarbCount.

Three layers:
  1. Bearer token authentication (keeps unauthorized users out)
  2. Rate limiting (prevents runaway usage even with valid auth)
  3. CORS (locks down cross-origin requests in production)

The Anthropic API key is NEVER exposed to the LLM context or any client.
It lives only in environment variables (Railway secrets in production).
"""

import time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import settings


# Paths that do NOT require authentication
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json"}
PUBLIC_PREFIXES = ("/app",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token on all /api/ routes."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public paths
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Skip auth for non-API paths
        if not path.startswith("/api/"):
            return await call_next(request)

        # Validate Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {settings.APP_SECRET_TOKEN}":
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized. Provide a valid Bearer token."}
            )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting.

    Limits:
      - 30 requests per hour to /api/estimate
      - 200 requests per day to /api/estimate
    """

    def __init__(self, app):
        super().__init__(app)
        self.hourly_requests: dict[str, list[float]] = defaultdict(list)
        self.daily_requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Only rate limit the expensive endpoint
        if request.url.path != "/api/estimate" or request.method != "POST":
            return await call_next(request)

        now = time.time()
        client_ip = request.client.host if request.client else "unknown"

        # Clean old entries
        hour_ago = now - 3600
        day_ago = now - 86400
        self.hourly_requests[client_ip] = [t for t in self.hourly_requests[client_ip] if t > hour_ago]
        self.daily_requests[client_ip] = [t for t in self.daily_requests[client_ip] if t > day_ago]

        # Check limits
        if len(self.hourly_requests[client_ip]) >= settings.RATE_LIMIT_PER_HOUR:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Maximum {settings.RATE_LIMIT_PER_HOUR} estimates per hour",
                    "retry_after_seconds": int(3600 - (now - self.hourly_requests[client_ip][0]))
                }
            )

        if len(self.daily_requests[client_ip]) >= settings.RATE_LIMIT_PER_DAY:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Daily rate limit exceeded",
                    "detail": f"Maximum {settings.RATE_LIMIT_PER_DAY} estimates per day"
                }
            )

        # Record this request
        self.hourly_requests[client_ip].append(now)
        self.daily_requests[client_ip].append(now)

        return await call_next(request)
