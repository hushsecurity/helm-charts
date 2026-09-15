<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

## hush-am 0.27.0 - 2026-09-20

### Added

- `accessManager.workloadIdentity.aws.oidc.role` names an AWS IAM role the access
  manager assumes with its own Kubernetes service account token. This reaches an
  AWS secret store, and an ECR registry, from a cluster that has no IRSA, with no
  AWS access key kept in the cluster.

  Enable the cluster OIDC issuer, register it as an IAM OIDC identity provider,
  and let the role be assumed over that provider by the access manager's service
  account. Its subject is `system:serviceaccount:<namespace>:<account>`, where
  `<account>` is the service account name the chart derives from the release,
  `hush-am-access-manager` for a release named `hush-am`.

  `accessManager.workloadIdentity.aws.oidc.audience` is the audience the identity
  provider is registered with. It defaults to `sts.amazonaws.com`, the audience
  IRSA uses on EKS.

  The role is an AWS identity like `irsa`, so setting it also takes the access
  manager pod off the host network, where it no longer reaches the node's own
  cloud credentials. Reading image manifests from the registry of the cloud the
  cluster runs in may then need that cloud's workload identity configured
  alongside the role:

  ```yaml
  accessManager:
    workloadIdentity:
      aws:
        oidc:
          role: "arn:aws:iam::000000000000:role/access-manager"
      # On AKS, for an Azure container registry
      azure:
        clientId: "00000000-0000-0000-0000-000000000000"
      # On GKE, for a Google container registry
      gcp:
        sa: "access-manager@my-project.iam.gserviceaccount.com"
  ```

  It cannot be combined with any other AWS credential:
  `accessManager.workloadIdentity.aws.irsa`, `secretStore.aws.irsa`,
  `containerRegistry.aws.irsa` or `secretStore.aws.access_key`.

### Added

- `secretStore.kind` accepts `hc_vault`, storing secrets in a HashiCorp Vault
  KV version 2 mount. Configure it under `secretStore.vault`:

      secretStore:
        kind: "hc_vault"
        prefix: "acme/prod"
        vault:
          address: "https://vault.example.com:8200"
          mount: "hush-kv"
          auth:
            method: "kubernetes"
            role: "hush-access-manager"

  `address` is required and must be https: every request carries the Vault
  token in a header and a kubernetes or jwt login posts the pod's service
  account token in the body, so a plaintext address would put a live
  credential on the wire. `mount` defaults to `secret` and must be KV version
  2 -- the access manager checks the mount's version at startup and refuses
  version 1, whose API has no compare-and-set and so cannot tell a create from
  an overwrite. `namespace` names a Vault Enterprise namespace and stays empty
  on Community Edition. `caCert` takes the PEM bundle of a private CA, and is
  not needed for a certificate that chains to a CA the container already
  trusts.

  `auth.method` is one of three:

  - `kubernetes` (the default) presents the pod's service account token, which
    Vault validates by calling the cluster's TokenReview API. Vault must be
    able to reach the API server.
  - `jwt` presents the same token, which Vault validates against keys it
    already holds. For a Vault that cannot reach the API server.
  - `token` uses a token given in `auth.token`, or taken from a pre-existing
    Kubernetes Secret named by `auth.tokenSecret`. Nothing renews it, so it
    stops working when it expires; intended for testing.

  `kubernetes` and `jwt` need `auth.role`, and mount a service account token
  projected for Vault alone, separate from the one the Hush OIDC assertion
  uses -- the audience a Vault role accepts is the operator's choice and has no
  reason to match the one Hush issues against. Set `auth.audience` to the
  role's `bound_audiences` when it names one; leave it empty for the cluster
  default, which a role with no bound audience accepts.

  The Vault role must bind the access manager's service account and the
  namespace the chart is installed in, and grant a policy carrying at least:

      path "<mount>/data/<prefix>/*"     { capabilities = ["create", "update", "read"] }
      path "<mount>/metadata/<prefix>/*" { capabilities = ["read", "delete"] }

  No `list` is needed. A policy missing the metadata grants yields a store
  that reads and writes but can never delete, and Vault answers 403, which
  nothing retries. Leave the role's default policy in place too: `renew-self`
  rides on it, so a role with `token_no_default_policy=true` cannot renew its
  token and falls back to logging in again whenever a request is denied.

  This needs an access manager that carries the `hc_vault` silo. An older
  image installs and then fails to start, reporting an unknown secret store
  kind.

