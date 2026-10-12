# hush-connector

Hush Security Connector helm chart.

The connector gives the Hush platform access to resources on your private
network. It is also shipped inside the `hush-sensor` chart; this chart installs
it on its own, for a cluster that runs no sensor or for running it apart from
the sensor.

## Installing

Create a Kubernetes deployment in the Hush platform and pass its token and
password (or an existing Secret holding them) exactly as for the sensor, with
the same values: `hushDeployment.token`, `hushDeployment.password` or
`hushDeployment.secretKeyRef`, and `image.pullToken` or `image.pullSecretList`.
A render without a token, or without a password in password auth mode, fails.

## Next to a sensor

The chart takes no credentials from a `hush-sensor` release; give it the same
ones, or a `secretKeyRef` and `pullSecretList` naming the Secrets the sensor
was given. Both connectors can run on one deployment while the sensor's is
being switched off, but each request reaches whichever of the two takes it
first, so they must reach the same resources. Once this release is up, disable
the sensor's with `connector.enabled=false` on the sensor release.

Image tags are channel tags (`v0`). Next to a sensor its `vermon` pod restarts
the connector when the channel moves; on its own the images refresh only when
the pod restarts.
