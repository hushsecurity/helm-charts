<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

## hush-agw 0.4.0 - 2026-09-09

### Changed

- raise the default of `agw.dynamicOAuthRegistrationTTL` from 600 to 3600.

  Ten minutes proved too short to finish a connect, so the Hush authorization
  server now holds an unconsented registration for an hour and gives the user
  that long to log in. This value has to match the server, and an installation
  that overrides it in its own values file raises it too.

- bump the app version to v0.5.0.

  A tool an application does not catalogue is now gated by that application's
  default for uncatalogued tools, so it can be blocked or ask for consent.
  Until now such a tool was let through, leaving an uncatalogued destructive
  tool less protected than a catalogued read-only one.

  An agent that connects an application receives a short link it can render as
  a clickable one, instead of the provider's raw authorize URL. A connection
  still waiting for consent is reported as a normal answer rather than as an
  error.

  Agent type policies and the audit trail now cover clients speaking the
  2026-07-28 MCP protocol as well, and a client of either protocol generation
  reaches an application of either.

  An application connected before 2026-08-29 and not used since shows as
  disconnected after the upgrade. Connecting it once restores it; an
  application used since then is unaffected.

## hush-agw 0.3.0 - 2026-08-31

### Added

- report which cluster the gateway runs in.

  The chart now creates a ClusterRole and a ClusterRoleBinding granting the
  gateway `get` on the `kube-system` namespace and nothing else, so its reports
  say which cluster they came from. Installing or upgrading the chart now needs
  permission to create cluster-scoped RBAC.

### Changed

- add an `app.kubernetes.io/component` label to the gateway's Deployment,
  Service, ServiceAccount and PersistentVolumeClaim, naming the role each plays,
  and to the Deployment and Service selectors, so the objects can be selected by
  role rather than by name.

  Upgrading a release installed with an earlier version fails with
  `spec.selector: Invalid value: ...: field is immutable`, because a Deployment's
  selector cannot change once the Deployment exists. Delete the Deployment and
  run the upgrade again, or uninstall and install again under the same release
  name and namespace. The volume claim survives either way, so no state is lost.

- bump the app version to v0.4.1.

  The gateway reports the cluster and the helm context the chart passes it. On
  v0.4.0 it collected them and reported neither.

## hush-agw 0.2.0 - 2026-08-31

### Changed

- pass Hush standard environment variables to vector.

- bump the app version to v0.4.0.

  Consent methods work again against the current Hush backend; on v0.3.0 the
  user is offered nonsense choices. Tool definitions are cached per user, so one
  user's identity can no longer reach another's. A token that expires within the
  minute the gateway still honours is no longer refused, removing a common
  spurious 401.

## hush-agw 0.1.1 - 2026-08-13

### Changed

- bump the app version to v0.3.0. The chart remains otherwise unchanged.

## hush-agw 0.1.0 - 2026-08-13

### Added

- initial release of the Hush Security Agent Gateway chart
