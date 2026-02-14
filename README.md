# uht - micro HTTP Toolkit

A minimal, fully async HTTP/1.0 server for tiny devices (ESP32, Raspberry Pi Pico, etc.) running [MicroPython](https://github.com/micropython/micropython) or [CircuitPython](https://github.com/adafruit/circuitpython). Compatible with MicroPython 1.21+.

```python
from uht import HTTPServer

app = HTTPServer()

@app.route("/hello/<name>")
async def greet(req, resp, name):
    await resp.send(f"Hello, {name}!")

app.run()
```

The [Basic Usage](#basic-usage) section shows how to quickly get started. The [Installation Instructions](#installation-instructions) section shows advanced installation options. The [Examples](#examples) section shows real-world examples. There is also an [API reference page](https://nmattia.github.io/uht/).

## Basic Usage

This shows the 3 steps to get an app running on a board, assuming you have [`mpremote`](#installing-mpremote) installed.

Make sure your board is connected via USB and install `uht` with `mip`:

```bash
mpremote mip install logging
mpremote mip install "https://github.com/nmattia/uht/releases/latest/download/uht.py"
```

Create a file named `main.py` with the following content:

```python
import network
from uht import HTTPServer

nic = network.WLAN(network.AP_IF)
nic.active(True)
nic.config(ssid="uht-test-server", security=network.WLAN.SEC_OPEN)

(ip, _, _, _) = nic.ifconfig()

print(f"URL: 'http://{ip}'")

app = HTTPServer()

@app.route("/")
async def index(req, resp):
    await resp.send(b"Hello, world!")

app.run()
```

Run the server on the device:

```shell
mpremote run main.py
```

The server is now running. Connect to WiFi network `uht-test-server` and visit `http://192.168.4.1/`.

## Installation instructions

This assumes MicroPython was already flashed to your board.

### Installing with mpremote

This uses `mpremote`. This does not require the board to be connected to the internet.

Install the library and dependencies:

```shell
mpremote mip install logging
mpremote mip install "https://github.com/nmattia/uht/releases/latest/download/uht.py"
```

If resource constrained or if you don't plan on tweaking the code install the `.mpy` module:

```
mpremote mip install "https://github.com/nmattia/uht/releases/latest/download/uht.mpy"
```


https://docs.micropython.org/en/latest/reference/mpremote.html

### Installing from MicroPython REPL

Use MicroPython's built-in package manager `mip` to install the `logging` library (dependency of `uht`) and `uht`. This requires the board to be connected to the internet.

```python
import mip
mip.install("logging")
mip.install("https://github.com/nmattia/uht/releases/latest/download/uht.py")
```


## Examples

These examples use `mpremote`. See instructions on how to install it or adapt to your IDE.

The first two examples show how to set up networking. The other examples assume working networking.

### Full Hello World in AP mode

_The devices creates a new WiFi network (i.e. Access Point mode) and serves "Hello, World!". The device won't have access to the internet and you will need to connect to it directly._

Create a file `main_ap.py` with the following:

```python
import network
from uht import HTTPServer

nic = network.WLAN(network.AP_IF)
nic.active(True)
nic.config(ssid="uht-test-server", security=network.WLAN.SEC_OPEN)

(ip, _, _, _) = nic.ifconfig()

print(f"URL: 'http://{ip}'")

app = HTTPServer()

@app.route("/")
async def index(req, resp):
    await resp.send(b"Hello, world!")

app.run()
```

Run the server on the device:

```shell
mpremote run main_ap.py
```

### Full Hello World in STA mode

_The devices connects to a known WiFi network and serves "Hello, World!"._

Create a file `main_sta.py` with the following:

```shell
$ mpremote edit :/config.json
{  "SSID": "my-ssid",
    "PK": "wpa-password"
}
```

Write this to `main_sta.py`:

```python
import io
import time
import json
import network
from uht import HTTPServer

def read_config():
    with io.open("config.json", "r") as f:
        return json.load(f)


# enable station interface and connect to WiFi access point
nic = network.WLAN(network.WLAN.IF_STA)
nic.active(True)
cfg = read_config()
nic.connect(cfg["SSID"], cfg["PK"])

while not nic.isconnected():
    print("waiting for connect")
    time.sleep(1)

(ip, _, _, _) = nic.ifconfig()

print(f"URL: 'http://{ip}'")

app = HTTPServer()

@app.route("/")
async def index(req, resp):
    await resp.send(b"Hello, world!")

app.run()
```

Run the server on the device:

```shell
mpremote run main_sta.py
```

Note the URL printed out.

### Route with Parameter

Define a dynamic route that greets the user by name:

```python
from uht import HTTPServer

app = HTTPServer()

@app.route("/hello/<name>")
async def greet(req, resp, name):
    await resp.send("Hello, {name}!")

app.run()
```

### Custom Status Code and Header

Custom HTTP status codes and additional response headers can be set as follows:

```python
from uht import HTTPServer

app = HTTPServer()

@app.route("/custom")
async def custom_response(req, resp):
    resp.set_status_code(202)
    resp.set_reason_phrase("Accepted")
    resp.add_header("X-Custom", "Value")
    await resp.send(b"Custom response")

app.run()
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

> [!NOTE]
>
> The status code and headers must be set before the first call to `send()` otherwise an exception will be thrown!

Any request that doesn't match a defined route will now return:

```
HTTP/1.0 404
Custom 404 Not Found
```


### Running in an Async Context

If you need to integrate the server with other async code (e.g., background tasks), use the `start()` method instead of `run()`. This approach gives you more control and allows you to schedule other coroutines alongside the HTTP server.

```python
from machine import Pin
from uht import HTTPServer
import asyncio

app = HTTPServer()

led_gpio = 8 # GPIO pin driving an LED

state = { "blink_interval_ms" : 500 } # shared state

@app.route("/fast")
async def index(req, resp):
    state['blink_interval_ms'] = 250

@app.route("/slow")
async def index(req, resp):
    state['blink_interval_ms'] = 1000

async def blink():
    pin = Pin(led_gpio, Pin.OUT)
    while True:
        pin.toggle()
        await asyncio.sleep_ms(state['blink_interval_ms'])

async def main():
    server = await app.start()
    asyncio.create_task(blink())

    print("Server started")

    await server.wait_closed()  # Finish if the server shuts down for any reason

asyncio.run(main())
```


## About

The `uht` library started as a fork of [tinyweb](https://github.com/belyalov/tinyweb) by [Konstantin Belyalov](https://github.com/belyalov). Over time the library was pretty much completely rewritten.

The full diff (before the first commit on this repo) can be found [here](https://github.com/nmattia/tinyweb-ng/compare/7669f03cdcbb62a847e7d4917673be52ad2f7e79..e11bd40756669dc48ad34b56a4be8e6b8e6bbb9e).
