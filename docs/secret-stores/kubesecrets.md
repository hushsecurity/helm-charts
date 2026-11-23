# Kubernetes Secrets

`kubesecrets`, the default, keeps each secret in a Kubernetes Secret, in one
namespace of the cluster the chart is installed in.

```yaml
secretStore:
  kind: kubesecrets
  prefix: hush
  k8s:
    # empty for the release namespace
    namespace: ""
```

## Permissions

The store reads, creates, updates and deletes Secrets: the verbs `get`,
`create`, `update` and `delete` on `secrets`. The chart grants them itself, in
the namespace of the store and in each namespace listed in
`secretStore.k8s.additionalNamespaces`:

- `hush-agw` grants these four verbs, with a Role and a RoleBinding in each
  namespace.
- `hush-am` grants every verb on `secrets`: with a Role in the release
  namespace, and with a RoleBinding to a ClusterRole in each other namespace.

Whoever installs the chart must therefore be allowed to create these Roles and
RoleBindings, and hold there the Secret permissions they grant: Kubernetes
refuses to grant a permission its granter does not hold.

## Notes

- The namespace must already exist; the chart does not create it.
- A Kubernetes store created in Hush in a namespace other than the release
  namespace needs that namespace in `secretStore.k8s.additionalNamespaces`.
