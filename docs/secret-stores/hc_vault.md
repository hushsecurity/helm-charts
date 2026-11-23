# HashiCorp Vault

`hc_vault` keeps each secret at a path of a Vault KV version 2 secrets engine.

```yaml
secretStore:
  kind: hc_vault
  prefix: hush
  hcVault:
    address: https://vault.example.com:8200
    # empty for "secret"
    mount: secret
    auth:
      method: kubernetes
      role: hush-am
      audience: vault
```

## Permissions

A Vault policy on the mount:

```hcl
path "<mount>/data/<prefix>/*" {
  capabilities = ["create", "update", "read"]
}

path "<mount>/metadata/<prefix>/*" {
  capabilities = ["read", "delete"]
}
```

```shell
vault policy write hush-am hush-am.hcl
```

Keep the `default` policy on the token as well: it lets the store renew its
token instead of logging in again.

Without the `metadata` grants the store cannot delete, and a store created in
Hush never becomes ready.

## Identity

Set `secretStore.hcVault.auth.method` to one of:

- **`kubernetes`.** The pod logs in with its service account token, which Vault
  checks through the TokenReview API of the cluster, so Vault must reach the
  cluster's API server. See
  [Kubernetes auth method](https://developer.hashicorp.com/vault/docs/auth/kubernetes).

  Bind the role to the service account:

  ```shell
  vault write auth/kubernetes/role/hush-am \
    bound_service_account_names=<service-account> \
    bound_service_account_namespaces=<namespace> \
    audience=vault \
    token_policies=hush-am
  ```
- **`jwt`.** The pod logs in with the same token, whose signature Vault checks
  against the cluster's public keys, set on the auth mount as static keys or as
  the cluster's OIDC discovery or JWKS URL. With static keys, Vault needs no
  network access to the cluster, but they must be updated when the cluster
  rotates its keys.

  ```shell
  vault write auth/jwt/role/hush-am \
    role_type=jwt \
    user_claim=sub \
    bound_subject=system:serviceaccount:<namespace>:<service-account> \
    bound_audiences=vault \
    token_policies=hush-am
  ```

- **`token`, for testing.** Set `secretStore.hcVault.auth.token`, or
  `auth.tokenSecretRef` to a Secret holding it. Nothing renews it.

For `kubernetes` and `jwt`, `secretStore.hcVault.auth.audience` is the audience
of the token, and must be the one the role binds: `audience` on a `kubernetes`
role, `bound_audiences` on a `jwt` one. `auth.mount` names an auth mount at
another path than `kubernetes` or `jwt`.

## Notes

- The address must be `https`. `secretStore.hcVault.caCert` holds the CA of a
  server certificate that does not chain to a public root.
- The mount must exist and be KV version 2. A version 1 mount is refused when
  the store starts. A missing one is not: Vault answers for it as for a mount
  the token cannot see, so it shows only once the store fails to write.
- `secretStore.hcVault.namespace` names the Vault Enterprise namespace of the
  mount.
