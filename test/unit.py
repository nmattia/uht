#!/usr/bin/env micropython
"""
Unittests for uht
MIT license
(C) Nicolas Mattia 2025 —
(C) Konstantin Belyalov 2017-2018
"""

import os
import gc
import unittest
import asyncio
from uht import (
    HTTPServer,
    HTTPException,
    Request,
    _parse_request_line,
    _match_url_paths,
)


# Helper to delete file
def delete_file(fn):
    # "unlink" gets renamed to "remove" in micropython,
    # so support both
    if hasattr(os, "unlink"):
        os.unlink(fn)
    else:
        os.remove(fn)


# HTTP headers helpers
def HDR(str):
    return "{}\r\n".format(str)


HDRE = "\r\n"


class mockReader:
    """Mock for coroutine reader class"""

    def __init__(self, lines):
        if type(lines) is not list:
            lines = [lines]
        self.lines = lines
        self.idx = 0

    async def readline(self):
        self.idx += 1
        # Convert and return str to bytes
        return self.lines[self.idx - 1].encode()

    def readexactly(self, n):
        return self.readline()


class mockWriter:
    """Mock for coroutine writer class"""

    def __init__(self, generate_exception=None):
        """
        keyword arguments:
            generate_exception - raise exception when calling send()
        """
        self.s = 1
        self.history = []
        self.closed = False
        self.generate_exception = generate_exception
        self.buffered = []

    def write(self, buf):
        self.buffered.append(buf)

    async def drain(self):
        if self.generate_exception:
            raise self.generate_exception
        self.history += self.buffered
        self.buffered = []

    def close(self):
        self.closed = True

    async def wait_closed(self):
        if not self.closed:
            raise Exception("Not implemented")
        return


# Tests


class Utils(unittest.TestCase):
    def testMatchURLPaths(self):
        runs = [
            (b"/", b"/", []),
            (b"/foo", b"/foo", []),
            (b"/oo", b"/foo", None),
            (b"/foo", b"/oo", None),
            (b"/foo/bar", b"/foo/bar", []),
            (b"/foo/bar/", b"/foo/bar/", []),
            (b"/users/<name>/", b"/users/alice/", [(b"name", b"alice")]),
            (
                b"/users/<uid>/posts/<pid>/comments",
                b"/users/1337/posts/42/comments",
                [(b"uid", b"1337"), (b"pid", b"42")],
            ),
        ]

        for route_path, req_path, expected in runs:
            result = _match_url_paths(route_path, req_path)
            self.assertEqual(result, expected)

    def test_parse_request_line_empty(self):
        self.assertIsNone(_parse_request_line(b""))

    def test_parse_request_line_bad_method(self):
        self.assertIsNone(_parse_request_line(b"GOT / HTTP/1.0"))

    def test_parse_request_line_bad_version(self):
        self.assertIsNone(_parse_request_line(b"GET / HTTP/"))
        self.assertIsNone(_parse_request_line(b"GET / HTTP/1"))
        self.assertIsNone(_parse_request_line(b"GET / HTTP/.1"))

    def test_parse_request_line_no_target(self):
        self.assertIsNone(_parse_request_line(b"GET HTTP/1.1"))
        self.assertIsNone(_parse_request_line(b"GET  HTTP/1.1"))

    def test_parse_request_line_bad_spaces(self):
        self.assertIsNone(_parse_request_line(b"GET /  HTTP/1.1"))
        self.assertIsNone(_parse_request_line(b"GET  / HTTP/1.1"))

    def test_parse_request_line_method(self):
        parsed = _parse_request_line(b"GET / HTTP/1.1")
        if not parsed:
            raise Exception("None")
        self.assertEqual(parsed["method"], b"GET")

    def test_parse_request_line_target(self):
        parsed = _parse_request_line(b"GET /foo HTTP/1.1")
        if not parsed:
            raise Exception("None")
        self.assertEqual(parsed["target"], b"/foo")

    def test_parse_request_line_version(self):
        parsed = _parse_request_line(b"GET / HTTP/1.1")
        if not parsed:
            raise Exception("None")
        self.assertEqual(parsed["version"], (1, 1))


