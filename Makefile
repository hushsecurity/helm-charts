.PHONY: default
default: lint

.PHONY: lint
lint: ct-lint-all lint-hush-sensor

.PHONY: lint-all
ct-lint-all:
	ct lint --all --validate-maintainers=false

.PHONY: lint-hush-sensor
lint-hush-sensor:
	helm template --kube-version "1.31" charts/hush-sensor | kubeconform -strict
	helm template --kube-version "1.28" charts/hush-sensor | kubeconform -strict
