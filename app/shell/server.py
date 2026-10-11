"""Loopback-only, read-only Foundation HTTP server with an exact route allowlist."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import socket
from pathlib import Path
from contextlib import nullcontext
from contracts.live.market_agent import AgentError
from urllib.parse import parse_qs, urlsplit
from app.shell.render import CSS, render_page
from shared.logging.timing import RequestTimings, stage, timed_request

logger = logging.getLogger("trading_lab.http")


def make_server(application, port=8765, *, diagnostics=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TradingLab/0.1"
        sys_version = ""

        def _send(self, status, content, content_type="text/plain; charset=utf-8", extra_headers=None):
            if getattr(self,'_timing',None) is not None:self._timing['status']=status
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    with stage('socket_write'):self.wfile.write(content)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,TimeoutError):
                    if getattr(self,'_timing',None) is not None:self._timing['disconnected']=True

        def _json(self, value, status=200):
            with stage('serialization'):body=json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _module_route(self, method, path, payload=None):
            for router in application.routers:
                with stage('router.'+type(router).__name__):response = router.route(method, path, payload)
                if response is not None:
                    status, body, content_type = response
                    if content_type:
                        self._send(status, body, content_type)
                    else:
                        self._json(body, status)
                    return True
            return False

        @timed_request
        def do_GET(self):
            try:
                parts = urlsplit(self.path)
                path = parts.path
                query = {key: values[-1] for key, values in parse_qs(parts.query,keep_blank_values=True).items()}
                if path == "/":
                    first = next((module for module in application.registry.modules if module.enabled), None)
                    return self._send(302, b"", extra_headers={"Location": first.route if first else "/healthz"})
                if path == "/healthz":
                    value={"service": "Trading Lab", "status": "UP"}
                    if getattr(self.server,'instance_id',None):value['instance_id']=self.server.instance_id
                    if application.runtime:value['progress']=application.live_loop.last_progress
                    return self._json(value)
                if path=='/internal/runtime':
                    if not self._runtime_authorized():return self._json({'error':'ACCESS_DENIED'},403)
                    return self._json(application.runtime.status())
                if path == "/favicon.ico":
                    return self._send(204,b"","image/x-icon")
                if path == "/api/health":
                    return self._json(application.system_health.read())
                if path == "/api/modules":
                    return self._json({"modules": [module.declaration() for module in application.registry.modules]})
                if path == "/assets/forms.css":
                    return self._send(200,Path(__file__).with_name("static").joinpath("forms.css").read_bytes(),"text/css; charset=utf-8")
                if path == "/assets/shell.css":
                    return self._send(200, CSS, "text/css; charset=utf-8")
                if self._module_route("GET", path, query):
                    return
                module = application.registry.resolve(path)
                if module:
                    with stage('page_render'):body=render_page(application.registry, module)
                    return self._send(200, body, "text/html; charset=utf-8")
                self._send(404, b"Not found")
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,TimeoutError):
                if getattr(self,'_timing',None) is not None:self._timing['disconnected']=True
            except Exception:
                logger.error("Request failed")
                self._send(500, b"Internal error; inspect local diagnostics")

        do_HEAD = do_GET

        def _method_not_allowed(self):
            self._send(405, b"Foundation endpoints are read-only", extra_headers={"Allow": "GET, HEAD"})

        def do_POST(self):
            return self._write_method('POST')

        def do_PUT(self):
            return self._write_method('PUT')

        def _write_method(self,method):
            path = urlsplit(self.path).path
            if path=='/internal/shutdown' and method=='POST':
                if not self._runtime_authorized():return self._json({'error':'ACCESS_DENIED'},403)
                return self._json(application.runtime.shutdown(),202)
            allowed=any((router.accepts_post(path) if method=='POST' else getattr(router,'accepts_put',lambda _:False)(path)) for router in application.routers)
            if not allowed:
                return self._send(404,b"Not found")
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected_host or self.headers.get("Origin") not in (None, "http://" + expected_host):
                return self._json({"error": "ORIGIN_REJECTED"}, 403)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self._json({"error": "JSON_REQUIRED"}, 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192 or self.headers.get("Transfer-Encoding"):
                    return self._json({"error": "INVALID_BODY_SIZE"}, 413)
                def invalid_constant(value):
                    raise ValueError("Non-finite JSON")
                payload = json.loads(self.rfile.read(length), parse_constant=invalid_constant)
                if not isinstance(payload, dict):
                    raise ValueError("Expected object")
                guard = getattr(application, 'command_guard', None)
                with application.runtime.command(path) if application.runtime else nullcontext():
                    with guard(path) if guard else nullcontext():
                        self._module_route(method, path, payload)
            except AgentError as error:
                self._json({'error':error.code,'message':str(error)},error.status)
            except (ValueError, UnicodeError):
                self._json({"error": "INVALID_JSON"}, 400)
            except Exception:
                logger.error("Request failed")
                self._json({"error": "COMPONENT_ERROR", "message": "组件异常；检查本地状态。"}, 500)

        do_PATCH = do_DELETE = do_OPTIONS = _method_not_allowed

        def _runtime_authorized(self):
            import secrets
            expected=getattr(self.server,'control_token','')
            return bool(expected) and self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and self.headers.get('Origin') is None and secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+expected)

        def log_message(self, format, *args):
            logger.debug("HTTP request completed: %s", args[1] if len(args) > 1 else "unknown")

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = False
        # A page load plus read polling can exceed the default five pending
        # connections. Keep a bounded backlog instead of refusing that burst.
        request_queue_size = 64
        def server_close(self):
            super().server_close()
            if hasattr(self,'performance'):self.performance.close()

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(10)
            return connection, address

    server=Server(("127.0.0.1", port), Handler)
    server.performance=diagnostics or RequestTimings.configured()
    return server