class ServerParts(unittest.TestCase):
    def testRequestLineEmptyLinesBefore(self):
        req = Request(mockReader(["\n", "\r\n", "GET /?a=a HTTP/1.1"]))
        asyncio.run(req._read_request_line())
        self.assertEqual(b"GET", req.method)
        self.assertEqual(b"/", req.path)
        self.assertEqual(b"a=a", req.query_string)

    def testRequestLineNegative(self):
        runs = ["", "\t\t", "  ", " / HTTP/1.1", "GET", "GET /", "GET / "]

        for r in runs:
            with self.assertRaises(HTTPException):
                req = Request(mockReader(r))
                asyncio.run(req._read_request_line())

    def testHeadersSimple(self):
        req = Request(mockReader([HDR("Host: google.com"), HDRE]))
        asyncio.run(req._read_headers([b"host"]))
        self.assertEqual(req.headers, {b"host": b"google.com"})

    def testHeadersSpaces(self):
        req = Request(mockReader([HDR("host:    \t    google.com   \t     "), HDRE]))
        asyncio.run(req._read_headers([b"host"]))
        self.assertEqual(req.headers, {b"host": b"google.com"})

    def testHeadersEmptyValue(self):
        req = Request(mockReader([HDR("host:"), HDRE]))
        asyncio.run(req._read_headers([b"host"]))
        self.assertEqual(req.headers, {b"host": b""})

    def testHeadersMultiple(self):
        req = Request(
            mockReader(
                [
                    HDR("host: google.com"),
                    HDR("junk: you    blah"),
                    HDR("content-type:      file"),
                    HDRE,
                ]
            )
        )
        hdrs = {
            b"host": b"google.com",
            b"junk": b"you    blah",
            b"content-type": b"file",
        }
        asyncio.run(req._read_headers([b"Host", b"Junk", b"Content-type"]))
        self.assertEqual(req.headers, hdrs)

    def testUrlFinderExplicit(self):
        urls = [("/", 1), ("/%20", 2), ("/a/b", 3), ("/aac", 5)]
        junk = ["//", "", "/a", "/aa", "/a/fhhfhfhfhfhf"]
        # Create server, add routes
        srv = HTTPServer()
        for u in urls:
            srv.add_route(u[0], u[1])
        # Search them all
        for u in urls:
            # Create mock request object with "pre-parsed" url path
            rq = Request(mockReader([]))
            rq.path = u[0].encode()
            rq.method = b"GET"
            result = srv._find_url_handler(rq)
            if isinstance(result, HTTPException):
                raise Exception("Expected result")

            f, args, _ = result
            self.assertEqual(u[1], f)
        # Some simple negative cases
        for j in junk:
            rq = Request(mockReader([]))
            rq.path = j.encode()
            with self.assertRaises(HTTPException):
                srv._find_url_handler(rq)

    def testUrlFinderNegative(self):
        srv = HTTPServer()
        # empty URL is not allowed
        with self.assertRaises(ValueError):
            srv.add_route("", 1)
        # Query string is not allowed
        with self.assertRaises(ValueError):
            srv.add_route("/?a=a", 1)


async def send_raw_request(host, port, request):
    """Sends a raw HTTP request and returns the raw response."""
    (reader, writer) = await asyncio.open_connection(host, port)
    writer.write(request.encode("ascii"))
    await writer.drain()
    writer.close()

    response = await reader.read()

    return response


