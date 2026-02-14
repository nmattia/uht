# Hacking on uht

Install the required dependencies:

```
make deps
```

This installs linter, build and docs dependencies.

Run the linters

```bash
make lint
```

Prepare output and run tests:

```
make build
make test
```

Optionally build the docs:

```
make docs
```

Serve the docs:

```
python3 -m http.server -d ./dist/docs
```

## Install uht on a board

First MicroPython (or CircuitPython) needs to be installed on your board. Then the dependencies need to be installed. Then you can install `uht`.

### Installing MicroPython

First download MicroPython for your board [here](https://micropython.org/download/) and flash it to your board.

<details><summary><h4>Install MicroPython on Raspberry Pi Pico 2 W</h4></summary>

1. Download the [MicroPython `.uf2` release](https://micropython.org/download/RPI_PICO2_W/)
2. Enter bootloader mode by holding the BOOTSEL button while powering your device
3. Copy the MicroPython `.uf2` to your device

</details>

<details><summary><h4>Install MicroPython on ESP8266</h4></summary>

```bash
pip3 install esptool==5.0.1
esptool erase_flash
curl -LO https://micropython.org/resources/firmware/ESP8266_GENERIC-20250415-v1.25.0.bin
esptool write-flash --flash-size=detect 0 ./ESP8266_GENERIC-20250415-v1.25.0.bin
```

</details>

<details><summary><h4>Install MicroPython on ESP32-C6</h4></summary>

```bash
pip3 install esptool==5.0.1
esptool erase-flash
curl -LO https://micropython.org/resources/firmware/ESP32_GENERIC_C6-20250415-v1.25.0.bin
esptool write-flash --flash-size=detect 0 ./ESP32_GENERIC_C6-20250415-v1.25.0.bin
```

</details>


### Install uht

Build and install the `uht` library to the board connected via USB:

```bash
make install
```

Run the tests in docker:

```bash
make test
```

Run the tests on a board:

> [!NOTE]
>
> Tests fail on the rp2 platform.

```
make TEST_TARGET=board test
```

Run the example webapp:

```bash
mpremote ls :/srv || mpremote mkdir :/srv
mpremote cp ./examples/static/index.html :/srv/index.html
mpremote run ./examples/webapp.py
```