### Changed

- bump the app version to `v0.22.0`, which brings security fixes and SPIRE
  1.15.3.

  With `accessManager.kind` set to `statefulset`, the upgrade migrates the
  SPIRE datastore and cannot be rolled back without restoring it from a backup
  taken beforehand.

- bump the default spire-agent image to `v0.22.0`. The first upgrade after this
  restarts spire-agent pods once to roll out the new image.

- the api controller role now grants `events` in the `events.k8s.io` API group
  beside the core one. From the paired app version on, the controller records
  its `AccessPolicy`, `AccessCredential` and `AccessPrivilege` events through
  `events.k8s.io/v1`, and RBAC matches on the API group, so without this rule
  the api server refuses every one of them.

- `secretStore.prefix` was validated by one pattern for every backend,
  `^[a-z][a-z0-9]{0,9}$`: ten characters, lowercase, no punctuation. It may now
  be up to **80 characters** and carry the punctuation the backend named by
  `secretStore.kind` accepts.

      kind         punctuation      notes
      awssm        - _ . + = @ /
      awsssm       - _ . /          at most 9 '/'-separated segments in the
                                    prefix; may not start with "aws" or "ssm"
      gcpsm        - _
      kubesecrets  - .              a Kubernetes Secret name
      hc_vault     - _ . /          a KV v2 path under the mount

  Lowercase, and a leading digit is now allowed. Punctuation separates segments
  and may not lead or trail one, so `acme/prod/secrets` is accepted while
  `/acme` and `acme/` are not. It may sit next to itself where the kind's
  charset allows the character -- `acme__prod` on `awsssm` -- except the
  separator, and except `.`, which may not repeat for any kind: `acme..prod`
  is an empty label in a Kubernetes Secret name. Each malformation says which
  it is rather than reporting a generic invalid prefix. A prefix cannot be
  changed once secrets exist under it.

  Every value the old pattern accepted still passes, with one exception: for
  `awsssm`, a prefix beginning "aws" or "ssm" is now refused, because Parameter
  Store reserves both and the prefix is the first path element of every
  parameter name. Such an install could never write a secret, so it now fails
  the install rather than every write.

  **A prefix outside the path the access manager's credential covers installs
  cleanly, then fails every write and stays in `error` with a config that
  cannot be edited.** For AWS that credential is an IRSA policy naming
  `secret:<prefix>/*`, and the boundary is a path: under `acme/*`, `acme/prod`
  works and `acme_prod` does not. For `kubesecrets` it is this chart's own
  namespace plus `secretStore.k8s.additionalNamespaces`.

- the vector sidecars now request `96Mi` of memory instead of `64Mi`, under
  `accessManager.vectorResources`, `apiController.vectorResources` and
  `diagnostics.vectorResources`: their resting usage grew past the old
  request. The `256Mi` limit is unchanged. An install that pins these values
  itself should raise them:

  ```yaml
  accessManager:
    vectorResources:
      requests:
        memory: "96Mi"
  ```

## hush-am 0.26.0 - 2026-09-08

### Changed

- bump the app version to `v0.21.0`

  This simplifies `Azure Redis` connector logic, and includes internal improvements.

  The chart is changed to fulfill the new env var contract.

## hush-am 0.25.1 - 2026-09-03

### Changed

- bump the app version to `v0.20.2`.

  This contains a fix for Temporal Cloud connector to issue credentials with maximal
  allowed expiration of 2 years, instead of previous 30 days. This allows workloads
  receiving credentials via env vars to run without restart up to that longer period.

## hush-am 0.25.0 - 2026-08-30

### Added