class TestHTTPServer(unittest.TestCase):
    HOST = "127.0.0.1"
    PORT = 8081

    def setUp(self):
        self.server = HTTPServer()
        gc.collect()

    def assertRequestResponse(self, req, expected):
        host = TestHTTPServer.HOST
        port = TestHTTPServer.PORT
        aaserver = self.server.start(host=host, port=port)

        async def send_request():
            aserver = await aaserver
            server = await aserver
            async with server:
                resp = await send_raw_request(host, port, req)

            return resp

        resp = asyncio.run(send_request())

        if callable(expected):
            self.assertTrue(expected(resp), "Response did not match expectations")
        else:
            self.assertEqual(resp, expected)

    def test_bad_method(self):
        self.assertRequestResponse("GOT / HTTP/1.1\r\n\r\n", b"HTTP/1.0 400 \r\n\r\n")

    def test_http_1_0_request(self):
        request = "GET / HTTP/1.0\r\n\r\n"
        self.assertRequestResponse(request, lambda resp: resp.startswith("HTTP/1.0"))

    def test_http_1_1_request(self):
        request = "GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
        self.assertRequestResponse(request, lambda resp: resp.startswith("HTTP/1.0"))

    def test_http_reason_phrase(self):
        @self.server.route("/")
        async def teapot(req, resp):
            resp.set_status_code(418)
            resp.set_reason_phrase("I'm a teapot")

        self.assertRequestResponse(
            "GET / HTTP/1.1\r\n\r\n", b"HTTP/1.0 418 I'm a teapot\r\n\r\n"
        )

    def test_not_found(self):
        self.assertRequestResponse("GET / HTTP/1.1\r\n\r\n", b"HTTP/1.0 404 \r\n\r\n")

    def test_get(self):
        @self.server.route("/")
        async def hello(req, resp):
            await resp.send("hello")

        self.assertRequestResponse(
            "GET / HTTP/1.1\r\n\r\n", b"HTTP/1.0 200 \r\n\r\nhello"
        )

    def test_method_not_allowed(self):
        @self.server.route("/")
        async def hello(req, resp):
            await resp.send("hello")

        self.assertRequestResponse("POST / HTTP/1.1\r\n\r\n", b"HTTP/1.0 405 \r\n\r\n")

    def test_connect_unimplemented(self):
        self.assertRequestResponse(
            "CONNECT www.example.com:443 HTTP/1.1\r\n\r\n", b"HTTP/1.0 501 \r\n\r\n"
        )

    def test_empty_response_body(self):
        @self.server.route("/")
        async def hello(req, resp):
            pass

        self.assertRequestResponse("GET / HTTP/1.1\r\n\r\n", b"HTTP/1.0 200 \r\n\r\n")


# We want to test decorators as well
server_for_decorators = HTTPServer()


@server_for_decorators.route("/uid/<user_id>")
@server_for_decorators.route("/uid2/<user_id>")
async def route_for_decorator(req, resp, user_id):
    resp.add_header("content-type", "text/html")
    await resp.send("YO, {}".format(user_id))


