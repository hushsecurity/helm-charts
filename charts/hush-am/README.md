# hush-am

Hush Access Manager helm chart.

## Admission controller certificate

The admission controller generates a certificate authority on first start,
stores it in a secret in the release namespace, and publishes it into the
`caBundle` of the mutating webhook configuration. It re-checks that field every
`admissionController.caBundleRepatchInterval` (2 minutes by default), so a
cleared or drifted `caBundle` is repaired without any helm or operator action.

**Do not delete the CA secret.** It is not tracked by helm, so an uninstall
leaves it in place and a reinstall adopts it. Deleting it makes the controller
generate a replacement on its next re-check and re-issue every replica's
certificate against it. Nothing restarts, but pods created in that window may
start without injection, and deleting the secret repeatedly keeps that churn
going. To replace the CA deliberately, contact Hush support for the rotation
procedure.

The `webhook-cert` diagnostic check reports whether the certificate the
controller serves is trusted by the published `caBundle`. Treat it as a
backstop rather than a verdict on the whole deployment: the access-manager
service pins a client to one replica, so the check can report a healthy replica
while another serves a certificate the API server rejects. The controllers
detect that themselves and re-issue their certificates to recover.

### GitOps

The chart deliberately does not render `caBundle`, since the controller owns it
at runtime. If your diff configuration reports the field as out of sync or
prunes it, exclude it:

```yaml
ignoreDifferences:
  - group: admissionregistration.k8s.io
    kind: MutatingWebhookConfiguration
    jqPathExpressions:
      - .webhooks[].clientConfig.caBundle
```

The expression matches every entry, so it holds whether or not
`diagnostics.enabled` adds the healthcheck entry.

## Upgrading

`helm upgrade` does **not** apply changes to CRDs - Helm only installs CRDs
from the chart's `crds/` directory on first install and never touches them
after that. If a chart upgrade ships an updated CRD schema (new fields,
new printer columns, etc.), the CRDs must be applied manually before the
upgrade.

```shell
helm pull oci://ghcr.io/hushsecurity/helm-charts/hush-am --untar
kubectl apply -f hush-am/crds/
helm upgrade hush-am ...
```

Existing custom resources remain valid as long as the schema changes are
additive (new optional fields). Their stored objects are not migrated;
they are revalidated against the updated schema on the next read/write.
