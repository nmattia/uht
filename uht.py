"""
Minimal HTTP server for MicroPython and CircuitPython.

Supports HTTP/1.0 request parsing, routing based on method and path, and response generation using asyncio streams.

Example:
```python
import uht

server = uht.HTTPServer()

@server.route("/hello/<name>")
async def greet(req, resp, name):
    await resp.send("Hello, " + name)

server.run("0.0.0.0", 8080)
```

See the main :class:`HTTPServer` class for details.

Project README, examples and more: https://github.com/nmattia/uht

Copyright 2025 `Nicolas Mattia <https://github.com/nmattia>`_
"""

import logging
import asyncio
import gc
import errno

# TYPING_START
# typing related lines that get stripped during build
# (micropython doesn't support them)
from typing import Callable, TypedDict, Literal, Any, Coroutine

# As per https://www.rfc-editor.org/rfc/rfc9112.html#name-request-line
RequestLine = TypedDict(
    "RequestLine",
    {
        "method": bytes,
        "target": bytes,
        "version": tuple[int, int],  # major.minor
    },
)

type Handler = Callable
Params = TypedDict(
    "Params",
    {
        "save_headers": list[bytes],
    },
)

# A route definition
# (method, path, handler, params)
type Route = tuple[bytes, bytes, Handler, Params]

type PathParameters = list[(bytes, bytes)]  # list of param name and param value
# TYPING_END

_log = logging.getLogger("WEB")


def _match_url_paths(route_path: bytes, req_path: bytes) -> None | PathParameters:
    """
    Match a request path against a route path and extract any path parameters.

    Parameters:
        route_path: The route pattern (e.g., b'/user/<id>').
        req_path: The requested URL path (e.g., b'/user/42').

    Returns:
        A list of (parameter name, parameter value) pairs if matched; otherwise None.
    """
    path_params = []

    route_parts = route_path.split(b"/")
    req_parts = req_path.split(b"/")

    if len(route_parts) != len(req_parts):
        return None

    # go through the parts, accumulating any path parameters found
    # along the way.
    for route_part, req_part in zip(route_parts, req_parts):
        if route_part.startswith(b"<") and route_part.endswith(b">"):
            param_key = route_part[1:-1]
            param_val = req_part

            path_params.append((param_key, param_val))
            continue

        if route_part != req_part:
            return None

    return path_params


class HTTPException(Exception):
    """HTTP protocol exceptions"""

    def __init__(self, code=400):
        self.code = code


# per https://www.rfc-editor.org/rfc/rfc9110#table-4
_SUPPORTED_METHODS = [
    b"GET",
    b"HEAD",
    b"POST",
    b"PUT",
    b"DELETE",
    b"CONNECT",
    b"OPTIONS",
    b"TRACE",
]


def _parse_request_line(line: bytes) -> RequestLine | None:
    """
    Parse an HTTP request line according to RFC 9112.

    As per https://www.rfc-editor.org/rfc/rfc9112.html#name-request-line
        request-line   = method SP request-target SP HTTP-version
    where SP is "single space"
    where method is defined in https://www.rfc-editor.org/rfc/rfc9110#section-9
    where request-target is arbitrary for our purposes
    where HTTP-version is 'HTTP-version  = HTTP-name "/" DIGIT "." DIGIT'
        (https://www.rfc-editor.org/rfc/rfc9112.html#name-http-version)

    Parameters:
        line: The raw request line as bytes (e.g., b'GET / HTTP/1.1').

    Returns:
        A dictionary with 'method', 'target', and 'version', or None if invalid.
    """
    fragments = line.split(b" ")
    if len(fragments) != 3:
        return None

    if fragments[0] not in _SUPPORTED_METHODS:
        return None

    if not fragments[1]:
        return None

    http_version_fragments = fragments[2].split(b"/")
    if len(http_version_fragments) != 2:
        return None

    if http_version_fragments[0] != b"HTTP":
        return None

    version_fragments = http_version_fragments[1].split(b".")

    if len(version_fragments) != 2:
        return None

    try:
        version_major = int(version_fragments[0])
        version_minor = int(version_fragments[1])
    except ValueError:  # failed to parse as int
        return None

    return {
        "method": fragments[0],
        "target": fragments[1],
        "version": (version_major, version_minor),
    }