- `admissionController.failurePolicy` selects what happens to a pod when
  admission does not complete. The default is `Ignore`: the pod is admitted
  without injection, and because Kubernetes never re-runs admission on an
  existing pod, it stays uninjected until something recreates it. `Fail` rejects
  the creation instead, and the controller owning the pod retries it, so the pod
  appears once admission succeeds. This covers every way the call itself can
  fail, not only a controller that is not running, so a cause which does not
  clear keeps the pod rejected.

  That retry is the client issuing the CREATE again; nothing in Kubernetes
  re-runs admission. ReplicaSets, StatefulSets, DaemonSets and Jobs retry
  indefinitely, but a pod created with no owning controller gets one error, a
  static pod runs anyway because only its mirror pod is admitted, and a Job past
  `activeDeadlineSeconds` or a CronJob run missed past `startingDeadlineSeconds`
  stops retrying. Both values also decide only what happens when the webhook
  cannot be called: if it answers but its patch cannot be applied to the pod,
  the creation is rejected either way.

  `Fail` blocks the creation of every pod the webhook is invoked on for as long
  as admission keeps failing, so scope the webhook to the workloads that need
  Hush Access Management:

  ```yaml
  admissionController:
    failurePolicy: "Fail"
    objectSelector:
      type: "labels"
      labels:
        am.hush.security/admission: "true"
  ```

  The label `am.hush.security/admission: "true"` is the installation's own and
  nothing sets it, so with this pairing every workload that needs Hush Access
  Management must carry it. Put it on the **pod template** --
  `spec.template.metadata.labels` of a Deployment, StatefulSet, DaemonSet or
  Job, not the workload's own labels -- because the object the selector matches
  is the pod. A pod without the label is never sent to the webhook, so it is
  admitted without injection and without any rejection to notice.

  The release namespace must stay outside the webhook's scope. With it in scope,
  `Fail` rejects the creation of the access manager's own pod, which is the pod
  that serves the webhook, so the release cannot start and no retry recovers it;
  the chart refuses to render that combination. The default `not_names`
  namespace selector keeps the webhook out of the release namespace,
  kube-system, kube-public and kube-node-lease; workloads in any other namespace
  are gated like the rest.

### Changed

- shutting down the access manager now keeps within
  `accessManager.terminationGracePeriodSeconds` while it finishes the admission
  calls it is already serving, so lowering that value shortens the time those
  calls are given rather than letting them be cut off. A cut-off call counts as
  a failed admission, and under the default `failurePolicy` of `Ignore` that
  starts the pod without injection. Nothing to configure, though the behaviour
  needs an app version that reads the value; an older one shuts down as before.

## hush-am 0.24.0 - 2026-08-18

### Changed

- the admission controller no longer uses a certificate authority baked into
  its image. It now generates a CA per cluster, stored in a secret in the
  release namespace, and publishes that CA into the webhook's `caBundle` itself,
  re-checking on a timer so a cleared or drifted `caBundle` self-heals. The
  chart and image must be upgraded together.

  Publishing is the running controller's own work, so it needs nothing
  configured and behaves the same under every delivery tool (helm, ArgoCD, Flux,
  and raw `kubectl`/kustomize applies).

  During the first upgrade there is a short window, bounded by the rollout, in
  which pods may be created without injection. Prefer a low-churn period. The CA
  secret is not tracked by helm and is not to be deleted; to replace the CA
  deliberately, contact Hush support.

- the chart now requires an app version that ships the admission controller
  which generates and publishes the CA. The chart and image are a matched pair
  and neither half works alone. Both mismatches fail loudly rather than
  degrading: the admission controller exits at startup and the pod
  restart-loops. Do not pin `image.tag` across this upgrade.

- rolling back to an earlier chart version is not supported across this
  upgrade. The previous chart and image restore the certificate authority whose
  private key ships inside the image, which is exactly what this release
  removes, so a rollback reinstates that exposure. If an upgrade has to be
  reversed, contact Hush support.

- a new ClusterRole, `<release>-hush-am-access-manager-webhook-publisher-cluster-role`,
  grants `patch` on the mutating webhook configuration, restricted by name to
  this release's own object, so the controller can keep its `caBundle`
  published. It is bound to the access-manager ServiceAccount alone rather than
  added to the common ClusterRole, which the spire-agent DaemonSet also uses.
  The chart always renders both, so a normal upgrade grants it. If RBAC is
  instead managed out of band --
  a policy engine that rejects the rule, or a ClusterRole edited or pruned
  outside helm -- the grant is the one prerequisite whose absence is quiet: the
  controller starts, serves, and stays ready, but every publish is denied, so
  `caBundle` is never written and the webhook admits pods without injection.
  `patch` on the named object is the whole grant; the controller never reads,
  lists or watches it. The `webhook-cert` diagnostic check reports this state.

