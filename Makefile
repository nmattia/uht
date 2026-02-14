.PHONY: container build test clean deps

.DEFAULT_GOAL := build

DOCKER ?= docker
OUTDIR ?= ./dist
DOCSDIR := $(OUTDIR)/docs
SERVER_PY := $(OUTDIR)/uht.py
SERVER_MPY := $(OUTDIR)/uht.mpy

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

container: Dockerfile
	$(DOCKER) build . -t uht

test: build container
	# run with the local uht added to the default search path
	# https://docs.micropython.org/en/latest/unix/quickref.html#envvar-MICROPYPATH
	$(DOCKER) run --rm \
		-v ./test:/opt/uht-test \
		-v $(OUTDIR):/remote \
		-e MICROPYPATH='/remote:.frozen:/root/.micropython/lib:/usr/lib/micropython' \
		uht micropython /opt/uht-test/unit.py

lint: ./uht.py
	ruff check
	mypy

docs: $(SERVER_PY)
	pdoc $(SERVER_PY) -o $(DOCSDIR)


clean:
	rm -rf $(OUTDIR)
