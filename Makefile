.PHONY: build test install clean deps

.DEFAULT_GOAL := build

DOCKER ?= docker
OUTDIR ?= ./dist
DOCSDIR := $(OUTDIR)/docs
SERVER_PY := $(OUTDIR)/uht.py
SERVER_MPY := $(OUTDIR)/uht.mpy
# marker for image used in tests
CONTAINER_IID := $(OUTDIR)/container_iid

# install pip dependencies
deps:
	pip3 install -r requirements-dev.txt
	pip3 install -r requirements-typings.txt --target=./.typings --upgrade

build: $(SERVER_MPY) $(SERVER_PY)

$(SERVER_PY): ./uht.py
	mkdir -p $(OUTDIR)
	strip-hints ./uht.py -o $(SERVER_PY)
	@sed -i.bak '/# TYPING_START/,/# TYPING_END/ s/.*//' $(SERVER_PY)
	@rm -f $(SERVER_PY).bak

$(SERVER_MPY): $(SERVER_PY)
	mpy-cross $(SERVER_PY)

$(CONTAINER_IID): Dockerfile
	# the container tag is not strictly necessary but shows image origin
	$(DOCKER) build . -t uht-test-container --iidfile $(CONTAINER_IID)

# Install the non-compiled server to the connected board
install: $(SERVER_PY)
	mpremote ls :/lib || mpremote mkdir :/lib
	# note: mpremote ls fails on non-dirs so we use sha256sum to check for existence
	mpremote sha256sum :/lib/logging.mpy || mpremote mip install logging
	mpremote cp $(SERVER_PY) :/lib/uht.py

# Conditional 'test' Make target. If the TEST_TARGET option is set to 'board', then use mpremote
# and run the tests on whatever board is connected. Otherwise, run in the Unix port.
ifeq ($(TEST_TARGET),board)
test: $(SERVER_PY) install
	# install unittest unless if it's not there
	mpremote ls :/lib/unittest || mpremote mip install unittest
	# run the unit tests
	mpremote run ./test/unit.py
else
test: build $(CONTAINER_IID)
	# run with the local uht added to the default search path
	# https://docs.micropython.org/en/latest/unix/quickref.html#envvar-MICROPYPATH
	$(DOCKER) run --rm \
		-v ./test:/opt/uht-test \
		-v $(OUTDIR):/remote \
		-e MICROPYPATH='/remote:.frozen:/root/.micropython/lib:/usr/lib/micropython' \
		`cat $(CONTAINER_IID)` micropython /opt/uht-test/unit.py
endif

lint: ./uht.py
	ruff check
	mypy

docs: $(SERVER_PY)
	pdoc $(SERVER_PY) -o $(DOCSDIR)


clean:
	rm -rf $(OUTDIR)