class HTTPServerFull(unittest.TestCase):
    def assertHistory(self, wrt, expected):
        if isinstance(expected, list):
            self.assertEqual(wrt.history, expected)
        else:
            self.assertEqual("".join(wrt.history), expected)

    def setUp(self):
        self.dummy_called = False
        self.data = {}
        self.hello_world_history = (
            "HTTP/1.0 200 \r\n"
            "content-type: text/html\r\n"
            "\r\n"
            "<html><h1>Hello world</h1></html>"
        )  # fmt: skip

        # Create one more server - to simplify bunch of tests
        self.srv = HTTPServer()

    def testRouteDecorator1(self):
        """Test @.route() decorator"""
        # First decorator
        rdr = mockReader(["GET /uid/man1 HTTP/1.1\r\n", HDRE])
        wrt = mockWriter()
        # "Send" request
        asyncio.run(server_for_decorators._handle_connection(rdr, wrt))
        # Ensure that proper response "sent"
        expected = (
            "HTTP/1.0 200 \r\n"
            "content-type: text/html\r\n"
            "\r\n"
            "YO, man1"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        self.assertTrue(wrt.closed)

    def testRouteDecorator2(self):
        # Second decorator
        rdr = mockReader(["GET /uid2/man2 HTTP/1.1\r\n", HDRE])
        wrt = mockWriter()
        # "Send" request
        asyncio.run(server_for_decorators._handle_connection(rdr, wrt))
        # Ensure that proper response "sent"
        expected = (
            "HTTP/1.0 200 \r\n"
            "content-type: text/html\r\n"
            "\r\n"
            "YO, man2"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        self.assertTrue(wrt.closed)

    def testOverlappingPaths(self):
        """Tests that the same path may be registered multiple times."""

        server = HTTPServer()

        @server.route("/", methods=["GET"])
        async def get(req, resp):
            await resp.send("hi from GET")

        @server.route("/", methods=["POST"])
        async def post(req, resp):
            await resp.send("hi from POST")

        rdr = mockReader(["GET / HTTP/1.1\r\n", HDRE])
        wrt = mockWriter()
        asyncio.run(server._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 200 \r\n"
            "\r\n"
            "hi from GET"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        self.assertTrue(wrt.closed)

        rdr = mockReader(["POST / HTTP/1.1\r\n", HDRE])
        wrt = mockWriter()
        asyncio.run(server._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 200 \r\n"
            "\r\n"
            "hi from POST"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        self.assertTrue(wrt.closed)

    def testCatchAllDecorator(self):
        # A fresh server for the catchall handler
        server_for_catchall_decorator = HTTPServer()

        # Catchall decorator and handler
        @server_for_catchall_decorator.catchall()
        async def route_for_catchall_decorator(req, resp):
            resp.set_status_code(404)
            resp.set_reason_phrase("NOT FOUND")
            await resp.send("my404")

        rdr = mockReader(["GET /this/is/an/invalid/url HTTP/1.1\r\n", HDRE])
        wrt = mockWriter()
        asyncio.run(server_for_catchall_decorator._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 404 NOT FOUND\r\n"
            "\r\n"
            "my404"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        self.assertTrue(wrt.closed)

    async def dummy_handler(self, req, resp):
        """Dummy URL handler. It just records the fact - it has been called"""
        self.dummy_req = req
        self.dummy_resp = resp
        self.dummy_called = True

    async def hello_world_handler(self, req, resp):
        resp.add_header("content-type", "text/html")
        await resp.send("<html><h1>Hello world</h1></html>")

    async def route_parameterized_handler(self, req, resp, user_name):
        resp.add_header("content-type", "text/html")
        await resp.send("<html>Hello, {}</html>".format(user_name))

    def testRouteParameterized(self):
        """Verify that route with params works fine"""
        self.srv.add_route("/db/<user_name>", self.route_parameterized_handler)
        rdr = mockReader(["GET /db/user1 HTTP/1.1\r\n", HDR("Host: junk.com"), HDRE])
        wrt = mockWriter()
        # "Send" request
        asyncio.run(self.srv._handle_connection(rdr, wrt))
        # Ensure that proper response "sent"
        expected = (
            "HTTP/1.0 200 \r\n"
            "content-type: text/html\r\n"
            "\r\n"
            "<html>Hello, user1</html>"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        self.assertTrue(wrt.closed)

    def testParseHeadersOnOff(self):
        """Verify parameter parse_headers works"""
        self.srv.add_route("/", self.dummy_handler, save_headers=["h1", "h2"])
        rdr = mockReader(
            [
                "GET / HTTP/1.1\r\n",
                HDR("h1: blah.com"),
                HDR("h2: lalalla"),
                HDR("junk: fsdfmsdjfgjsdfjunk.com"),
                HDRE,
            ]
        )
        # "Send" request
        wrt = mockWriter()
        asyncio.run(self.srv._handle_connection(rdr, wrt))
        self.assertTrue(self.dummy_called)
        # Check for headers - only 2 of 3 should be collected, others - ignore
        hdrs = {b"h1": b"blah.com", b"h2": b"lalalla"}
        self.assertEqual(self.dummy_req.headers, hdrs)
        self.assertTrue(wrt.closed)

    def testDisallowedMethod(self):
        """Verify that server respects allowed methods"""
        self.srv.add_route("/", self.hello_world_handler)
        self.srv.add_route("/post_only", self.dummy_handler, methods=["POST"])
        rdr = mockReader(["GET / HTTP/1.0\r\n", HDRE])
        # "Send" GET request, by default GET is enabled
        wrt = mockWriter()
        asyncio.run(self.srv._handle_connection(rdr, wrt))
        self.assertHistory(wrt, self.hello_world_history)
        self.assertTrue(wrt.closed)

        # "Send" GET request to POST only location
        self.dummy_called = False
        rdr = mockReader(["GET /post_only HTTP/1.1\r\n", HDRE])
        wrt = mockWriter()
        asyncio.run(self.srv._handle_connection(rdr, wrt))
        # Hanlder should not be called - method not allowed
        self.assertFalse(self.dummy_called)
        expected = (
            "HTTP/1.0 405 \r\n"
            "\r\n"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        # Connection must be closed
        self.assertTrue(wrt.closed)

    def testPageNotFound(self):
        """Verify that malformed request generates proper response"""
        rdr = mockReader(
            ["GET /not_existing HTTP/1.1\r\n", HDR("Host: blah.com"), HDRE]
        )
        wrt = mockWriter()
        asyncio.run(self.srv._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 404 \r\n"
            "\r\n"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        # Connection must be closed
        self.assertTrue(wrt.closed)

    def testMalformedRequest(self):
        """Verify that malformed request generates proper response"""
        rdr = mockReader(["GET /\r\n", HDR("Host: blah.com"), HDRE])
        wrt = mockWriter()
        asyncio.run(self.srv._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 400 \r\n"
            "\r\n"
        )  # fmt: skip
        self.assertHistory(wrt, expected)
        # Connection must be closed
        self.assertTrue(wrt.closed)

    def testGet(self):
        srv = HTTPServer()

        async def hello(req, resp):
            resp.add_header("content-type", "text/plain")
            await resp.send("hello")

        srv.add_route("/", hello)
        rdr = mockReader(["GET / HTTP/1.0\r\n", HDRE])
        wrt = mockWriter()
        asyncio.run(srv._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 200 \r\n"
            "content-type: text/plain\r\n"
            "\r\n"
            "hello"
        )  # fmt: skip
        self.assertHistory(wrt, expected)

    def testGetWithParam(self):
        srv = HTTPServer()

        async def echo(req, resp, param):
            resp.add_header("content-type", "text/plain")
            await resp.send(param)

        srv.add_route("/echo/<param>", echo)
        rdr = mockReader(["GET /echo/123 HTTP/1.0\r\n", HDRE])
        wrt = mockWriter()
        asyncio.run(srv._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 200 \r\n"
            "content-type: text/plain\r\n"
            "\r\n"
            "123"
        )  # fmt: skip
        self.assertHistory(wrt, expected)

    def testInvalidMethod(self):
        rdr = mockReader(["PUT / HTTP/1.0\r\n", HDRE])
        wrt = mockWriter()
        srv = HTTPServer()

        async def get(req, resp):
            resp.add_header("content-type", "text/plain")

        srv.add_route("/", get)
        asyncio.run(srv._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 405 \r\n"
            "\r\n"
        )  # fmt: skip
        self.assertHistory(wrt, expected)

    def testException(self):
        rdr = mockReader(["GET /err HTTP/1.0\r\n", HDRE])
        wrt = mockWriter()
        srv = HTTPServer()

        async def err(req, resp):
            raise Exception("This is an error")

        srv.add_route("/err", err)
        asyncio.run(srv._handle_connection(rdr, wrt))
        expected = (
            "HTTP/1.0 500 \r\n"
            "\r\n"
        )  # fmt: skip
        self.assertHistory(wrt, expected)


if __name__ == "__main__":
    res = unittest.main()
    if len(res.errors) > 0:
        print("got errors")
        raise Exception("errors")

    if len(res.failures) > 0:
        print("got failures")
        raise Exception("failures")
