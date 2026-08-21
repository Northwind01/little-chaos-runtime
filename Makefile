SHELL := /usr/bin/env bash

# Live session defaults (override on the command line).
LAB_ROOT ?= $(abspath ../gr00t-wbc-lab)
SCENARIO ?= little_chaos
PROMPT ?= Find the girl.
MODEL ?=
SESSION_NAME ?= littlechaos
WITH_CONTAINERS ?= 1
ATTACH ?= 1
PYTHON ?= python3

.PHONY: help shell live live-down session session-down test install-live

help:
	@echo "little-chaos-runtime targets:"
	@echo "  make shell              Offline/demo shell (mock planner)"
	@echo "  make live MODEL=...     Autonomous tmux stack (sim+controller+policy+runtime+inference)"
	@echo "  make live-down          Tear down live tmux session"
	@echo "  make test               Run pytest"
	@echo "  make install-live       pip install -e '.[live]' (needs a venv; system Python may refuse)"
	@echo
	@echo "Live example:"
	@echo "  make live MODEL=/checkpoints/littlechaos_x1_lora_proj/checkpoint-10000"
	@echo
	@echo "Optional: LAB_ROOT SCENARIO PROMPT SESSION_NAME WITH_CONTAINERS=0 ATTACH=0"

shell:
	$(PYTHON) -m little_chaos.cli.shell

# Aliases matching lab naming.
live session: _require-model
	LAB_ROOT="$(LAB_ROOT)" \
	SCENARIO="$(SCENARIO)" \
	PROMPT="$(PROMPT)" \
	MODEL="$(MODEL)" \
	SESSION_NAME="$(SESSION_NAME)" \
	WITH_CONTAINERS="$(WITH_CONTAINERS)" \
	ATTACH="$(ATTACH)" \
	./scripts/live_session.sh

live-down session-down:
	LAB_ROOT="$(LAB_ROOT)" SESSION_NAME="$(SESSION_NAME)" ./scripts/live_session_down.sh

test:
	$(PYTHON) -m pytest -c pyproject.toml tests

install-live:
	$(PYTHON) -m pip install -e '.[live]'

_require-model:
	@[[ -n "$(MODEL)" ]] || { echo "ERROR: set MODEL=/checkpoints/<ckpt> (container path)"; exit 1; }
