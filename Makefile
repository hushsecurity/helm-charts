TOP_DIR=$(shell git rev-parse --show-toplevel)
RELEASE=$(shell git describe --always --first-parent --dirty --exclude="*" --abbrev=10)
CHART?=must-specify-chart

.PHONY: default
default: lint

.PHONY: lint
lint: ct-lint-all
	$(MAKE) -C tests lint
	$(MAKE) -C cli lint

.PHONY: ct-lint-all
ct-lint-all:
	ct lint --all --validate-maintainers=false --skip-helm-dependencies

.PHONY: tests
tests:
	$(MAKE) -C tests tests

.PHONY: release
release:
	cd cli && TOP_DIR=$(TOP_DIR) RELEASE=$(RELEASE) \
		poetry run python3 -m cli release $(CHART)