class Request:
    """HTTP Request class

    :class:`HTTPServer`

    """

    def __init__(self, _reader):
        self.reader: asyncio.StreamReader = _reader
        # headers are 'None' until `_read_headers` is called
        self.headers: None | dict[bytes, bytes] = None
        self.method: bytes = b""
        self.path: bytes = b""
        self.query_string = b""
        self.version: Literal["1.0"] | Literal["1.1"] = "1.0"
        self.params: Params = {
            "save_headers": [],
        }

    async def _read_request_line(self):
        """
        Read and parse the HTTP request line from the client.

        Updates self.method, self.path, and self.query_string.

        Raises:
            HTTPException(400): If the request line is malformed.

        This is a coroutine.
        """
        while True:
            rl_raw = await self.reader.readline()
            # skip empty lines
            if rl_raw == b"\r\n" or rl_raw == b"\n":
                continue
            break

        rl = _parse_request_line(rl_raw)
        if not rl:
            raise HTTPException(400)

        self.method = rl["method"]

        url_frags = rl["target"].split(b"?", 1)

        self.path = url_frags[0]
        if len(url_frags) > 1:
            self.query_string = url_frags[1]

    async def _read_headers(self, save_headers=[]):
        """
        Read HTTP headers from the stream and store selected ones.

        Parameters:
            save_headers: List of header names (bytes or strings) to preserve in self.headers.

        Raises:
            HTTPException(400): If a header line is malformed.

        This is a coroutine.
        """
        self.headers = {}
        while True:
            gc.collect()
            line = await self.reader.readline()
            if line == b"\r\n":
                break
            frags = line.split(b":", 1)
            if len(frags) != 2:
                raise HTTPException(400)

            if frags[0].lower() in [header.lower() for header in save_headers]:
                self.headers[frags[0].lower()] = frags[1].strip()


class Response:
    """HTTP Response class"""

    VERSION = b"1.0"  # we only support 1.0

    def __init__(self, _writer):
        self._writer: asyncio.StreamWriter = _writer

        # Request line fields

        self._status_code: int = 200
        self._reason_phrase: str | None = None  # optional as per HTTP spec

        # Set to 'True' once the request line has been sent
        self._status_line_sent: bool = False

        # Header fields

        self.headers: dict[str, str] = {}
        # Set to 'True' once the header lines have been sent
        self._headers_sent: bool = False

    async def _ensure_ready_for_body(self):
        """
        Ensure the status line and headers are sent before sending a response body.

        Raises:
            Exception: If headers are sent before the status line.

        This is a coroutine.
        """
        status_line_sent = self._status_line_sent
        headers_sent = self._headers_sent

        if not status_line_sent:
            if headers_sent:
                raise Exception("Headers were sent before status line")
            await self._send_status_line()

        if not headers_sent:
            await self._send_headers()

    def set_status_code(self, value: int):
        """
        Set the HTTP status code to send.

        Parameters:
            value: Integer status code (e.g., 200, 404).

        Raises:
            Exception: If the status line has already been sent.
        """
        if self._status_line_sent:
            raise Exception("status line already sent")

        self._status_code = value

    def set_reason_phrase(self, value: str):
        """
        Set the optional reason phrase for the HTTP status line.

        Parameters:
            value: A string like 'OK' or 'NOT FOUND'.

        Raises:
            Exception: If the status line has already been sent.
        """
        if self._status_line_sent:
            raise Exception("status line already sent")

        self._reason_phrase = value

    async def _send_status_line(self):
        """
        Send the HTTP status line to the client.

        Raises:
            Exception: If the status line has already been sent.

        This is a coroutine.
        """
        if self._status_line_sent:
            raise Exception("status line already sent")

        # even if reason phrase is empty, the "preceding" space must be present
        # https://www.rfc-editor.org/rfc/rfc9112.html#section-4-9

        sl = "HTTP/%s %s %s\r\n" % (
            Response.VERSION.decode(),
            self._status_code,
            self._reason_phrase or "",
        )
        self._writer.write(sl)
        self._status_line_sent = True
        await self._writer.drain()

    async def _send_headers(self):
        """
        Send all HTTP headers followed by a blank line.

        Raises:
            Exception: If headers have already been sent.

        This is a coroutine.
        """

        if self.headers is None:
            raise Exception("Headers already sent")

        hdrs = ""
        # Headers
        for k, v in self.headers.items():
            hdrs += "%s: %s\r\n" % (k, v)
        hdrs += "\r\n"

        self._writer.write(hdrs)
        self._headers_sent = True
        await self._writer.drain()
        # Collect garbage after small mallocs
        gc.collect()

    async def send(self, content, **kwargs):
        """
        Send the response body content to the client.

        May be called as many times as needed, the content will be appended to the
        body.

        Parameters:
            content: The data to send as response body.

        Raises:
            Exception: If headers or status line are not ready.

        This is a coroutine.
        """
        await self._ensure_ready_for_body()

        self._writer.write(content)
        await self._writer.drain()

    def add_header(self, key, value):
        """
        Add a header to the response.

        Parameters:
            key: The header name.
            value: The header value.

        Raises:
            Exception: If headers have already been sent.
        """
        if self._headers_sent:
            raise Exception("Headers already sent")

        self.headers[key.lower()] = value


