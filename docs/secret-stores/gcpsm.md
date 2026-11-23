# Google Cloud Secret Manager

`gcpsm` keeps each secret in a Google Cloud Secret Manager secret, with
automatic replication, in one project.

```yaml
secretStore:
  kind: gcpsm
  prefix: hush
  gcp:
    projectId: <project>
accessManager:
  workloadIdentity:
    gcp:
      sa: hush-am@<project>.iam.gserviceaccount.com
```

## Permissions

On the project:

| Permission | Used to |
| :---- | :---- |
| `secretmanager.secrets.create` | create a secret |
| `secretmanager.versions.add` | write a value |
| `secretmanager.versions.access` | read a value |
| `secretmanager.secrets.delete` | delete a secret |

No predefined role holds these alone; `roles/secretmanager.admin` holds them
and more. A custom role holds exactly these:

```shell
gcloud iam roles create hushSecretStore --project=<project> \
  --title="Hush secret store" \
  --permissions=secretmanager.secrets.create,secretmanager.secrets.delete,secretmanager.versions.add,secretmanager.versions.access

gcloud projects add-iam-policy-binding <project> \
  --member=serviceAccount:hush-am@<project>.iam.gserviceaccount.com \
  --role=projects/<project>/roles/hushSecretStore
```

## Identity

Choose one:

- **GKE Workload Identity.** Set `accessManager.workloadIdentity.gcp.sa` to a
  Google service account holding the permissions above, and let the Kubernetes
  service account act as it:

  ```shell
  gcloud iam service-accounts add-iam-policy-binding \
    hush-am@<project>.iam.gserviceaccount.com \
    --role=roles/iam.workloadIdentityUser \
    --member="serviceAccount:<cluster-project>.svc.id.goog[<namespace>/<service-account>]"
  ```

  `<cluster-project>` is the project of the GKE cluster, which may differ from
  the project of the secrets.

  See
  [Workload Identity Federation for GKE](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity).
- **A service account key, for testing.** Set
  `secretStore.gcp.credentials_json` to the key JSON.

## Notes

- The role is granted on the project, so it reaches every secret of the
  project. A project used by the store alone keeps the store away from other
  secrets.
- Writing a value to an existing secret adds a version and keeps the earlier
  ones until the secret is deleted.
