# hush-am

Hush Access Manager helm chart.

## Upgrading

`helm upgrade` does **not** apply changes to CRDs - Helm only installs CRDs
from the chart's `crds/` directory on first install and never touches them
after that. If a chart upgrade ships an updated CRD schema (new fields,
new printer columns, etc.), the CRDs must be applied manually before the
upgrade.

```shell
kubectl apply -f charts/hush-am/crds/
helm upgrade hush-am ...
```

Existing custom resources remain valid as long as the schema changes are
additive (new optional fields). Their stored objects are not migrated;
they are revalidated against the updated schema on the next read/write.
