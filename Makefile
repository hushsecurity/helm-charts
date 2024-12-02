.PHONY: default
default: lint

.PHONY: lint
lint: ct-lint-all
	$(MAKE) -C tests lint

.PHONY: lint-all
ct-lint-all:
	ct lint --all --validate-maintainers=false

.PHONY: tests
tests:
	$(MAKE) -C tests tests
