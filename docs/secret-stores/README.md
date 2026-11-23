# Secret stores

Hush keeps the credentials it issues, and the keys of its access manager, in a
secret store of your choosing. The `hush-am` and `hush-agw` charts support the
same stores, with the same settings. This page describes what the stores share;
the pages it links to describe each store, with every permission it needs.

## Values

The two charts keep the same settings under different keys:

| | `hush-am` | `hush-agw` |
| :---- | :---- | :---- |
| The store | `secretStore` | `agw.secretStore` |
| The cloud identity of the pod | `accessManager.workloadIdentity` | `agw.workloadIdentity` |
| Service account, for a release named after the chart | `hush-am-access-manager` | `hush-agw` |

The pages use the `hush-am` keys. For `hush-agw`, read `secretStore` as
`agw.secretStore` and `accessManager.workloadIdentity` as
`agw.workloadIdentity`. The identity a store trusts is bound to the service
account in the last row; `kubectl get serviceaccount -n <namespace>` lists it
for another release name: for `hush-am`, the one ending in `-access-manager`.

A `hush-agw` that shares its Hush deployment with `hush-am` must use the store
of `hush-am`: the same kind, prefix and location. The identity of that store
must then trust the service accounts of both charts.

## Stores

| `secretStore.kind` | Store | Max prefix length |
| :---- | :---- | :---- |
| `kubesecrets` (default) | [Kubernetes Secrets](kubesecrets.md) | 80 |
| `awssm` | [AWS Secrets Manager](awssm.md) | 80 |
| `awsssm` | [AWS Systems Manager Parameter Store](awsssm.md) | 80 |
| `gcpsm` | [Google Cloud Secret Manager](gcpsm.md) | 80 |
| `hc_vault` | [HashiCorp Vault, KV version 2](hc_vault.md) | 80 |
| `az_key_vault` | [Azure Key Vault](az_key_vault.md) | 32 |

## Prefix

A secret name is `secretStore.prefix` (default `hush`), the separator of the
store, then a path Hush builds from the deployment and the key; Parameter Store
adds a leading `/`. So a permission limited to `<prefix><separator>*` covers
everything the store writes, and several deployments may share a prefix.

The prefix is lowercase letters and digits, with the punctuation of its store
between them. It starts and ends with a letter or a digit, the separator always
stands between two letters or digits, and `.` never repeats. An invalid prefix
fails the install.

| Store | Punctuation | Separator | Examples | Also |
| :---- | :---- | :---- | :---- | :---- |
| `awssm` | `- _ . + = @ /` | `/` | `hush`, `acme/prod`, `team_a/secrets` | |
| `awsssm` | `- _ . /` | `/` | `hush`, `acme/prod`, `team.a/secrets` | At most 9 segments; must not start with `aws` or `ssm` |
| `gcpsm` | `- _` | `-` | `hush`, `acme-prod`, `team_a` | |
| `kubesecrets` | `- .` | `-` | `hush`, `acme-prod`, `team.a` | |
| `hc_vault` | `- _ . /` | `/` | `hush`, `acme/prod`, `team_a/secrets` | |
| `az_key_vault` | `-` | `-` | `hush`, `acme-prod` | At most 32 characters |

For example, `acme/prod` is a valid prefix for `awssm`, but these are not:

- `Acme/prod`: an uppercase letter.
- `acme prod`: a space.
- `/acme` and `acme/`: punctuation at the start or at the end.
- `acme//prod` and `acme/-prod`: the separator next to other punctuation.
- `acme..prod`: `.` twice in a row.

The prefix cannot change once secrets exist under it.

A prefix outside what the permissions cover installs cleanly, then fails every
write.

## Identity

A store outside the cluster needs the pod to hold an identity there:

| Store | Identity | For testing |
| :---- | :---- | :---- |
| `awssm`, `awsssm` | [IRSA or an IAM role](awssm.md#identity) under `accessManager.workloadIdentity.aws` | |
| `gcpsm` | [GKE Workload Identity](gcpsm.md#identity) under `accessManager.workloadIdentity.gcp` | `secretStore.gcp.credentials_json` |
| `hc_vault` | [Vault `kubernetes` or `jwt` auth](hc_vault.md#identity) | Vault `token` auth |
| `az_key_vault` | [AKS workload identity](az_key_vault.md#identity) under `accessManager.workloadIdentity.azure`, or a service principal | |

`kubesecrets` needs none: the chart grants its permissions itself.

## Stores created in Hush

The stores created on the **Secret Stores** page in Hush are used by every
deployment they are assigned to, beside the store of the chart. Hush gives each
one its kind, prefix and location. They need the permissions their store page
lists, for their own prefix, and take the rest from the chart of each
deployment:

- the identity under `accessManager.workloadIdentity`, whatever
  `secretStore.kind` is.
- `secretStore.gcp.credentials_json`.
- `secretStore.hcVault.timeout`, `auth.audience`, `auth.token` and
  `auth.tokenSecretRef`, shared by every Vault store of the deployment, and
  `secretStore.hcVault.caCert`, for the Vault stores that carry no CA of their
  own. A Vault store that logs in with `kubernetes` or `jwt` needs
  `auth.audience`, bound on its Vault role as [described](hc_vault.md#identity),
  unless the chart's own store is `hc_vault` with `kubernetes` or `jwt` auth,
  since the chart mounts the token for Vault only then.
- `secretStore.azKeyVault.timeout`, `auth.clientSecret` and
  `auth.clientSecretRef`, shared by every Key Vault store of the deployment.
- `secretStore.k8s.additionalNamespaces`, listing the namespaces of the
  Kubernetes stores outside the release namespace.
