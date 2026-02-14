"""Very bare-bones HTTP end-to-end tests."""

import os
import signal
import subprocess
import urllib.request
import time

mpy_run_cmd = os.environ["MPY_RUN_CMD"]
mpy_origin = os.environ["MPY_ORIGIN"]

process = subprocess.Popen(
    f"{mpy_run_cmd} ./tests/hello.py",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    shell=True,
)


def wait_for_http(origin):
    """Returns when the origin starts talking HTTP."""
    attempt = 1
    max_attempts = 5
    while True:
        print(f"connecting to {origin} (attempt {attempt})")
        # curl will return !0 if the connection itself fails.
        # If it gets a response, regardless of the HTTP code, it
        # returns 0.
        result = subprocess.run(["curl", origin + "/not-found"])
        if result.returncode == 0:
            print(f"connected to {origin}")
            return

        if attempt >= max_attempts:
            raise ValueError(f"did not connect in {max_attempts} attempts")
        attempt += 1

        time.sleep(1)


try:
    wait_for_http(mpy_origin)
    response = urllib.request.urlopen(f"http://{mpy_origin}/", timeout=5)

    status = response.status
    if status != 200:
        raise AssertionError(f"Bad response status: {status}")

finally:
    process.send_signal(signal.SIGINT)

    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("WARNING: process did not return")