class HTTPServer:
    def __init__(self, backlog=16):
        """
        HTTPServer class.

        See the :func:`route` decorator for specifying routes.
        See :func:`run` for starting the server.

        """
        self._backlog = backlog
        self._routes: list[Route] = []
        self._catch_all_handler = None

    def run(self, host="127.0.0.1", port=8081):
        """
        Start the HTTP server (blocking) on the specified host and port and run forever.

        Parameters:
            host: Interface to bind to (default "127.0.0.1").
            port: Port number to listen on (default 8081).
        """
        asyncio.run(self.arun(host, port))

    def _find_url_handler(self, req) -> tuple[Handler, Params, PathParameters]:
        """
        Find the registered handler matching the given request method and path.

        Parameters:
            req: A Request instance.

        Returns:
            A tuple of (handler, params, path_parameters).

        Raises:
            HTTPException(404): If no matching path.
            HTTPException(405): If path matches but method does not.
            HTTPException(501): For unsupported methods (CONNECT, OPTIONS, TRACE).
        """

        # we only support basic (GET, PUT, etc) requests
        if (
            req.method == b"CONNECT"
            or req.method == b"OPTIONS"
            or req.method == b"TRACE"
        ):
            raise HTTPException(501)

        # tracks whether there was an exact path match to differentiate
        # between 404 and 405
        path_matched = False

        for method, path, handler, params in self._routes:
            result = _match_url_paths(path, req.path)
            if result is not None:
                if method == req.method:
                    return (handler, params, result)

                path_matched = True

        if self._catch_all_handler:
            return self._catch_all_handler

        if path_matched:
            raise HTTPException(405)

        # No handler found
        raise HTTPException(404)

    async def _handle_connection(self, reader, writer):
        """
        Handle a client TCP connection, parse request (HTTP/1.0), call handler, return response.

        Parameters:
            reader: StreamReader for reading the connection.
            writer: StreamWriter for writing the connection.

        This is a coroutine.
        """
        gc.collect()

        try:
            req = Request(reader)
            resp = Response(writer)
            await req._read_request_line()

            # Find URL handler and parse headers
            (handler, req_params, path_params) = self._find_url_handler(req)
            await req._read_headers(req_params.get("save_headers") or [])

            gc.collect()  # free up some memory before the handler runs

            path_param_values = [v.decode() for (_, v) in path_params]
            await handler(req, resp, *path_param_values)

            # ensure the status line & headers are sent even if there
            # was no body
            await resp._ensure_ready_for_body()
            # Done here
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except OSError as e:
            # Do not send response for connection related errors - too late :)
            # P.S. code 32 - is possible BROKEN PIPE error (TODO: is it true?)
            if e.args[0] not in (errno.ECONNABORTED, errno.ECONNRESET, 32):
                _log.exception(f"Connection error: {e}")
                try:
                    resp.set_status_code(500)
                    await resp._ensure_ready_for_body()
                except Exception as e:
                    pass
        except HTTPException as e:
            try:
                if req.headers is None:
                    await req._read_headers()
                resp.set_status_code(e.code)
                await resp._ensure_ready_for_body()
            except Exception as e:
                _log.exception(
                    f"Failed to send error after HTTPException. Original error: {e}"
                )
        except Exception as e:
            # Unhandled expection in user's method
            _log.error(req.path.decode())
            _log.exception(f"Unhandled exception in user's method. Original error: {e}")
            try:
                resp.set_status_code(500)
                await resp._ensure_ready_for_body()
            except Exception as e:
                pass
        finally:
            writer.close()
            await writer.wait_closed()

    def add_route(
        self,
        url: str,
        f,
        methods: list[str] = ["GET"],
        save_headers: list[str | bytes] = [],
    ):
        """
        Register a route handler for a URL pattern and list of HTTP methods.

        Parameters:
            url: The route path pattern (e.g., '/hello/<name>').
            f: The handler function (async).
            methods: List of allowed HTTP methods.
            save_headers: Headers to preserve from the request.
        """
        if url == "" or "?" in url:
            raise ValueError("Invalid URL")
        _save_headers = [x.encode() if isinstance(x, str) else x for x in save_headers]
        _save_headers = [x.lower() for x in _save_headers]
        # Initial params for route
        params: Params = {
            "save_headers": _save_headers,
        }

        for method in [x.encode().upper() for x in methods]:
            self._routes.append((method, url.encode(), f, params))

    def catchall(self):
        """
        Decorator to register a catch-all handler when no routes match.

        Returns:
            A decorator function.
        """
        params: Params = {
            "save_headers": [],
        }

        def _route(f):
            self._catch_all_handler = (f, params, {})
            return f

        return _route

    def route(self, url, **kwargs):
        """
        Decorator to register a route handler.

        Parameters:
            url: The route path pattern.
            kwargs: Arguments passed to add_route(), e.g., methods or save_headers.

        Returns:
            A decorator function.
        """

        def _route(f):
            self.add_route(url, f, **kwargs)
            return f

        return _route

    async def arun(self, host="127.0.0.1", port=8081):
        """
        Asynchronously start the server and wait for it to close.

        Parameters:
            host: Interface to bind to.
            port: Port number.

        This is a coroutine.
        """
        aserver = await self.start(host, port)
        server = await aserver
        await server.wait_closed()

    async def start(self, host, port) -> Coroutine[Any, Any, asyncio.Server]:
        """
        Start the server and return the asyncio.Server instance.

        Parameters:
            host: Interface to bind to.
            port: Port number.

        Returns:
            An asyncio.Server instance.
        """
        return asyncio.start_server(
            self._handle_connection, host, port, backlog=self._backlog
        )
