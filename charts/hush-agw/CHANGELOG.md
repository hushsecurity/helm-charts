<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

## hush-agw 0.9.0 - 2026-10-28

### Added

- the new `agw.secretStore` values choose where the gateway keeps its private
  keys, with the same settings as hush-am's `secretStore`: `kubesecrets` (the
  default), `awssm`, `awsssm`, `gcpsm`, `hc_vault` or `az_key_vault`. With
  the default, the gateway keeps them as Secrets in its own namespace, and the
  chart lets it manage Secrets there. A gateway that shares its Hush
  deployment with hush-am must use the same secret store as hush-am. An Azure
  Key Vault must not have purge protection enabled, and the gateway's identity
  needs get, set, delete and purge on its secrets. For example:

  ```yaml
  agw:
    secretStore:
      kind: awssm
      prefix: hush
      aws:
        region: eu-central-1
  ```

  Upgrading an existing release with `--reuse-values` fails, because that flag
  drops the new chart's defaults; upgrade with explicit values or
  `--reset-then-reuse-values` (Helm 3.14+) instead.

- the new `agw.workloadIdentity` values give the gateway the cloud identity an
  `awssm`, `awsssm`, `gcpsm` or `az_key_vault` secret store is reached with,
  as hush-am's `accessManager.workloadIdentity` does: `aws.irsa` on EKS,
  `aws.oidc.role` to assume an AWS role with the gateway's service account
  token outside EKS, `gcp.sa` on GKE, or `azure.clientId` on AKS. Only the
  gateway's controller containers get the AWS role or the Azure identity.
  Annotations set by hand in `agw.serviceAccount.annotations` and
  `agw.annotations` win over the ones these set. For example:

  ```yaml
  agw:
    workloadIdentity:
      aws:
        irsa: arn:aws:iam::123456789012:role/hush-agw
  ```

### Changed

- bump the app version to v0.11.0. The gateway now generates the
  deployment's private keys, as hush-am does, and keeps them in the secret
  store `agw.secretStore` chooses, and refuses to start without one; this
  release of the chart always configures one. A gateway whose secret store
  differs from that of the hush-am in the same Hush deployment fails to
  start. With `kubesecrets` the namespace is part of the store: a gateway
  installed in another namespace than hush-am sets
  `agw.secretStore.k8s.namespace` to hush-am's.

  - a mongodb application gains a tool that lists the database's
    collections. A mongodb read, update or delete tool given a collection
    that does not exist now fails instead of returning an empty result.
  - a mongodb user created in another database than the one the tools run
    against, such as `admin`, now authenticates. A database name containing
    `%` or `+` now works.
  - an application whose server does not answer is reported as unavailable,
    instead of every tool call waiting out a connect timeout.
  - the gateway images carry the latest CA trust store.

  The rest of the release is internal improvements.

- the Kubernetes API token is mounted only into the gateway containers that
  call the API, no longer into the client-facing gateway container or the
  toolbox.
- a pre-created Secret (`hushDeployment.secretKeyRef`) now takes precedence
  over the inline `hushDeployment.token`/`password`, as the comments on
  those two values said; the overridden inline value is no longer stored in
  the chart's Secret.
- under `hushDeployment.authMode: oidc` an inline `hushDeployment.password`
  is no longer stored in the chart's Secret.
- an empty `hushDeployment.sensorDeploymentSecretName` now requires the
  chart's own credentials instead of referencing a Secret with no name.
- the `hushDeployment.sensorDeploymentSecretName` fallback applies only to a
  chart named hush-agw. Pulled into an umbrella chart under an alias, the
  chart must be given its own credentials; the render fails with
  "'hushDeployment.token' is undefined" otherwise.

### Fixed

