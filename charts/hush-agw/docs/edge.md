# Exposing Hush AGW

This page and the ones it links to describe the settings of the `hush-agw`
chart that put Hush AGW behind an ingress controller or a cloud load balancer,
with an example for each.

## Options

| Option | Page |
| :---- | :---- |
| AWS Application Load Balancer, through the Gateway API | [AWS](edge-aws.md#gateway-api) |
| GKE Gateway | [Google Cloud](edge-gcp.md#gke-gateway) |
| Azure Application Gateway for Containers, through the Gateway API | [Azure](edge-azure.md#gateway-api) |
| AWS Application Load Balancer, through an Ingress | [AWS](edge-aws.md#ingress) |
| AWS Application Load Balancer, internal | [AWS](edge-aws.md#internal-alb) |
| AWS Network Load Balancer | [AWS](edge-aws.md#network-load-balancer) |
| GKE Ingress | [Google Cloud](edge-gcp.md#gke-ingress) |
| Azure Application Gateway for Containers, through an Ingress | [Azure](edge-azure.md#ingress) |

Prefer the Gateway API where the cluster offers it: the Kubernetes project
recommends Gateway over Ingress, whose API is frozen. See
[Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/).
Each Gateway API option also shows how to attach Hush AGW to a Gateway that
already runs, such as one a platform team shares.

Each example lists its prerequisites, most with a command that checks whether
the cluster already has them. Install only what is missing, as described at
the end of each page.

## What any edge must do

Hush AGW serves plain HTTP on the port named `gateway` of the `hush-agw`
Service: port 3001 when the Service is `ClusterIP`, port 443 when it is
`LoadBalancer`. It holds no certificate. Whatever fronts it must:

- terminate TLS on port 443 with a certificate valid for `agw.hostname`;
- send every path of `agw.hostname` to Hush AGW, not only `/mcp`. Hush AGW
  also serves the pages users see while they connect an application;
- health check port 15021, path `/healthz/ready`. Port 3001 answers 404 on
  `/`, which a default HTTP health check takes for a failure. A firewall
  between the load balancer and the pods must let both ports through: 3001
  for traffic and 15021 for the health check;
- keep a connection open far longer than the 30 to 60 seconds many load
  balancers allow. MCP holds a connection open for a whole session, and a
  response can stream for minutes.

`agw.hostname` must be exactly the hostname recorded on the deployment in
Hush, since nothing reconciles the two. The AI clients, and the browsers of
the users and admins who connect applications, must reach it over HTTPS. The
Hush backend never connects to Hush AGW itself: it sends browsers there.

The chart refuses an HTTPRoute together with an Ingress, and either of them
together with a `LoadBalancer` Service, since each pair would put two load
balancers in front of Hush AGW.

## Settings

These settings put Hush AGW behind an edge set up by hand:

| Setting | Default | What it does |
| :---- | :---- | :---- |
| `agw.hostname` | `""` | The hostname of Hush AGW. Required. The Ingress routes it, and the certificate must be valid for it |
| `agw.service.type` | `ClusterIP` | `ClusterIP`, on port 3001, or `LoadBalancer`, on port 443. A `LoadBalancer` works only where the load balancer terminates TLS itself, since Hush AGW serves plain HTTP |
| `agw.service.annotations` | `{}` | Annotations on the Service: the settings of a cloud load balancer for a `LoadBalancer` Service, or the settings GKE Ingress reads from its backend Service |
| `agw.service.loadBalancerClass` | `""` | `spec.loadBalancerClass` of a `LoadBalancer` Service, which picks the implementation that handles it. It cannot be changed once set |
| `agw.service.loadBalancerSourceRanges` | `[]` | The client addresses a `LoadBalancer` Service admits, as CIDR ranges, where the cloud supports it |
| `agw.httpRoute.enabled` | `false` | Creates the HTTPRoute `hush-agw`: the rule for `agw.hostname`, path `/` of type `PathPrefix`, to the Service |
| `agw.httpRoute.parentRefs` | `[]` | The Gateway listeners the HTTPRoute attaches to, for example `[{name: shared, namespace: gateway-infra, sectionName: https}]`. Required unless `agw.httpRoute.gateway.enabled` is set |
| `agw.httpRoute.annotations` | `{}` | Annotations on the HTTPRoute |
| `agw.httpRoute.gateway.enabled` | `false` | Creates the Gateway `hush-agw`, with one HTTPS listener named `https` on port 443 for `agw.hostname`, which admits routes from the release's namespace only, and attaches the HTTPRoute to it |
| `agw.httpRoute.gateway.className` | `""` | `spec.gatewayClassName` of the Gateway. Required with the Gateway |
| `agw.httpRoute.gateway.annotations` | `{}` | Annotations on the Gateway, through which some implementations take their settings |
| `agw.httpRoute.gateway.tls.secretName` | `""` | The Secret the listener takes its certificate from, in the release's namespace. Leave it empty where the implementation takes the certificate another way |
| `agw.ingress.enabled` | `false` | Creates the Ingress `hush-agw`: the rule for `agw.hostname`, path `/` of type `Prefix`, to the `gateway` port of the Service |
| `agw.ingress.className` | `""` | `spec.ingressClassName`. When empty, the cluster's default IngressClass applies, if it has one |
| `agw.ingress.annotations` | `{}` | Annotations on the Ingress, through which most ingress controllers are configured |
| `agw.ingress.tls.secretName` | `""` | Adds `spec.tls` for `agw.hostname` with this Secret, in the release's namespace. Leave it empty where the controller takes the certificate another way |

`agw.httpRoute.controller`, `agw.ingress.controller` and
`agw.service.loadBalancer` stay empty in these examples: they select the
chart's presets, which set the same annotations and objects for you.

The Service, like every object of the chart, is named after the release: the
release name itself when it contains `hush-agw`, such as `hush-agw` in the
install command of the deployment wizard, and `<release>-hush-agw` otherwise.
`fullnameOverride` replaces either. Objects that name the Service, such as the
HealthCheckPolicy on [Azure](edge-azure.md), must use that name, or the
controller ignores them. The examples assume a release named `hush-agw`.

## Using an example

Each example lists only its own values. The rest of the install command, with
the image pull token and the deployment's credentials, comes from the
deployment wizard in Hush. Put the example's values in a file and add it with
`-f`, before the chart reference:

```bash
helm install hush-agw -n hush-security --create-namespace \
  ... \
  -f hush-agw-edge.yaml \
  oci://ghcr.io/hushsecurity/helm-charts/hush-agw
```

Replace the placeholders, such as `gw.example.com`, the certificate ARN and the
email address, with your own, in the values and in the objects you create.
The wizard's command already sets `agw.hostname` with `--set`, which takes
precedence over the file.
