<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

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
