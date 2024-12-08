NO_SYNC?=

__SYNC_ARGS = --sync
ifeq ($(NO_SYNC),1)
__SYNC_ARGS =
endif

.PHONY: default
default: lint

poetry.lock: pyproject.toml
	@poetry lock --no-update
	@touch $@

.venv: poetry.lock
	@poetry install --with ci $(__SYNC_ARGS)
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
