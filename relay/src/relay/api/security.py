"""Loopback-only HTTP boundary with header auth and streaming-safe body limits."""

from __future__ import annotations

import hmac
import uuid
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 70 * 1024
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "testserver"})
SECURITY_HEADERS = {
    "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cache-control": "no-store",
}


def error_response(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": request_id}},
        status_code=status,
    )


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        headers = Headers(scope=scope)

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = (
                    list(message.get("headers", []))
                    + [(key.encode(), value.encode()) for key, value in SECURITY_HEADERS.items()]
                    + [(b"x-request-id", request_id.encode())]
                )
            await send(message)

        async def reject(status: int, code: str, message: str) -> None:
            await error_response(status, code, message, request_id)(scope, receive, secured_send)

        hosts = headers.getlist("host")
        try:
            authority = urlsplit("//" + (hosts[0] if len(hosts) == 1 else ""))
            host = authority.hostname
            port = authority.port
            if (
                host not in ALLOWED_HOSTS
                or authority.username is not None
                or authority.password is not None
                or authority.path
                or authority.query
                or authority.fragment
            ):
                raise ValueError
        except ValueError:
            await reject(400, "INVALID_HOST", "host is not allowed")
            return
        origins = headers.getlist("origin")
        if origins:
            try:
                origin = urlsplit(origins[0])
                scheme = scope.get("scheme", "http")
                default_port = 443 if scheme == "https" else 80
                if (
                    len(origins) != 1
                    or origin.scheme != scheme
                    or origin.hostname != host
                    or (origin.port or default_port) != (port or default_port)
                    or origin.path
                    or origin.query
                    or origin.fragment
                    or origin.username is not None
                    or origin.password is not None
                ):
                    raise ValueError
            except ValueError:
                await reject(403, "INVALID_ORIGIN", "same-origin requests only")
                return
        path = scope["path"]
        if path == "/api" or path.startswith("/api/") or path == "/metrics":
            credentials = headers.getlist("authorization")
            supplied = credentials[0] if len(credentials) == 1 else ""
            scheme, _, value = supplied.partition(" ")
            valid = hmac.compare_digest(value.encode("utf-8"), self.token)
            if scheme.lower() != "bearer" or not valid:
                response = error_response(401, "UNAUTHORIZED", "bearer token required", request_id)
                response.headers["WWW-Authenticate"] = "Bearer"
                await response(scope, receive, secured_send)
                return
        lengths = headers.getlist("content-length")
        if lengths:
            try:
                if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                    raise ValueError
                length = int(lengths[0])
            except ValueError:
                await reject(400, "INVALID_REQUEST", "invalid content length")
                return
            if length > MAX_BODY_BYTES:
                await reject(413, "REQUEST_TOO_LARGE", "request body exceeds limit")
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                await reject(413, "REQUEST_TOO_LARGE", "request body exceeds limit")
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, secured_send)
