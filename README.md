# uht

A minimal HTTP/1.0 server for tiny devices (ESP32, Raspberry Pi Pico, etc.) running [MicroPython](https://github.com/micropython/micropython) or [CircuitPython](https://github.com/adafruit/circuitpython). Compatible with MicroPython 1.21+.

### Table of Contents

* [Basic Usage](#basic-usage)
* [Getting Started](#getting-started)
  * [Installing mpremote](#installing-mpremote)
  * [Connecting to WiFi](#connecting-to-wifi)
  * [Installing uht and starting an HTTP server](#installing-uht-and-starting-an-http-server)
* [Examples](#examples)
  * [Basic Hello World](#basic-hello-world)
  * [Route with Parameter](#route-with-parameter)
  * [Custom Status Code and Header](#custom-status-code-and-header)
  * [Catch-All Route](#catch-all-route)
* [Running in an Async Context](#running-in-an-async-context)
* [About](#about)

## Basic Usage

Install with `mip`:

```bash
mpremote mip install logging
mpremote mip install "https://github.com/nmattia/uht/releases/latest/download/uht.py" # .mpy is also available
```

Start a server:

```python
from uht import HTTPServer

app = HTTPServer()

@app.route("/")
async def index(req, resp):
    await resp.send(b"Hello, world!")

app.run()  # Starts the server on 127.0.0.1:8081
```

See the [Getting Started](#getting-started) and [Examples](#examples) sections below for more information and refer to the [documentation](https://nmattia.github.io/uht/) for all options.

## Getting Started

This will guide you through the installation of the `uht` library and its dependencies via MicroPython and [`mip`](https://docs.micropython.org/en/latest/reference/packages.html#installing-packages-with-mip) and show you how to start an HTTP server.

> [!NOTE]
>
> See the [Basic Usage](#basic-usage) section for a shorter — but equivalent — intro.

### Installing mpremote

The simplest way to get a MicroPython repl on your microcontroller is to use mpremote. First install `mpremote`:

```bash
pip install --user mpremote
```

Then open a MicroPython console:

```bash
mpremote # will automatically connect to any board that's plugged in and start a repl
```

### Connecting to WiFi

In the MicroPython repl, set the SSID and password for your WiFi network:

```
>>> SSID = "my-ssid" # use value from your network
>>> PASSWORD = "my-password" # use value from your network
```

> [!NOTE]
>
> If you are not seeing the MicroPython repl prompt (`>>>`) you may need to hit `Ctrl-C`. The `>>>` prompt is omitted from snippets below.

Then activate the WiFi interface (the repl prompt `>>>` is omitted for snippets):

```python
import network

sta_if = network.WLAN(network.STA_IF)
sta_if.active(True)
sta_if.connect(SSID, PASSWORD)
```

Your board might take a couple of seconds to connect to your WiFi network. You can check the status by calling `sta_if.isconnected()`:

```
>>> sta_if.isconnected()
False
>>> sta_if.isconnected()
False
>>> sta_if.isconnected()
True
```

Once your board is connected to your WiFi network, look up your board's IP address and write it down.

```
>>> sta_if.ipconfig('addr4')[0]
'192.168.1.120'
```

### Installing uht and starting an HTTP server

Now use `mip` — MicroPython's built-in package manager — to install the `logging` library (dependency of `uht`) and `uht`:

```python
import mip
mip.install("logging")
mip.install("https://github.com/nmattia/uht/releases/latest/download/uht.py")
```

Finally, start the server:

> [!NOTE]
>
> To paste complex snippets, first hit `Ctrl-E` to enter paste mode, paste your snippet, and then hit `Ctrl-D` to exit paste mode.

```python
import uht

server = uht.HTTPServer()

@server.route("/hello/<name>")
async def greet(req, resp, name):
    await resp.send(f"Hello, {name}!\n")
    await resp.send("Greetings from your board.\n")

server.run()
```

You should now be able to reach your board from any device connected to your WiFi using the IP address looked up above:

```bash
$ curl http://192.168.1.120:8080/hello/alice
Hello, alice!
Greetings from your board.
```

## Examples

### Basic Hello World

Serve a simple "Hello, world!" response on `http://127.0.0.1:8081/`:

```python
from uht import HTTPServer

app = HTTPServer()

@app.route("/")
async def index(req, resp):
    await resp.send(b"Hello, world!")

app.run()  # Defaults to 127.0.0.1:8081
```

### Route with Parameter

Define a dynamic route that greets the user by name:

```python
@app.route("/hello/<name>")
async def greet(req, resp, name):
    await resp.send("Hello, {name}!")
```

The parameter is now echoed in the response:

```bash
$ curl http://127.0.0.1:8081/hello/Alice
Hello, Alice!
```

### Custom Status Code and Header

Custom HTTP status codes and additional response headers can be set as follows:

```python
@app.route("/custom")
async def custom_response(req, resp):
    resp.set_status_code(202)
    resp.set_reason_phrase("Accepted")
    resp.add_header("X-Custom", "Value")
    await resp.send(b"Custom response")
```

> [!NOTE]
>
> The status code and headers must be set before the first call to `send()` otherwise an exception will be thrown!

Response:

```
HTTP/1.0 202 Accepted
X-Custom: Value
```

### Catch-All Route

A catch-all handler can be registered:

```python
@app.catchall()
async def not_found(req, resp):
    resp.set_status_code(404)
    await resp.send(b"Custom 404 Not Found")
```

Any request that doesn't match a defined route will now return:
```
HTTP/1.0 404
Custom 404 Not Found
```

See the [examples](./examples) directory for more.

## Running in an Async Context

If you need to integrate the server with other async code (e.g., background tasks), use the `start()` method instead of `run()`.

### Example:

```python
from uht import HTTPServer
import asyncio

app = HTTPServer()

@app.route("/")
async def index(req, resp):
    await resp.send(b"Hello from async start")

async def main():
    server = app.start("0.0.0.0", 8081)
    print("Server started on port 8081")

    # Optionally do other async tasks here
    await server.wait_closed()  # Wait until the server shuts down

asyncio.run(main())
```

This approach gives you more control and allows you to schedule other coroutines alongside the HTTP server.


## About

The `uht` library started as a fork of [tinyweb](https://github.com/belyalov/tinyweb) by [Konstantin Belyalov](https://github.com/belyalov). Over time the library was pretty much completely rewritten.
