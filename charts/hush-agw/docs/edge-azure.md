# Exposing Hush AGW on Azure

Azure Application Gateway for Containers puts Hush AGW behind a frontend that
its ALB Controller programs from a Gateway or an Ingress. For what any edge
must do and the settings the examples use, see [Exposing Hush AGW](edge.md).

## Gateway API

Tested with ALB Controller 1.13.0 on AKS, with the HealthCheckPolicy and the
session affinity below as the chart's `azure-agc` preset renders them. The
preset sets the request timeout on the HTTPRoute instead, so the RoutePolicy
timeout below was not tested, nor was the DNS-01 issuance.

The ALB Controller programs a frontend of an Azure Application Gateway for
Containers (AGC) for a Gateway of the class `azure-alb-external`, and sends
the requests of the chart's HTTPRoute to the Hush AGW pods. In these examples
the ALB Controller also creates the AGC itself, from an
`ApplicationLoadBalancer` resource named `alb` in the namespace `alb-infra`. The chart creates the Gateway and the HTTPRoute. The settings of
the load balancer go into a HealthCheckPolicy and a RoutePolicy, which you
create, and cert-manager issues the certificate.

### Prerequisites

- An AKS cluster that uses Azure CNI or Azure CNI Overlay, with the OIDC
  issuer and workload identity enabled, in a region where AGC is available,
  with the variables of
  [Installing the prerequisites](#installing-the-prerequisites) set:
  `az aks show -g $RESOURCE_GROUP -n $AKS_NAME --query "{networkPlugin: networkProfile.networkPlugin, oidcIssuer: oidcIssuerProfile.enabled, workloadIdentity: securityProfile.workloadIdentity.enabled}"`.
  The first step under [ALB Controller](#alb-controller) turns the last two
  on.
- The ALB Controller, with its managed identity:
  `kubectl get pods -n azure-alb-system`, or
  `kubectl get pods -n kube-system | grep alb-controller` for the AKS add-on.
  See [ALB Controller](#alb-controller).
- The `ApplicationLoadBalancer` `alb` in the namespace `alb-infra`, on a
  subnet delegated to `Microsoft.ServiceNetworking/trafficControllers`:
  `kubectl get applicationloadbalancer alb -n alb-infra`. See
  [ApplicationLoadBalancer](#applicationloadbalancer).
- No network security group rule on that subnet that denies outbound traffic
  to the pods: it blocks the health probes too. See
  [Network Security Groups on the association subnet](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/application-gateway-for-containers-components#network-security-groups-on-the-association-subnet).
- cert-manager with a ClusterIssuer that solves the DNS-01 challenge in the
  hostname's Azure DNS zone: `kubectl get clusterissuer letsencrypt-dns`. See
  [cert-manager DNS-01 with Azure DNS](#cert-manager-dns-01-with-azure-dns).
  The chart's Gateway listens on port 443 only, while an HTTP-01 challenge
  needs a listener on port 80.
- The hostname's DNS zone, in Azure DNS for this ClusterIssuer. cert-manager
  supports other DNS providers too.

### Create the Certificate and the policies

Create them in the release's namespace before installing, after
`kubectl create namespace hush-security`:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: gw-example-com-tls
  namespace: hush-security
spec:
  secretName: gw-example-com-tls
  dnsNames:
    - gw.example.com
  issuerRef:
    name: letsencrypt-dns
    kind: ClusterIssuer
---
apiVersion: alb.networking.azure.io/v1
kind: HealthCheckPolicy
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  targetRef:
    group: ""
    kind: Service
    name: hush-agw
  default:
    port: 15021
    http:
      path: /healthz/ready
---
apiVersion: alb.networking.azure.io/v1
kind: RoutePolicy
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: hush-agw
  default:
    timeouts:
      routeTimeout: 1800s
    sessionAffinity:
      affinityType: managed-cookie
```

- The Certificate has cert-manager issue the certificate into the Secret
  `gw-example-com-tls`, which the Gateway's listener names.
- The HealthCheckPolicy probes port 15021, path `/healthz/ready`. A probe on a
  port other than the Service's runs in cleartext. Without the policy, AGC
  falls back to the readiness probe of the pod, which checks the same port and
  path. The policy states the probe explicitly. See
  [Custom health probe](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/custom-health-probe).
- The RoutePolicy names the chart's HTTPRoute, `hush-agw` for a release of
  that name. Its `targetRef.group` must be `gateway.networking.k8s.io`: the
  ALB Controller refuses the empty group of Microsoft's session affinity
  example.
- `routeTimeout` bounds a whole request, 60 seconds by default. Microsoft
  states that AGC "strictly enforces the request to complete in the defined
  time irrespective if data is actively streaming or the request is idle", so
  a stream that lasts longer is cut and the MCP client reconnects. AGC takes
  it since the chart's HTTPRoute sets no timeout of its own, which AGC would
  prefer. AGC also cuts a stream or a connection idle for 5 minutes, which
  cannot be changed.
- `managed-cookie` keeps a client on the Hush AGW pod that served it before,
  which answers it faster, through a cookie named `AGCAffinity` that lasts one
  day, for clients that send it back.

See [Server-sent events](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/server-sent-events)
for `routeTimeout`, the order of the timeouts in
[Application Gateway for Containers components](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/application-gateway-for-containers-components),
[Session affinity](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/session-affinity)
and the [API specification](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/api-specification-kubernetes).

### Values

```yaml
agw:
  hostname: gw.example.com
  httpRoute:
    enabled: true
    gateway:
      enabled: true
      className: azure-alb-external
      annotations:
        alb.networking.azure.io/alb-name: alb
        alb.networking.azure.io/alb-namespace: alb-infra
      tls:
        secretName: gw-example-com-tls
```

| Setting | Value | Purpose |
| :---- | :---- | :---- |
| `gateway.className` | `azure-alb-external` | A frontend with a public IP address. `azure-alb-internal` gives one with no public IP address, reachable only through private endpoints, which Microsoft offers in preview. See [Private ingress](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/private-ingress) |
| `alb.networking.azure.io/alb-name` | `alb` | The `ApplicationLoadBalancer` whose AGC serves the Gateway |
| `alb.networking.azure.io/alb-namespace` | `alb-infra` | Its namespace |
| `gateway.tls.secretName` | `gw-example-com-tls` | The Secret cert-manager writes the certificate into |

The ALB Controller names the frontend `fe-<random>`. An AGC created outside the
cluster is named by `alb.networking.azure.io/alb-id` and its frontend by the
Gateway's `spec.addresses`, which the chart sets only in its `azure-agc`
preset: use the preset, or a Gateway of your own. See
[SSL offloading with Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-ssl-offloading-gateway-api).

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

Create the HealthCheckPolicy and the RoutePolicy as above: they name the
Service and the HTTPRoute of Hush AGW, so they apply on any Gateway, and the
affinity cookie reaches the traffic to Hush AGW only. The certificate belongs
to that Gateway. Its listener must meet the
[requirements](edge.md#what-any-edge-must-do) and admit routes from the
`hush-security` namespace.

### TLS and the certificate

- **Termination.** The frontend terminates TLS on port 443 with the
  certificate from the Secret, and sends the requests to the pods over plain
  HTTP/1.1, on port 3001. It applies the default TLS policy, `2023-06`, which
  accepts TLS 1.2 and 1.3 only. A FrontendTLSPolicy can pick another
  predefined policy. See
  [TLS policy](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/tls-policy).
- **Issuance.** cert-manager proves the domain to Let's Encrypt with a TXT
  record it writes into the Azure DNS zone, so the hostname need not point at
  the frontend first, and nothing has to listen on port 80.
- **Rotation.** cert-manager renews the certificate 2/3 through its duration,
  on day 60 of the 90 days a Let's Encrypt certificate lasts by default, with
  the same DNS-01 challenge, and writes the new certificate into the same
  Secret. Microsoft states that cert-manager "automatically issue[s] and
  renew[s]" the certificates of AGC frontends, but does not describe how the
  ALB Controller picks up a changed Secret, and a renewal was not tested.
  After a renewal, compare the expiry of the served certificate with that of
  the Secret:

  ```bash
  kubectl get certificate gw-example-com-tls -n hush-security
  openssl s_client -connect gw.example.com:443 -servername gw.example.com </dev/null 2>/dev/null \
    | openssl x509 -noout -enddate
  ```

  See [Certificate resource](https://cert-manager.io/docs/usage/certificate/)
  for the renewal time.

### After the install

The Gateway shows the frontend's FQDN as its address once it is `Programmed`.
Point the hostname at it with a CNAME record:

```bash
kubectl get gateway hush-agw -n hush-security
kubectl get certificate -n hush-security
```

## Ingress

Tested with ALB Controller 1.13.0 on AKS.

The ALB Controller programs an AGC for the Ingress: a frontend that terminates
TLS for the hostname and sends the requests to the Hush AGW pods. In this
example the ALB Controller also creates the AGC itself, from an
`ApplicationLoadBalancer` resource named `alb` in the namespace `alb-infra`.
cert-manager issues the certificate from Let's Encrypt.

### Prerequisites

- An AKS cluster that uses Azure CNI or Azure CNI Overlay, with the OIDC
  issuer and workload identity enabled, in a region where AGC is available,
  with the variables of
  [Installing the prerequisites](#installing-the-prerequisites) set:
  `az aks show -g $RESOURCE_GROUP -n $AKS_NAME --query "{networkPlugin: networkProfile.networkPlugin, oidcIssuer: oidcIssuerProfile.enabled, workloadIdentity: securityProfile.workloadIdentity.enabled}"`.
  The first step under [ALB Controller](#alb-controller) turns the last two
  on.
- The ALB Controller, with its managed identity:
  `kubectl get pods -n azure-alb-system`, or
  `kubectl get pods -n kube-system | grep alb-controller` for the AKS add-on.
  See [ALB Controller](#alb-controller).
- The `ApplicationLoadBalancer` `alb` in the namespace `alb-infra`, on a
  subnet delegated to `Microsoft.ServiceNetworking/trafficControllers`:
  `kubectl get applicationloadbalancer alb -n alb-infra`. See
  [ApplicationLoadBalancer](#applicationloadbalancer).
- No network security group rule on that subnet that denies outbound traffic
  to the pods: it blocks the health probes too. See
  [Network Security Groups on the association subnet](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/application-gateway-for-containers-components#network-security-groups-on-the-association-subnet).
- cert-manager: `kubectl get pods -n cert-manager`. See
  [cert-manager](#cert-manager).
- A DNS zone where you can create the hostname's record.

### Create the ClusterIssuer

The ClusterIssuer solves the HTTP-01 challenge of Let's Encrypt with a
temporary Ingress of class `azure-alb-external`. Its annotations put that
Ingress on the same AGC and the same frontend as the Ingress of Hush AGW, where
the hostname's DNS record points. Without `alb-frontend`, the ALB Controller
gives the challenge Ingress a frontend of its own, which Let's Encrypt never
reaches, and the certificate is never issued:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: platform@example.com
    privateKeySecretRef:
      name: letsencrypt-account-key
    solvers:
      - http01:
          ingress:
            ingressClassName: azure-alb-external
            ingressTemplate:
              metadata:
                annotations:
                  alb.networking.azure.io/alb-name: alb
                  alb.networking.azure.io/alb-namespace: alb-infra
                  alb.networking.azure.io/alb-frontend: hush-agw
```

Since the solver names the frontend of Hush AGW, other applications need an
issuer of their own.

See [HTTP01](https://cert-manager.io/docs/configuration/acme/http01/) and
[Cert-manager and Let's Encrypt with Application Gateway for Containers - Ingress API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-cert-manager-lets-encrypt-ingress-api).

### Create the HealthCheckPolicy and the IngressExtension

Create both in the release's namespace before installing, after
`kubectl create namespace hush-security`. They name the Service, `hush-agw`
for a release of that name:

```yaml
apiVersion: alb.networking.azure.io/v1
kind: HealthCheckPolicy
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  targetRef:
    group: ""
    kind: Service
    name: hush-agw
  default:
    port: 15021
    http:
      path: /healthz/ready
---
apiVersion: alb.networking.azure.io/v1
kind: IngressExtension
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  backendSettings:
    - service: hush-agw
      timeouts:
        requestTimeout: 1800s
      sessionAffinity:
        affinityType: managed-cookie
```

- The HealthCheckPolicy probes port 15021, path `/healthz/ready`. A probe on a
  port other than the Service's runs in cleartext. Without the policy, AGC
  falls back to the readiness probe of the pod, which checks the same port and
  path. The policy states the probe explicitly.
- `requestTimeout` bounds a whole request, 60 seconds by default. Microsoft
  states that it "strictly enforces the request to complete in the defined
  time irrespective if data is actively streaming or the request is idle", so
  a stream that lasts longer is cut and the MCP client reconnects. AGC also
  cuts a stream or a connection idle for 5 minutes, which cannot be changed.
- `managed-cookie` keeps a client on the Hush AGW pod that served it before,
  which answers it faster, through a cookie named `AGCAffinity` that lasts one
  day, for clients that send it back.

See [Custom health probe](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/custom-health-probe),
[Session affinity](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/session-affinity),
the request timeouts in
[Application Gateway for Containers components](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/application-gateway-for-containers-components)
and the [API specification](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/api-specification-kubernetes).

### Values

```yaml
agw:
  hostname: gw.example.com
  ingress:
    enabled: true
    className: azure-alb-external
    annotations:
      alb.networking.azure.io/alb-name: alb
      alb.networking.azure.io/alb-namespace: alb-infra
      alb.networking.azure.io/alb-frontend: hush-agw
      alb.networking.azure.io/alb-ingress-extension: hush-agw
      cert-manager.io/cluster-issuer: letsencrypt
    tls:
      secretName: gw-example-com-tls
```

| Setting | Value | Purpose |
| :---- | :---- | :---- |
| `className` | `azure-alb-external` | The ALB Controller serves Ingresses of this class only. Any other class leaves Hush AGW unserved |
| `alb.networking.azure.io/alb-name` | `alb` | The `ApplicationLoadBalancer` whose AGC serves the Ingress |
| `alb.networking.azure.io/alb-namespace` | `alb-infra` | Its namespace |
| `alb.networking.azure.io/alb-frontend` | `hush-agw` | The name of the frontend, which the ClusterIssuer's solver names too. Without it the ALB Controller names the frontend `fe-<random>` |
| `alb.networking.azure.io/alb-ingress-extension` | `hush-agw` | The IngressExtension, in the Ingress's namespace |
| `cert-manager.io/cluster-issuer` | `letsencrypt` | The ClusterIssuer cert-manager issues the certificate with |
| `tls.secretName` | `gw-example-com-tls` | The Secret cert-manager writes the certificate into, and AGC serves it from |

For an AGC created outside the cluster, replace `alb-name` and
`alb-namespace` with `alb.networking.azure.io/alb-id`, its resource ID, and
name its existing frontend in `alb-frontend`, in the Ingress and in the
solver alike.

Microsoft documents these annotations through examples rather than a
reference. See
[SSL offloading with Ingress API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-ssl-offloading-ingress-api)
for `alb-name`, `alb-namespace`, `alb-id` and `alb-frontend`, and
[End-to-end TLS with Ingress API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-end-to-end-tls-ingress-api)
for `alb-ingress-extension`. For the cert-manager annotations, see
[Annotated Ingress resource](https://cert-manager.io/docs/usage/ingress/).

### TLS and the certificate

- **Termination.** The AGC frontend terminates TLS on port 443 with the
  certificate from the Secret `gw-example-com-tls`, and sends the requests to
  the pods over plain HTTP/1.1, on port 3001. AGC takes certificates from
  Kubernetes Secrets only, not from Azure Key Vault. It applies its default
  TLS policy, `2023-06`, to every Ingress, which accepts TLS 1.2 and 1.3 only
  and cannot be changed for an Ingress. See
  [TLS policy](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/tls-policy).
- **Issuance.** cert-manager sees the `cert-manager.io/cluster-issuer`
  annotation and creates a Certificate for the hosts in `spec.tls`, named
  after the Secret. For the HTTP-01 challenge it creates the temporary solver
  Ingress and pod, and Let's Encrypt fetches the challenge from the hostname
  over plain HTTP on port 80. So the hostname's DNS record must point at the
  frontend first: create a CNAME record to the frontend's FQDN as soon as the
  Ingress shows it. The ALB Controller programs the Ingress of Hush AGW only
  once the Secret exists, so HTTPS starts to work after the issuance.
- **Rotation.** cert-manager renews the certificate 2/3 through its duration,
  on day 60 of the 90 days a Let's Encrypt certificate lasts by default, with
  the same HTTP-01 challenge, and writes the new certificate into the same
  Secret. Renewal needs what issuance needed: the DNS record, port 80, and the
  solver naming the frontend. How the ALB Controller picks up the changed
  Secret is not documented, as described for the
  [Gateway API](#tls-and-the-certificate), which shows how to check it.

### After the install

The Ingress shows the frontend's FQDN as its address. Point the hostname at it
with a CNAME record, then wait for the certificate:

```bash
kubectl get ingress hush-agw -n hush-security
kubectl get certificate -n hush-security
```

## Installing the prerequisites

Install these only where the checks under an example show them missing. The
commands, and the checks, take the cluster's resource group and name from
these variables:

```bash
RESOURCE_GROUP=<the cluster's resource group>
AKS_NAME=<the cluster's name>
```

### ALB Controller

Register the resource providers, add the `alb` extension of the Azure CLI,
and turn on the OIDC issuer and workload identity of the cluster:

```bash
az provider register --namespace Microsoft.ContainerService
az provider register --namespace Microsoft.Network
az provider register --namespace Microsoft.NetworkFunction
az provider register --namespace Microsoft.ServiceNetworking
az extension add --name alb

az aks update -g $RESOURCE_GROUP -n $AKS_NAME --enable-oidc-issuer --enable-workload-identity
```

Create the controller's managed identity, give it the Reader role on the
cluster's node resource group, and federate it with the controller's service
account:

```bash
IDENTITY_RESOURCE_NAME='azure-alb-identity'
CONTROLLER_NAMESPACE='azure-alb-system'

mcResourceGroup=$(az aks show --resource-group $RESOURCE_GROUP --name $AKS_NAME --query "nodeResourceGroup" -o tsv)
mcResourceGroupId=$(az group show --name $mcResourceGroup --query id -otsv)

az identity create --resource-group $RESOURCE_GROUP --name $IDENTITY_RESOURCE_NAME
principalId="$(az identity show -g $RESOURCE_GROUP -n $IDENTITY_RESOURCE_NAME --query principalId -otsv)"
sleep 60   # let the identity replicate in Microsoft Entra ID

az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal \
  --scope $mcResourceGroupId --role "acdd72a7-3385-48ef-bd42-f606fba81ae7"   # Reader

AKS_OIDC_ISSUER="$(az aks show -n "$AKS_NAME" -g "$RESOURCE_GROUP" --query "oidcIssuerProfile.issuerUrl" -o tsv)"
az identity federated-credential create --name $IDENTITY_RESOURCE_NAME \
  --identity-name "$IDENTITY_RESOURCE_NAME" \
  --resource-group $RESOURCE_GROUP \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:$CONTROLLER_NAMESPACE:alb-controller-sa"
```

Install the controller:

```bash
helm install alb-controller oci://mcr.microsoft.com/application-lb/charts/alb-controller \
  --namespace azure-alb-system --create-namespace \
  --version 1.13.0 \
  --set albController.namespace=$CONTROLLER_NAMESPACE \
  --set albController.podIdentity.clientID=$(az identity show -g $RESOURCE_GROUP -n $IDENTITY_RESOURCE_NAME --query clientId -o tsv)

kubectl get pods -n azure-alb-system
```

See [Quickstart: Deploy Application Gateway for Containers ALB Controller](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-helm)
for the current version and the full steps. The ALB Controller is also
available as an AKS add-on, in preview, which creates the identity and a
delegated subnet itself but cannot be customized. See
[the add-on quickstart](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-addon).

### ApplicationLoadBalancer

Create the delegated subnet in the cluster's virtual network, or in one
connected to it, and give the controller's identity the roles it needs to
create the AGC and to join the subnet. These commands are for the Helm install
above. The AKS add-on names its identity
`applicationloadbalancer-<cluster-name>`, which already has the Configuration
Manager role, and on an AKS-managed virtual network creates the delegated
subnet `aks-appgateway` itself: with the add-on, follow the quickstart linked
below instead.

```bash
IDENTITY_RESOURCE_NAME='azure-alb-identity'
principalId="$(az identity show -g $RESOURCE_GROUP -n $IDENTITY_RESOURCE_NAME --query principalId -otsv)"
mcResourceGroupId=$(az group show --name "$(az aks show -g $RESOURCE_GROUP -n $AKS_NAME --query nodeResourceGroup -o tsv)" --query id -otsv)

VNET_RESOURCE_GROUP=<the virtual network's resource group>
VNET_NAME=<the virtual network's name>
SUBNET_ADDRESS_PREFIX=<a free range of at least /24>

az network vnet subnet create \
  --resource-group $VNET_RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --name subnet-alb \
  --address-prefixes $SUBNET_ADDRESS_PREFIX \
  --delegations 'Microsoft.ServiceNetworking/trafficControllers'
ALB_SUBNET_ID=$(az network vnet subnet show --name subnet-alb --resource-group $VNET_RESOURCE_GROUP --vnet-name $VNET_NAME --query '[id]' --output tsv)

az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal \
  --scope $mcResourceGroupId --role "fbc52c3f-28ad-4303-a892-8a056630b8f1"   # AppGw for Containers Configuration Manager
az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal \
  --scope $ALB_SUBNET_ID --role "4d97b98b-1d4f-4787-a291-c67834d212e7"       # Network Contributor
```

Then create the `ApplicationLoadBalancer`. The AGC takes 5 to 6 minutes to
be created, and is ready when the resource reports `Deployment` as `Ready`:

```bash
kubectl create namespace alb-infra
kubectl apply -f - <<EOF
apiVersion: alb.networking.azure.io/v1
kind: ApplicationLoadBalancer
metadata:
  name: alb
  namespace: alb-infra
spec:
  associations:
    - $ALB_SUBNET_ID
EOF
kubectl get applicationloadbalancer alb -n alb-infra -o yaml -w
```

See [Quickstart: Create Application Gateway for Containers managed by ALB Controller](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-managed-by-alb-controller).

### cert-manager

```bash
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version v1.21.3 \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true
```

See [Installing cert-manager with Helm](https://cert-manager.io/docs/installation/helm/)
for the current version.

### cert-manager DNS-01 with Azure DNS

cert-manager writes the challenge's TXT record into the Azure DNS zone with a
managed identity, through workload identity. Install cert-manager, as under
[cert-manager](#cert-manager), with this label on its pod, in a values file
added with `-f`:

```yaml
podLabels:
  azure.workload.identity/use: "true"
```

Where cert-manager already runs, add the label to it with the version it runs,
which `helm list -n cert-manager` shows, and its other values kept:

```bash
helm upgrade cert-manager oci://quay.io/jetstack/charts/cert-manager -n cert-manager \
  --version <the installed version> --reuse-values -f <the values file>
```

Create the identity, let it edit the DNS zone, and federate it with
cert-manager's service account:

```bash
DNS_ZONE=example.com
DNS_ZONE_RESOURCE_GROUP=<the DNS zone's resource group>

az identity create --resource-group $RESOURCE_GROUP --name cert-manager
IDENTITY_CLIENT_ID=$(az identity show -g $RESOURCE_GROUP -n cert-manager --query clientId -o tsv)

az role assignment create --role "DNS Zone Contributor" --assignee $IDENTITY_CLIENT_ID \
  --scope $(az network dns zone show --name $DNS_ZONE --resource-group $DNS_ZONE_RESOURCE_GROUP -o tsv --query id)

AKS_OIDC_ISSUER="$(az aks show -n "$AKS_NAME" -g "$RESOURCE_GROUP" --query "oidcIssuerProfile.issuerUrl" -o tsv)"
az identity federated-credential create --name cert-manager \
  --identity-name cert-manager \
  --resource-group $RESOURCE_GROUP \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:cert-manager:cert-manager"
```

Then create the ClusterIssuer:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: platform@example.com
    privateKeySecretRef:
      name: letsencrypt-dns-account-key
    solvers:
      - dns01:
          azureDNS:
            hostedZoneName: example.com
            resourceGroupName: <the DNS zone's resource group>
            subscriptionID: <the DNS zone's subscription ID>
            environment: AzurePublicCloud
            managedIdentity:
              clientID: <IDENTITY_CLIENT_ID>
```

See [AzureDNS](https://cert-manager.io/docs/configuration/acme/dns01/azuredns/).
