<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

## hush-sensor [unreleased]

### Added

- add support for `sentry` `k8s` integration configuration. K8s integration is enabled
  by default. To disable it set `sentry.integrations.k8s.enabled=false`
- add `daemonSet.disableJavaProbing` boolean value to allow disabling probing of Java
  applications.

## hush-sensor 0.22.0 - 2025-09-14

### Added

- add support for metrics report in `sensor`, `vermon` and `sentry` vector
- add support for controlling (or disabling) workload sampling
- add support for multiple AWS Assume Role configurations in `sentry`. Previously only
  a single role could be defined.

### Changed

- stop running the DaemonSet on host network
- remove "catch-all" tolerations from Deployments, leave them on DaemonSet only.
  This is done to move Deployments out of cordoned nodes as we have only a single
  instance of them. In the edge case of having no untainted nodes, a user needs to add
  custom tolerations suitable to cluster needs.

## hush-sensor 0.21.0 - 2025-07-03

### Added

- add support for `argocd`. Stop parsing the Deployment Token in the chart.
- add Minimum Supported Sensor Version (MSSV) check to verify that a pinned sensor
  version is compatible with the version of the chart.
  The initial MSSV is `0.25.0`.

### Changed

- stop using the `lookup` Helm function as it is not supported in `argocd`
- change from `Role` to `ClusterRole` in `vermon`
- allow all pods to query `namespaces` to get the `kube-system` UID which is used as
  cluster identifier
- add rules to `sentry` to allow scanning ESO (External Secrets Operator)
- rename helper functions to disambiguate the word `secret`

## hush-sensor 0.20.0 - 2025-06-18

### Added

- add permissions and environment variables required for K8S crawler in `sentry`
- add support for passing the Deployment Token in the same K8S Secret as Deployment
  Password under `hushDeployment.secretKeyRef.tokenKey` key name

## hush-sensor 0.19.0 - 2025-06-10

### Added

- add `Connector` Deployment

### Changed

- make the `sensor` DaemonSet optional
- set `sentry` and `vermon` DNS policy to `ClusterFirst` as those services do not run
  on Host network