- a numeric `hushDeployment.token` or `hushDeployment.password` given with
  `--set` failed the render ("wrong type for value; expected string; got
  int64"); it is now stored as given. A bare number in a values file is
  refused with a message to quote it.

## hush-agw 0.8.0 - 2026-10-18

### Changed

- bump the app version to v0.10.0. The release asks nothing of the chart.

  - a mongodb application can connect over TLS, verifying the server against
    a CA bundle the admin supplies or, without one, skipping certificate
    checks. This is what AWS DocumentDB needs. Direct mongodb connections no
    longer use retryable writes, which DocumentDB rejects.
  - a mongodb password containing a space now authenticates.
  - admins can rate limit tool calls per user or agent, on one tool, a tool
    class or a whole app, either blocking calls past the limit or flagging
    them in the activity log.
  - an MCP server whose provider has switched it off is reported as
    unavailable, with the server's reason, instead of answering every call
    with a bare refusal.
  - a call to an MCP server that answers with plain JSON is now cut off after
    55s; before, it had no limit. A streaming response is not cut off once it
    has started.
  - a single SSE event larger than 16 MiB is refused instead of being buffered
    whole, which could run the gateway out of memory.

  The rest of the release is internal improvements.

- raise the default `agw.genaiToolbox.configSizeLimit` from `2Mi` to `16Mi`.
  Gateways that support TLS for mongodb applications also keep each
  application's CA bundle on this volume, up to 200 KiB apiece. The volume is
  in memory, so the higher limit uses memory only for what is written.

## hush-agw 0.7.1 - 2026-10-09

### Changed

- bump the app version to v0.9.1. The release asks nothing of the chart.

  - a service agent can call the gateway with its own platform token, such as
    a Foundry agent's Entra token.
  - a tool call on an app whose connection has expired or was revoked asks the
    agent to reconnect instead of asking the user for consent.
  - an expired or answered consent request is no longer reported as pending.
  - `hush_search_tools` takes an optional `app` argument.

## hush-agw 0.7.0 - 2026-10-08

### Added

- run a genai-toolbox sidecar in the gateway pod, so the gateway can serve
  database-backed tools. Its resources and config-volume size are the new
  `agw.genaiToolbox.resources` and `agw.genaiToolbox.configSizeLimit` values.

  Upgrading an existing release with `--reuse-values` fails, because that flag
  drops the new chart's defaults; upgrade with explicit values or
  `--reset-then-reuse-values` (Helm 3.14+) instead.

## hush-agw 0.6.1 - 2026-10-05

### Changed

- bump the app version to v0.8.0. The release asks nothing of the chart.

  The Kiro CLI, the Kiro IDE and Amazon Quick Suite are now recognised as the
  agent types `kiro` and `amazon-quick` instead of appearing under the raw
  names they report, so they can be named in an application's allowed agent
  types and show as themselves in the activity log. Upgrading is required
  before those agent types can be used.

  Consent status messages no longer name an empty tool. A status poll used to
  read like a broken request to the agent relaying it to the user.

  `hush_list_apps` reports a `user_required` state, and `hush_connect`, the
  connect-start endpoint and token exchange refuse with that reason rather
  than handing a service agent a sign-in link whose tokens would land under
  the agent. A service agent can still use these apps when acting for a user.

  An upstream that answers with an empty tool list is no longer cached as
  authoritative. Before, if a user's first listing of an app came back empty
  because they could not see its tools, that app stayed empty for them until
  the gateway restarted.

  The rest of the release is internal improvements.

## hush-agw 0.6.0 - 2026-09-22

### Changed

- bump the app version to v0.7.0. The release asks nothing of the chart.

  `hush_connect` and `hush_disconnect`, each taking the app as an argument,
  replace the per-application `hush_<app>_connect` and `hush_<app>_disconnect`
  tools. The rest of the release is internal improvements.

## hush-agw 0.5.0 - 2026-09-18

### Changed

- drop the `HUSH_HIDE_UPSTREAM_TOOLS` variable from the gateway's Deployment.

  It has had no effect since app version v0.3.0, where hiding the upstream tools
  stopped being optional. The gateway behaves the same without it.

- bump the app version to v0.6.0.

  The gateway serves the 2026-07-28 MCP protocol as well as the older one, so
  an agent that has moved to it works. Consent cannot be asked in-band there,
  so such a client is sent to the browser to approve a call.

  A tool an application does not catalogue now takes the default of the class
  the server's own description puts it in, where it used to take the
  application's separate default for uncatalogued tools. Under the shipped
  defaults a tool marked read-only now runs without asking, one marked
  destructive is now refused where it used to ask the user, and one that says
  nothing still asks. An application whose uncatalogued default an administrator
  had changed loses that setting: the read, write and destructive defaults now
  govern catalogued and uncatalogued tools alike.

  A custom application whose server speaks only the 2026-07-28 protocol
  registers with its real tool set instead of failing detection.

  The hush_* tools answer on a deployment with no application registered, where
  every call to them used to fail as if the tool did not exist.

  An application that refuses a tool call no longer ends the agent's session,
  and the refusal names its cause: a missing permission, a login the
  application declined, or a tool it does not have.

  An application whose stored login stops being accepted is reported
  disconnected, so the user is asked to reconnect instead of every call to it
  failing.

  Codex connects applications again and shows why a policy blocked a call,
  where it used to fail with an unexpected-response error and show the user
  nothing.

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
