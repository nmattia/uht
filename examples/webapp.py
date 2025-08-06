#!/usr/bin/env micropython

import gc
import json
import errno
import sys
import uht
import logging
import os
import network


def init_logger(name="root"):
    rootLogger = logging.getLogger(name)
    rootLogger.setLevel(logging.DEBUG)
    for handler in rootLogger.handlers:
        handler.setLevel(logging.DEBUG)


init_logger("root")
init_logger("WEB")

server = uht.HTTPServer()


async def html_file_handler(filename, resp):
    buf = bytearray(512)
    try:
        # get file size
        stat = os.stat(filename)
        file_len = stat[6]
        resp.add_header("content-length", str(file_len))
        resp.add_header("content-type", "text/html")

        with open(filename) as f:
            while True:
                size = f.readinto(buf)
                if size == 0:
                    break
                await resp.send(buf[:size])
    except OSError as e:
        # special handling for ENOENT / EACCESS
        if e.args[0] in (errno.ENOENT, errno.EACCES):
            raise uht.HTTPException(404)
        else:
            raise


@server.route("/", methods=["GET"])
async def get_index(req, resp):
    """Serve the webapp."""
    await html_file_handler("/srv/index.html", resp)


@server.route("/info", methods=["GET"])
async def get_info(req, resp):
    """Returns information about the board."""
    resp.headers[b"content-type"] = b"application/json"

    obj = board_data()
    await resp.send(json.dumps(obj))


@server.route("/pins/", methods=["GET"])
async def get_pins(req, resp):
    """Returns a list of pins."""
    from machine import Pin

    pin_names: list[str] = []

    for pin in dir(Pin.board):
        if not pin.startswith("__"):
            pin_names.append(pin)

    resp.headers[b"content-type"] = b"application/json"
    await resp.send(json.dumps({"pins": pin_names}))


@server.route("/pins/<pin_name>/toggle", methods=["POST"])
async def toggle_pin(req, resp, pin_name):
    """Toggles any particular pin."""

    from machine import Pin

    pin = getattr(Pin.board, pin_name)
    pin.toggle()

    resp.headers[b"content-type"] = b"application/json"
    await resp.send(json.dumps({}))


def board_data():
    """Return boad data in format [{"title": "foo", "value": "bar"}]."""

    obj = [{"title": "Platform", "value": sys.platform}]

    # some of these are not available on all platforms, so as much as possible we wrap them in try/catch
    try:
        ap = network.WLAN(network.AP_IF)
        if ap.active():
            (ip, _, _, _) = ap.ifconfig()
            obj.append({"title": "Network", "value": f"{ip} (AP mode)"})
    except ModuleNotFoundError:
        pass

    try:
        mem_free = gc.mem_free()
        mem_tot = mem_free + gc.mem_alloc()
        mem_data = f"{mem_free}B/{mem_tot}B ({mem_free / mem_tot * 100:.2}%)"
        obj.append({"title": "Memory Usage", "value": mem_data})
    except ModuleNotFoundError:
        pass

    try:
        import machine

        # while the freq (as a string) ends with 000, increase the 10e3 factor
        # in the unit and strip those three 0s
        freq = str(machine.freq())
        freq_unit_factor = ["", "k", "M", "G", "T"]  # Hz, kHz, MHz, etc
        freq_10e3 = 0
        while freq.endswith("000"):
            freq = freq[:3]
            freq_10e3 += 1

        freq = f"{freq}{freq_unit_factor[freq_10e3]}Hz"
        obj.append({"title": "Chip Frequency", "value": freq})
    except ModuleNotFoundError:
        pass

    return obj


def run():
    # Set up AP
    SSID = "uht-demo"
    logging.info(f"creating AP with SSID '{SSID}'")
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(ssid=SSID, security=network.WLAN.SEC_OPEN)

    (ip, _, _, _) = ap.ifconfig()
    logging.info("AP configured: " + ip)

    port = 8081
    logging.info("starting server")
    endpoint = f"http://{ip}:{port}"
    logging.info(f"listening on '{endpoint}'")
    server.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    run()
