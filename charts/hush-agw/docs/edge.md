# Exposing Hush AGW

This page and the ones it links to describe the settings of the `hush-agw`
chart that put Hush AGW behind an ingress controller or a cloud load balancer,
through a preset or by hand, with an example for each.

## Options

| Option | Preset | Page |
| :---- | :---- | :---- |
| AWS Application Load Balancer, through the Gateway API | `agw.httpRoute.controller: aws-alb` | [AWS](edge-aws.md#gateway-api) |
| GKE Gateway | `agw.httpRoute.controller: gke-gateway` | [Google Cloud](edge-gcp.md#gke-gateway) |
| Azure Application Gateway for Containers, through the Gateway API | `agw.httpRoute.controller: azure-agc` | [Azure](edge-azure.md#gateway-api) |
| AWS Application Load Balancer, through an Ingress | `agw.ingress.controller: aws-alb` | [AWS](edge-aws.md#ingress) |
| AWS Application Load Balancer, internal | `agw.ingress.controller: aws-alb` with `scheme: internal` | [AWS](edge-aws.md#internal-alb) |
| AWS Network Load Balancer | `agw.service.loadBalancer: aws-nlb` | [AWS](edge-aws.md#network-load-balancer) |
| GKE Ingress | `agw.ingress.controller: gke-ingress` | [Google Cloud](edge-gcp.md#gke-ingress) |
| Azure Application Gateway for Containers, through an Ingress | `agw.ingress.controller: azure-agc` | [Azure](edge-azure.md#ingress) |

Prefer the Gateway API where the cluster offers it: the Kubernetes project
recommends Gateway over Ingress, whose API is frozen. See
[Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/).
Each Gateway API option also shows how to attach Hush AGW to a Gateway that
already runs, such as one a platform team shares.

Each option lists its prerequisites, most with a command that checks whether
the cluster already has them. Install only what is missing, as described at
the end of each page. Then set the option up with its [preset](#presets), or
by hand where the preset does not fit.

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

## Presets

A preset names the load balancer in front of Hush AGW, and the chart then sets
it up for Hush AGW. Each of these settings takes one:

| Setting | Presets |
| :---- | :---- |
| `agw.httpRoute.controller` | `aws-alb`, `gke-gateway`, `azure-agc` |
| `agw.ingress.controller` | `aws-alb`, `gke-ingress`, `azure-agc` |
| `agw.service.loadBalancer` | `aws-nlb` |

Each page shows a preset next to the same setup written by hand. Compared with
that, a preset:

- Replaces the annotations and the objects you would write. It sets the class
  and the annotations of the Ingress, the Service or the Gateway, and creates
  the objects the controller reads its other settings from, such as a
  BackendConfig on GKE or a HealthCheckPolicy on Azure. They belong to the
  release: nothing is created in the namespace before the install,
  `helm upgrade` changes them and `helm uninstall` removes them.
- Meets the [requirements](#what-any-edge-must-do) by default: the health
  check on port 15021, an idle or request timeout of 10 or 30 minutes rather
  than the cloud's 30 or 60 seconds where the load balancer lets it be set,
  and session affinity where the load balancer supports it. On AWS it also
  limits TLS to 1.2 and 1.3. On Google Cloud it takes the name of an SSL
  policy for that, and AGC on Azure does it on its own.
- Names every object after the release, and refers to the Service, the
  HTTPRoute and the Gateway by the names the chart gives them. By hand, the
  controller ignores an object that names the wrong one.
- Takes plain values, such as `idleTimeout: 600`, and writes them in the
  format the controller expects, such as the annotation
  `alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=600`.
- Refuses a combination the cloud rejects or that cannot work, such as sticky
  sessions without cross-zone load balancing on an ALB, or no certificate on
  Azure. The install or upgrade then fails with the reason, rather than leave
  a load balancer that never comes up.
- Sets a few things the chart offers no value for without a preset: it turns
  off the node ports of the NLB's Service, attaches the
  LoadBalancerConfiguration to the chart's own ALB Gateway, gives the chart's
  own GKE Gateway a Compute Engine SSL certificate, sets the request timeout
  of the HTTPRoute on AGC, and attaches the chart's own Gateway to an AGC
  created outside the cluster.

Where a preset does not fit as it is, adjust it rather than drop it. Its
settings, such as `agw.ingress.awsAlb`, are listed on each page. Keys in
`agw.ingress.annotations`, `agw.service.annotations` or
`agw.httpRoute.gateway.annotations` replace the annotations the preset sets.
Each object the preset creates can be turned off, as its page shows, so that
you bring your own.

## Settings

These settings apply with a preset and by hand:

| Setting | Default | What it does |
| :---- | :---- | :---- |
| `agw.hostname` | `""` | The hostname of Hush AGW. Required. The Ingress routes it, and the certificate must be valid for it |
| `agw.service.type` | `ClusterIP` | `ClusterIP`, on port 3001, or `LoadBalancer`, on port 443. A `LoadBalancer` works only where the load balancer terminates TLS itself, since Hush AGW serves plain HTTP. The `aws-nlb` preset makes it `LoadBalancer` |
| `agw.service.annotations` | `{}` | Annotations on the Service: the settings of a cloud load balancer for a `LoadBalancer` Service, or the settings GKE Ingress reads from its backend Service |
| `agw.service.loadBalancerClass` | `""` | `spec.loadBalancerClass` of a `LoadBalancer` Service, which picks the implementation that handles it. It cannot be changed once set |
| `agw.service.loadBalancerSourceRanges` | `[]` | The client addresses a `LoadBalancer` Service admits, as CIDR ranges, where the cloud supports it |
| `agw.httpRoute.enabled` | `false` | Creates the HTTPRoute `hush-agw`: the rule for `agw.hostname`, path `/` of type `PathPrefix`, to the Service |
| `agw.httpRoute.parentRefs` | `[]` | The Gateway listeners the HTTPRoute attaches to, for example `[{name: shared, namespace: gateway-infra, sectionName: https}]`. Required unless `agw.httpRoute.gateway.enabled` is set |
| `agw.httpRoute.annotations` | `{}` | Annotations on the HTTPRoute |
| `agw.httpRoute.gateway.enabled` | `false` | Creates the Gateway `hush-agw`, with one HTTPS listener named `https` on port 443 for `agw.hostname`, which admits routes from the release's namespace only, and attaches the HTTPRoute to it |
| `agw.httpRoute.gateway.className` | `""` | `spec.gatewayClassName` of the Gateway. Required with the Gateway, except that the `gke-gateway` and `azure-agc` presets have a default |
| `agw.httpRoute.gateway.annotations` | `{}` | Annotations on the Gateway, through which some implementations take their settings |
| `agw.httpRoute.gateway.tls.secretName` | `""` | The Secret the listener takes its certificate from, in the release's namespace. Leave it empty where the implementation takes the certificate another way |
| `agw.ingress.enabled` | `false` | Creates the Ingress `hush-agw`: the rule for `agw.hostname`, path `/` of type `Prefix`, to the `gateway` port of the Service |
| `agw.ingress.className` | `""` | `spec.ingressClassName`. When empty, the preset's class applies, or else the cluster's default IngressClass, if it has one |
| `agw.ingress.annotations` | `{}` | Annotations on the Ingress, through which most ingress controllers are configured |
| `agw.ingress.tls.secretName` | `""` | Adds `spec.tls` for `agw.hostname` with this Secret, in the release's namespace. Leave it empty where the controller takes the certificate another way |

The Service, like every object of the chart, is named after the release: the
release name itself when it contains `hush-agw`, such as `hush-agw` in the
install command of the deployment wizard, and `<release>-hush-agw` otherwise.
`fullnameOverride` replaces either. Objects you create by hand that name the
Service, such as the HealthCheckPolicy on [Azure](edge-azure.md), must use
that name, or the controller ignores them. A preset uses it on its own. The
examples assume a release named `hush-agw`.

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