### Added

- `admissionController.caBundleRepatchInterval` (default `2m`), the steady-state
  interval at which the controller re-publishes its CA. Install, upgrade and CA
  changes publish promptly regardless; this is the drift-repair backstop and it
  sets the audit-log volume at one write per webhook entry per interval.
  Shorten it on high-churn clusters.

## hush-am 0.23.0 - 2026-08-06

### Added

- `status.foreignId` on `AccessCredential`, `AccessPrivilege` and `AccessPolicy`.
  The api-controller records here the identifier by which this cluster knows the
  resource, so a cluster rebuilt from scratch recognises the entities its
  predecessor created instead of creating a second set.

  Nothing in a manifest changes: the field is written by the controller only, and
  it is additive, so existing custom resources stay valid.

  **Apply the CRDs before upgrading**, as described under Upgrading in this
  chart's README -- `helm upgrade` never updates them. Skipping it leaves the
  field undeclared; the api-controller detects that and keeps its previous
  behaviour, so nothing breaks, but a rebuilt cluster goes on duplicating
  entities until the CRDs are applied.

### Changed

- bump the app version to `v0.19.0`. This adds support for taking over gitops-managed
  objects by their K8S unique identifier (requires CRD additions above) when no
  status is found in (possibly re-created from scratch) cluster.

## hush-am 0.22.1 - 2026-08-03

### Changed

- bump the app version to `v0.18.0`. This adds support for AMR (Azure Managed Redis).
  The chart itself remains unchanged.

## hush-am 0.22.0 - 2026-07-23

### Added

- `accessManager.forcePodNetwork` to keep the access-manager Pod on the Pod
  network even when the chart would otherwise place it on the host network to
  reach cloud instance metadata. Use on installations that do not rely on
  instance-profile credentials (e.g. on-prem), where node-to-node connectivity
  to the SPIRE server port may be blocked by a firewall. `false` by default,
  which keeps the current auto-detection (backward compatible). When enabled,
  the Pod can no longer reach node-local instance metadata and cannot use
  instance-profile credentials, so cloud access must use workload identity
  (IRSA on AWS, a GCP service account, or an Azure client ID); the admission
  controller correspondingly stops authenticating to the container registry
  through the EC2 instance role. Example:

  ```yaml
  accessManager:
    forcePodNetwork: true
  ```

- `hushDeployment.oidc.audience` to set the audience (`aud` claim) of the
  Kubernetes service account token used as the OIDC assertion when
  `hushDeployment.authMode` is `oidc`. Empty by default, which keeps the cluster
  default audience (backward compatible). Example:

  ```yaml
  hushDeployment:
    authMode: oidc
    oidc:
      audience: https://kubernetes.default.svc
  ```

## hush-am 0.21.0 - 2026-07-19

### Added

- `secretStore.k8s.additionalNamespaces` to grant the access manager write
  access to secrets in namespaces other than its own, for k8s secret stores
  placed there via the Secret Store API. The grant is scoped to each listed
  namespace (which must already exist), never cluster-wide. Example:

  ```yaml
  secretStore:
    k8s:
      additionalNamespaces:
        - team-a
        - team-b
  ```

### Changed

- the access manager no longer gets cluster-wide write access to Secrets. When
  the k8s secret store uses a namespace other than its own, write access is
  granted only in that namespace (a namespaced RoleBinding). Cluster-wide
  access to Secrets is now read-only, as needed for reading image-pull secrets.

## hush-am 0.20.0 - 2026-07-06

### Added

- add a PodDisruptionBudget for the access manager so that voluntary node
  disruptions (drain, autoscaler consolidation) evict at most one
  access-manager pod at a time. Created only when `accessManager.replicas`
  is greater than 1. Disable with
  `accessManager.podDisruptionBudget.enabled: false`.

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
