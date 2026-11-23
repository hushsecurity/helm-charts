# Azure Key Vault

`az_key_vault` keeps each secret in a secret of one Azure Key Vault.

```yaml
secretStore:
  kind: az_key_vault
  prefix: hush
  azKeyVault:
    vaultUrl: https://<vault>.vault.azure.net
accessManager:
  workloadIdentity:
    azure:
      clientId: <client-id>
```

## Permissions

On the secrets of the vault, in either permission model:

| Azure RBAC data action | Access policy | Used to |
| :---- | :---- | :---- |
| `Microsoft.KeyVault/vaults/secrets/getSecret/action` | Get | read a value |
| `Microsoft.KeyVault/vaults/secrets/setSecret/action` | Set | write a value |
| `Microsoft.KeyVault/vaults/secrets/delete` | Delete | delete a secret |
| `Microsoft.KeyVault/vaults/secrets/purge/action` | Purge | free the name of a deleted secret |

With Azure RBAC, the built-in role **Key Vault Secrets Officer** holds all
four.

The vault must not have purge protection, which cannot be turned off once it
is on. A deleted secret keeps its name until it is purged, so the store purges
every secret it deletes. Without purging, whether refused by purge protection
or by a missing Purge permission, the store never becomes ready.

## Identity

Set `secretStore.azKeyVault.auth.method` to one of:

- **`default`, the identity of the pod.** On AKS that is workload identity:
  set `accessManager.workloadIdentity.azure.clientId` to the client ID of a
  user-assigned managed identity holding the permissions above, and let the
  service account sign in as it:

  ```shell
  az identity federated-credential create --name hush-am \
    --identity-name <identity> --resource-group <resource-group> \
    --issuer "$(az aks show --name <cluster> --resource-group <cluster-resource-group> \
      --query oidcIssuerProfile.issuerUrl --output tsv)" \
    --subject system:serviceaccount:<namespace>:<service-account> \
    --audience api://AzureADTokenExchange
  ```

  See
  [Microsoft Entra Workload ID on AKS](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview).
- **`client_secret`, a service principal**, for a cluster without workload
  identity. Set `auth.tenantId`, `auth.clientId`, and `auth.clientSecretRef` to
  a Secret holding the client secret, in the release namespace. Register the
  application as single-tenant.

## Notes

- The permissions are granted on the vault, so they reach every secret of the
  vault. A vault used by the store alone keeps the store away from other
  secrets.
- `secretStore.azKeyVault.cloud` names the Azure cloud of the vault: `public`
  (the default), `china` or `usgov`.
- The prefix is at most 32 characters, since a Key Vault secret name is at most
  127.
