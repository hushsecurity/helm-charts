TOP_DIR:=$(shell git rev-parse --show-toplevel)
TEST_KW?=
VERBOSE?=
NO_SYNC?=

__PYTEST_ARGS = --log-level INFO
__PYTEST_ARGS += --log-format "%(asctime)s.%(msecs)03d %(levelname)s %(message)s"
ifneq ($(TEST_KW),)
__PYTEST_ARGS += -k $(TEST_KW)
endif
ifeq ($(VERBOSE),1)
__PYTEST_ARGS += -vvv
__PYTEST_ARGS += -o log_cli=true
endif

__INSTALL_CMD = sync
ifeq ($(NO_SYNC),1)
__INSTALL_CMD = install
endif

.PHONY: default
default: lint

poetry.lock: pyproject.toml
	@poetry lock

.venv: poetry.lock
	@poetry $(__INSTALL_CMD) --with ci
	@touch .venv

.PHONY: lint
lint: rufflint pylint

.PHONY: rufflint
rufflint: .venv
	@poetry run ruff check $(if $(FIX),--fix)
	@poetry run ruff format --diff
	@poetry run ruff check --select I

.PHONY: pylint
pylint: .venv
	@poetry run pylint --jobs 0 --recursive yes --disable=C,R \
		--ignore-paths .venv .

.PHONY: pyformat
pyformat: .venv
	@poetry run ruff format
	@poetry run ruff check --select I --fix

.PHONY: tests
tests: .venv
	@PYTHONDONTWRITEBYTECODE=1 TOP_DIR=$(TOP_DIR) poetry run \
		pytest -p no:cacheprovider $(__PYTEST_ARGS)
