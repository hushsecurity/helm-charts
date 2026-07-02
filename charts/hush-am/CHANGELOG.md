<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

## hush-am 0.19.1 - 2026-07-05

### Changed

- bump `appVersion` from `v0.15.0` to `v0.16.0`. No chart-template changes.

## hush-am 0.19.0 - 2026-06-25

### Added

- `admissionController.injectorSpireAgentWaitDuration` /
  `injectorSpireAgentWaitStep` to control how long an injected workload waits
  for the node's SPIRE agent before starting. Unset by default (the injector's
  built-in 30s timeout, after which the workload starts without its injected
  secrets if the agent is not ready). Set `injectorSpireAgentWaitDuration` to
  `"-1s"` to wait indefinitely (recommended where nodes scale up, e.g.
  Karpenter) or to a bounded duration like `"300s"`.
- `admissionController.injectorFailureStrategy` to choose what happens when the
  injector cannot fetch a workload's secrets: unset keeps the default
  (`continue` -- the workload starts without its injected secrets); `"abort"`
  fails the workload so it never starts without them.

### Changed

- bump `appVersion` from `v0.14.0` to `v0.15.0`, which ships the injector
  image that reads the new `injectorSpireAgentWaitDuration` /
  `injectorSpireAgentWaitStep` knobs, so the wait knob now functions.
- bump the default spire-agent image to `v0.14.0`. The first upgrade after this
  restarts spire-agent pods once to roll out the new image.
- spire-agent pods no longer restart on every chart upgrade, but only when
  their actual configuration changes. As part of this, spire-agent pods no
  longer carry the `helm.sh/chart` and `app.kubernetes.io/version` labels
  (the spire-agent DaemonSet object still does).

## hush-am 0.18.1 - 2026-06-12

### Changed

- bump `appVersion` from `v0.13.0` to `v0.14.0`. No chart-template changes.

## hush-am 0.18.0 - 2026-06-09

### Added

- add a `diagnostics` Deployment that runs `diag` in daemon mode, performing
  periodic health checks from inside the cluster. Controlled by
  `diagnostics.enabled` (default `true`).
- add a healthcheck webhook entry to the MutatingWebhookConfiguration,
  gated on `diagnostics.enabled`.

### Changed

- add `namespaces:get` permission to api-controller's ClusterRole to allow it
  query `kube-system` namespace UID as cluster identifier

## hush-am 0.17.0 - 2026-05-25

### Added

- add support for a custom KMS key id in AWS Secrets Manager and AWS SSM
  secret stores via `secretStore.aws.kmsKeyId`.
- add `livenessProbe` and `readinessProbe` to the API Controller Deployment,
  configurable under `apiController.livenessProbe` and
  `apiController.readinessProbe`.

### Changed

- document in the README how to install CRDs from the `oci://` registry
  (`helm pull --untar` + `kubectl apply -f hush-am/crds/`) instead of from a
  local checkout.

## hush-am 0.16.1 - 2026-05-19

### Changed

- bump `appVersion` from `v0.11.0` to `v0.11.1`. No chart-template changes.

## hush-am 0.16.0 - 2026-05-15

### Added

- add `remoteName` + `type` option on `accessCredentialRef` and
  `accessPrivilegeRefs` in the `AccessPolicy` CRD. The API Controller
  resolves the pair to an id via Hush UAM, alongside the existing `name`
  (in-cluster CR) and `id` (externally-managed) options.

## hush-am 0.15.1 - 2026-05-10

### Changed

- bump `appVersion` from `v0.10.0` to `v0.10.1`. No chart-template changes.

## hush-am 0.15.0 - 2026-05-10

### Added

- deploy an API Controller (Deployment, Role, ServiceAccount) and the
  supporting "electric" infrastructure used to sync CRD status from the
  cluster to Hush UAM.
- grant the API Controller cluster-wide `get` on
  `customresourcedefinitions` so it can observe schema changes.
- add `modifiedAt` and other status-related fields to the status of all
  CRDs (`AccessPolicy`, `AccessCredential`, `AccessPrivilege`).
- document the CRD upgrade procedure in the chart README.

### Changed

- drop the `Enabled` printer column from the `AccessPolicy` CRD and remove
  the default for `spec.enabled`.
