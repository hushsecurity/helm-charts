# Exposing Hush AGW on Google Cloud

GKE Gateway and GKE Ingress put Hush AGW behind an external Application Load
Balancer. For what any edge must do and the settings the examples use, see
[Exposing Hush AGW](edge.md).

## GKE Gateway

Tested on GKE Standard, with the policies below as the chart's `gke-gateway`
preset renders them, and with a certificate map.

GKE Gateway creates a global external Application Load Balancer for a
Gateway of the class `gke-l7-global-external-managed`, and sends the requests
of the chart's HTTPRoute to the Hush AGW pods. The chart creates the Gateway
and the HTTPRoute. The settings of the load balancer go into policy objects,
which you create. Google recommends the Gateway API over GKE Ingress. See
[About Gateway API](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/gateway-api).

### Prerequisites

- A VPC-native cluster: Google supports the Gateway API on VPC-native
  clusters only. This prints `True` for one:
  `gcloud container clusters describe CLUSTER_NAME --location LOCATION --format='value(ipAllocationPolicy.useIpAliases)'`.
- The HTTP load balancing add-on, on by default, which Autopilot cannot turn
  off. It is on when this prints nothing or `False`:
  `gcloud container clusters describe CLUSTER_NAME --location LOCATION --format='value(addonsConfig.httpLoadBalancing.disabled)'`.
  See [HTTP load balancing add-on](#http-load-balancing-add-on).
- The Gateway API, always on in Autopilot:
  `kubectl get gatewayclass gke-l7-global-external-managed`. See
  [Gateway API](#gateway-api).
- An SSL policy in the cluster's project, for TLS 1.2 or later:
  `gcloud compute ssl-policies describe hush-agw-tls`. See
  [SSL policy](#ssl-policy).
- A certificate for the hostname: a Certificate Manager certificate map with a
  Google-managed certificate,
  `gcloud certificate-manager maps describe hush-agw`, or a Secret. See
  [Certificate Manager certificate](#certificate-manager-certificate).
- A DNS zone where you can create the hostname's A record.
- On a cluster in a service project of a Shared VPC, the firewall rules that
  let Google's proxies and health checks reach the pods, which GKE cannot
  create in the host project by default. See
  [Shared VPC](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/ingress-routing-security#shared_vpc).

### Create the policies

Create them in the release's namespace before installing, after
`kubectl create namespace hush-security`:

```yaml
apiVersion: networking.gke.io/v1
kind: HealthCheckPolicy
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  default:
    config:
      type: HTTP
      httpHealthCheck:
        portSpecification: USE_FIXED_PORT
        port: 15021
        requestPath: /healthz/ready
  targetRef:
    group: ""
    kind: Service
    name: hush-agw
---
apiVersion: networking.gke.io/v1
kind: GCPBackendPolicy
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  default:
    timeoutSec: 1800
    sessionAffinity:
      type: GENERATED_COOKIE
  targetRef:
    group: ""
    kind: Service
    name: hush-agw
---
apiVersion: networking.gke.io/v1
kind: GCPGatewayPolicy
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  default:
    sslPolicy: hush-agw-tls
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: hush-agw
```

- The HealthCheckPolicy probes port 15021, path `/healthz/ready`. GKE Gateway
  does not infer a health check from the readiness probe of the pods: without
  the policy it probes the serving port at `/`, which answers 404.
- `timeoutSec` bounds a whole response, 30 seconds by default: from the first
  byte of the request sent to the backend to the last byte of the response. A
  stream that lasts longer is cut, and the MCP client reconnects. 1800 lets it
  last 30 minutes.
- `GENERATED_COOKIE` keeps a client on the Hush AGW pod that served it before,
  which answers it faster, through a cookie the load balancer sets, for
  clients that send it back. Google now recommends a
  GCPTrafficDistributionPolicy for the affinity, from GKE 1.35.2-gke.1269001,
  and keeps supporting the GCPBackendPolicy.
- The GCPGatewayPolicy attaches the SSL policy to the Gateway, which has none
  by default and then accepts TLS 1.0 and later.

The HealthCheckPolicy and the GCPBackendPolicy name the Service, `hush-agw` for
a release of that name, and the GCPGatewayPolicy names the chart's Gateway,
`hush-agw` too. See
[Configure Gateway resources using Policies](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/configure-gateway-resources).

### Values

```yaml
agw:
  hostname: gw.example.com
  httpRoute:
    enabled: true
    gateway:
      enabled: true
      className: gke-l7-global-external-managed
      annotations:
        networking.gke.io/certmap: hush-agw
```

The chart creates the Gateway `hush-agw`, with one HTTPS listener on port 443
for the hostname, and the HTTPRoute that sends every path of the hostname to
Hush AGW. The `networking.gke.io/certmap` annotation names the certificate
map. For a Secret instead, leave the annotation out and set
`gateway.tls.secretName`: GKE refuses the two together. A Google-managed
Compute Engine certificate needs a listener option that only the chart's
`gke-gateway` preset sets.

### On a Gateway of your own

Where a Gateway already runs, for example one a platform team shares, attach
the HTTPRoute to its listener rather than create a Gateway:

```yaml
agw:
  hostname: gw.example.com
  httpRoute:
    enabled: true
    parentRefs:
      - name: shared
        namespace: gateway-infra
        sectionName: https
```

Create the HealthCheckPolicy and the GCPBackendPolicy as above: they configure
the backend of Hush AGW on any Gateway. The certificate and the SSL policy
belong to that Gateway. Its listener must meet the
[requirements](edge.md#what-any-edge-must-do) and admit routes from the
`hush-security` namespace.

### TLS and the certificate

- **Termination.** The load balancer's Google Front Ends terminate TLS on port
  443, and send the requests to the pods over plain HTTP, on port 3001. The
  Gateway has no listener on port 80. The GCPGatewayPolicy limits it to TLS
  1.2 or later. See
  [Secure a Gateway](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/secure-gateway).
- **Issuance.** Certificate Manager issues the Google-managed certificate once
  the CNAME record of its DNS authorization resolves. Unlike the
  ManagedCertificate of GKE Ingress, it does not wait for the hostname to point
  at the load balancer, so the certificate can be ready before the install.
- **Rotation.** Google renews the certificate on its own, as long as the DNS
  authorization's CNAME record stays in place and is the only record of its
  name. See
  [Certificate Manager overview](https://docs.cloud.google.com/certificate-manager/docs/overview)
  and [Deploy a Google-managed certificate with DNS authorization](https://docs.cloud.google.com/certificate-manager/docs/deploy-google-managed-dns-auth).
  With a Secret, whoever writes the Secret renews the certificate. Google does
  not document whether the load balancer follows a changed Secret.

### After the install

The Gateway shows the load balancer's IP address once it is `Programmed`.
Point the hostname's A record at it:

```bash
kubectl get gateway hush-agw -n hush-security
```

## GKE Ingress

Tested on GKE Standard.

GKE creates an external Application Load Balancer for the Ingress. Google
recommends [GKE Gateway](#gke-gateway) over GKE Ingress for new work. It reads
the load balancer's settings from annotations on the Ingress and on the
Service, and from the objects they name: a BackendConfig, a
ManagedCertificate and a FrontendConfig.

### Prerequisites

- A VPC-native cluster. Container-native load balancing, which sends requests
  straight to the pods, and session affinity both need it. This prints `True`
  for one:
  `gcloud container clusters describe CLUSTER_NAME --location LOCATION --format='value(ipAllocationPolicy.useIpAliases)'`.
  See [GKE Ingress](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/ingress).
- The HTTP load balancing add-on, on by default, which Autopilot cannot turn
  off. It is on when this prints nothing or `False`:
  `gcloud container clusters describe CLUSTER_NAME --location LOCATION --format='value(addonsConfig.httpLoadBalancing.disabled)'`.
  See [HTTP load balancing add-on](#http-load-balancing-add-on).
- An SSL policy in the cluster's project, for TLS 1.2 or later:
  `gcloud compute ssl-policies describe hush-agw-tls`. See
  [SSL policy](#ssl-policy).
- A domain name you own, no longer than 63 characters, and the DNS zone where
  you can create its A record.
- On a cluster in a service project of a Shared VPC, the firewall rules that
  let Google's proxies and health checks reach the pods, which GKE cannot
  create in the host project by default. See
  [Shared VPC](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/ingress-routing-security#shared_vpc).

### Create the BackendConfig, ManagedCertificate and FrontendConfig

Create them in the release's namespace before installing. Create the namespace
first, since the install command creates it only when it runs:

```bash
kubectl create namespace hush-security
```

```yaml
apiVersion: cloud.google.com/v1
kind: BackendConfig
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  timeoutSec: 1800
  healthCheck:
    type: HTTP
    port: 15021
    requestPath: /healthz/ready
  sessionAffinity:
    affinityType: GENERATED_COOKIE
---
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  domains:
    - gw.example.com
---
apiVersion: networking.gke.io/v1beta1
kind: FrontendConfig
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  redirectToHttps:
    enabled: true
  sslPolicy: hush-agw-tls
```

- `timeoutSec` bounds a whole response, 30 seconds by default: Google defines
  it as the time from the first byte of the request sent to the backend to the
  last byte of the response. A stream that lasts longer is cut, and the MCP
  client reconnects. 1800 lets it last 30 minutes.
- `healthCheck` probes port 15021, path `/healthz/ready`, over HTTP. Without
  it GKE probes the serving port, 3001, at the path of the readiness probe,
  which port 3001 does not serve, so the pods never turn healthy. GKE takes
  the port of the readiness probe only when it is the port the Service sends
  traffic to. See
  [Ingress health checks](https://docs.cloud.google.com/kubernetes-engine/docs/troubleshooting/ingress-health-checks).
- `GENERATED_COOKIE` keeps a client on the Hush AGW pod that served it before,
  which answers it faster, through a cookie the load balancer sets, for
  clients that send it back.
- `redirectToHttps` answers plain HTTP on port 80 with a 301 to HTTPS, rather
  than serve Hush AGW there.
- `sslPolicy` names the [SSL policy](#ssl-policy) of the prerequisites.

See [Configure Ingress features](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/ingress-configuration)
and [Timeouts and retries](https://docs.cloud.google.com/load-balancing/docs/https/request-distribution).

### Values

```yaml
agw:
  hostname: gw.example.com
  service:
    annotations:
      cloud.google.com/neg: '{"ingress": true}'
      cloud.google.com/backend-config: '{"default": "hush-agw"}'
  ingress:
    enabled: true
    annotations:
      kubernetes.io/ingress.class: gce
      networking.gke.io/managed-certificates: hush-agw
      networking.gke.io/v1beta1.FrontendConfig: hush-agw
```

| Setting | On | Value | Purpose |
| :---- | :---- | :---- | :---- |
| `cloud.google.com/neg` | Service | `{"ingress": true}` | Container-native load balancing: the load balancer sends requests straight to the pods, through a network endpoint group. Do not remove or change it once applied |
| `cloud.google.com/backend-config` | Service | `{"default": "hush-agw"}` | The BackendConfig, for every port of the Service |
| `kubernetes.io/ingress.class` | Ingress | `gce` | Selects GKE Ingress, an external Application Load Balancer. GKE takes the class from this annotation, and does not support `ingressClassName` with managed certificates, so `className` stays empty |
| `networking.gke.io/managed-certificates` | Ingress | `hush-agw` | The ManagedCertificate |
| `networking.gke.io/v1beta1.FrontendConfig` | Ingress | `hush-agw` | The FrontendConfig |

See the annotations in
[Configure Ingress for external Application Load Balancers](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/load-balance-ingress),
[Configure Ingress features](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/ingress-configuration)
and [Secure traffic for GKE Ingress](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/secure-traffic-management).

Optionally reserve a global static IP address, and name it in the Ingress
annotation `kubernetes.io/ingress.global-static-ip-name`, so that the address
survives a deleted Ingress and the DNS record stays valid:

```bash
gcloud compute addresses create hush-agw --global
```

### TLS and the certificate

- **Termination.** The load balancer's Google Front Ends terminate TLS on port
  443, and send the requests to the pods over unencrypted HTTP/1.1, on port
  3001. On port 80 they answer with the FrontendConfig's redirect.
- **TLS policy.** Without an SSL policy, the load balancer accepts TLS 1.0 and
  later. The FrontendConfig attaches `hush-agw-tls`, which requires TLS 1.2.
  To drop the FrontendConfig, first remove its `sslPolicy` and apply: GKE
  leaves the SSL policy on the load balancer when the FrontendConfig goes. See
  [SSL policies overview](https://docs.cloud.google.com/load-balancing/docs/ssl-policies-concepts).
- **Issuance.** The ManagedCertificate asks Google for a domain-validated
  certificate. Google provisions it once the hostname's A record in public DNS
  points at the Ingress's IP address, or a CNAME record points at a name that
  does, which can take up to 60 minutes after DNS has propagated. The load
  balancer may take up to 30 more minutes to serve it. It is ready when its
  status is `Active`.
- **Rotation.** Google renews the certificate on its own, as long as the DNS
  record still points at the load balancer and its forwarding rule listens on
  port 443. A ManagedCertificate cannot be updated: to change its domains,
  create a new one. Google does not replace a certificate revoked at the
  certificate authority: delete the ManagedCertificate and create a new one.
  See [Use Google-managed SSL certificates](https://docs.cloud.google.com/load-balancing/docs/ssl-certificates/google-managed-certs)
  and [Secure traffic for GKE Ingress](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/secure-traffic-management).

### After the install

The Ingress shows the load balancer's IP address. Point the hostname's A
record at it, then wait for the certificate:

```bash
kubectl get ingress hush-agw -n hush-security
kubectl describe managedcertificate hush-agw -n hush-security
```

## Installing the prerequisites

Install these only where the checks under an example show them missing.

### HTTP load balancing add-on

```bash
gcloud container clusters update CLUSTER_NAME --update-addons=HttpLoadBalancing=ENABLED
```

See [Configure Ingress for external Application Load Balancers](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/load-balance-ingress).

### SSL policy

Create it in the cluster's project. The `MODERN` profile with a minimum of TLS
1.2 refuses TLS 1.0 and 1.1:

```bash
gcloud compute ssl-policies create hush-agw-tls --profile MODERN --min-tls-version 1.2
```

See [Use SSL policies](https://docs.cloud.google.com/load-balancing/docs/use-ssl-policies).

### Gateway API

```bash
gcloud container clusters update CLUSTER_NAME --location=CLUSTER_LOCATION --gateway-api=standard
```

GKE then installs the Gateway API CRDs of the standard channel and its
GatewayClasses, which can take up to 45 minutes. See
[Deploy Gateways](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/deploying-gateways).

### Certificate Manager certificate

Create a DNS authorization for the hostname, add the CNAME record it lists to
the DNS zone and leave it there, then create the certificate and a certificate
map that serves it for the hostname:

```bash
gcloud certificate-manager dns-authorizations create hush-agw --domain="gw.example.com"
gcloud certificate-manager dns-authorizations describe hush-agw   # the CNAME record under dnsResourceRecord

gcloud certificate-manager certificates create hush-agw \
  --domains="gw.example.com" --dns-authorizations="hush-agw"
gcloud certificate-manager maps create hush-agw
gcloud certificate-manager maps entries create hush-agw \
  --map="hush-agw" --certificates="hush-agw" --hostname="gw.example.com"
```

See [Deploy a Google-managed certificate with DNS authorization](https://docs.cloud.google.com/certificate-manager/docs/deploy-google-managed-dns-auth).
