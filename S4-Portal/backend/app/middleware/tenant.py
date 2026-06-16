"""Tenant resolution middleware.

Reads the Host header, extracts the subdomain (the part before the first dot),
and stores it in request.state.tenant_id.

Examples:
  Host: demo.s4log.app        → tenant_id = "demo"
  Host: acme.s4log.app        → tenant_id = "acme"
  Host: localhost (no dot)    → tenant_id = "localhost" (useful for local dev)
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        host = request.headers.get("host", "")
        # Strip port if present (e.g. demo.s4log.app:8000)
        hostname = host.split(":")[0]
        subdomain = hostname.split(".")[0] if "." in hostname else hostname
        request.state.tenant_id = subdomain or "default"
        return await call_next(request)
