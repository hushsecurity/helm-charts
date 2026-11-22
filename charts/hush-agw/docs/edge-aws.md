# Exposing Hush AGW on AWS

The AWS Load Balancer Controller puts Hush AGW behind an Application Load
Balancer, through the Gateway API or an Ingress, or behind a Network Load
Balancer, through the Service.
For what any edge must do and the settings the examples use, see
[Exposing Hush AGW](edge.md).

## Gateway API

Tested with AWS Load Balancer Controller v3.6.3 on EKS 1.35, with the
LoadBalancerConfiguration and the TargetGroupConfiguration below as the
chart's `aws-alb` preset renders them. Attaching the LoadBalancerConfiguration
to the GatewayClass, as the chart's own Gateway needs here, was not tested.

The AWS Load Balancer Controller creates an Application Load Balancer (ALB) for
a Gateway, with an HTTPS listener on port 443, and sends the requests of the
chart's HTTPRoute to the Hush AGW pods. The chart creates the Gateway and the
HTTPRoute. The settings of the load balancer go into a
LoadBalancerConfiguration and those of its targets into a
TargetGroupConfiguration, which you create.

### Prerequisites

- An EKS cluster whose pods get their IP addresses from the VPC, as with the
  Amazon VPC CNI plugin, since the ALB sends requests straight to the pod IPs:
  `kubectl get daemonset aws-node -n kube-system`.
- The AWS Load Balancer Controller, v3.5.0 or later, the first to serve the
  `gateway.k8s.aws/v1` objects below:
  `kubectl get deployment aws-load-balancer-controller -n kube-system -o jsonpath='{.spec.template.spec.containers[0].image}'`.
  See [AWS Load Balancer Controller](#aws-load-balancer-controller).
- Subnets tagged for the controller in at least two Availability Zones:
  public subnets with `kubernetes.io/role/elb` for an internet-facing ALB,
  private subnets with `kubernetes.io/role/internal-elb` for an internal one.
  See [Subnet tags](#subnet-tags).
- An ACM certificate for the hostname, issued in the cluster's Region and
  validated by DNS:
  `aws acm list-certificates --region <region> --certificate-statuses ISSUED`.
  See [ACM certificate](#acm-certificate).
- The Gateway API CRDs, v1.6.0 or later, and the controller's own Gateway
  CRDs at version `v1`, installed before the controller started: it looks for
  them only when it starts. The first command prints the Gateway API version,
  the second must list `v1`:
  `kubectl get crd gateways.gateway.networking.k8s.io -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/bundle-version}'`,
  `kubectl get crd loadbalancerconfigurations.gateway.k8s.aws -o jsonpath='{.spec.versions[*].name}'`.
  See [Gateway API CRDs](#gateway-api-crds).
- A DNS zone where you can create the hostname's record.

### Create the LoadBalancerConfiguration and the GatewayClass

Create the namespace first, `kubectl create namespace hush-security`, since
the install command creates it only when it runs:

```yaml
apiVersion: gateway.k8s.aws/v1
kind: LoadBalancerConfiguration
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  scheme: internet-facing
  listenerConfigurations:
    - protocolPort: HTTPS:443
      sslPolicy: ELBSecurityPolicy-TLS13-1-2-2021-06
  loadBalancerAttributes:
    - key: idle_timeout.timeout_seconds
      value: "600"
---
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: hush-agw-alb
spec:
  controllerName: gateway.k8s.aws/alb
  parametersRef:
    group: gateway.k8s.aws
    kind: LoadBalancerConfiguration
    name: hush-agw
    namespace: hush-security
```

- The chart's Gateway names no LoadBalancerConfiguration, so the GatewayClass
  carries it, as the default of every Gateway of the class. Give Hush AGW a
  GatewayClass of its own.
- `scheme: internet-facing` gives the ALB public IP addresses. The
  controller's default is `internal`, which keeps the ALB inside your network,
  as described under [Internal ALB](#internal-alb).
- `sslPolicy` accepts TLS 1.2 and 1.3 only. The controller's default,
  `ELBSecurityPolicy-2016-08`, also accepts TLS 1.0 and 1.1.
- Without a `defaultCertificate`, the controller finds the ACM certificate by
  the listener's hostname. To name it, add `defaultCertificate: <ARN>` to the
  listener configuration.
- The controller does not support the timeouts of an HTTPRoute, so the idle
  timeout of the ALB, 600 seconds rather than AWS's 60, is what keeps long MCP
  sessions open.

See [Customizing the Gateway](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/gateway/customization/)
and [LoadBalancerConfiguration](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/gateway/loadbalancerconfig/).

### Create the TargetGroupConfiguration

```yaml
apiVersion: gateway.k8s.aws/v1
kind: TargetGroupConfiguration
metadata:
  name: hush-agw
  namespace: hush-security
spec:
  targetReference:
    name: hush-agw
  defaultConfiguration:
    targetType: ip
    healthCheckConfig:
      healthCheckProtocol: HTTP
      healthCheckPort: "15021"
      healthCheckPath: /healthz/ready
    targetGroupAttributes:
      - key: stickiness.enabled
        value: "true"
      - key: stickiness.lb_cookie.duration_seconds
        value: "86400"
      - key: load_balancing.cross_zone.enabled
        value: "true"
```

- `targetReference` names the Service, `hush-agw` for a release of that
  name.
- `targetType: ip` registers the pods as targets. The controller's default,
  `instance`, registers the nodes on the Service's node port, which the
  `ClusterIP` Service of Hush AGW does not have. Without this object the
  controller cannot send traffic to Hush AGW, and applies no change to the
  Gateway at all, from any route, while the HTTPRoute is attached.
- The health check probes port 15021, path `/healthz/ready`. The sticky
  sessions keep a client on the Hush AGW pod that served it before, which
  answers it faster, through a cookie the ALB sets for one day, for clients
  that send it back. Cross-zone load balancing, which an ALB has on by
  default, lets its node in each zone send requests to the pods in every
  zone. The attribute states it on the target group, where it could be turned
  off. See
  [Application Load Balancers](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html).

See [TargetGroupConfiguration](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/gateway/targetgroupconfig/).

### Values

```yaml
agw:
  hostname: gw.example.com
  httpRoute:
    enabled: true
    gateway:
      enabled: true
      className: hush-agw-alb
```

The chart creates the Gateway `hush-agw`, of the GatewayClass above, with one
HTTPS listener on port 443 for the hostname, and the HTTPRoute that sends every
path of the hostname to Hush AGW. Leave `gateway.tls.secretName` empty: the
controller takes the certificate from ACM only, not from a Secret.

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

The TargetGroupConfiguration is still needed, for the reason above. The
settings of the load balancer belong to that Gateway, which names a
LoadBalancerConfiguration of its own namespace in
`spec.infrastructure.parametersRef`. Its listener must meet the
[requirements](edge.md#what-any-edge-must-do) and admit routes from the
`hush-security` namespace.

### TLS and the certificate

- **Termination.** The HTTPS listener terminates TLS on port 443 with the ACM
  certificate, and sends the requests to the pod IPs over plain HTTP, on port
  3001. With the `sslPolicy` above it accepts TLS 1.2 and 1.3 only. See
  [Security policies for your Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/describe-ssl-policies.html).
- **Certificate.** The controller takes certificates from ACM only: it does
  not support the `certificateRefs` of a Gateway listener. It finds the
  certificate by the listener's hostname, or takes the one the
  LoadBalancerConfiguration names. See
  [Certificate Discovery for secure listeners](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/gateway/gateway/).
- **Issuance.** ACM issues the certificate once the CNAME record of its DNS
  validation resolves. Nothing in the cluster takes part.
- **Rotation.** ACM renews a DNS-validated certificate on its own, starting
  45 days before it expires, as long as an AWS service such as the ALB uses
  it and the validation CNAME record is still in public DNS. The renewed
  certificate keeps its ARN, so nothing in the cluster changes, and the ALB
  serves it to new requests at once. If ACM cannot validate the domain, it
  sends AWS Health and EventBridge events from 30 days before the expiry. ACM
  does not renew an imported certificate: import the new one under the same
  ARN yourself. See
  [Managed certificate renewal](https://docs.aws.amazon.com/acm/latest/userguide/managed-renewal.html),
  [Renew domains validated by DNS](https://docs.aws.amazon.com/acm/latest/userguide/dns-renewal-validation.html)
  and [SSL certificates for your Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/https-listener-certificates.html).

### After the install

The Gateway shows the ALB's DNS name as its address once it is `Programmed`.
Point the hostname at it with a CNAME record, or with a Route 53 alias record:

```bash
kubectl get gateway hush-agw -n hush-security
```

## Ingress

Tested with AWS Load Balancer Controller v3.6.3 on EKS 1.35, internet-facing
and internal.

The AWS Load Balancer Controller creates an Application Load Balancer (ALB)
for the Ingress, with an HTTPS listener on port 443 and the Hush AGW pods as
its targets.

### Prerequisites

- An EKS cluster whose pods get their IP addresses from the VPC, as with the
  Amazon VPC CNI plugin, since the ALB sends requests straight to the pod IPs:
  `kubectl get daemonset aws-node -n kube-system`.
- The AWS Load Balancer Controller:
  `kubectl get deployment aws-load-balancer-controller -n kube-system`. See
  [AWS Load Balancer Controller](#aws-load-balancer-controller).
- Subnets tagged for the controller in at least two Availability Zones:
  public subnets with `kubernetes.io/role/elb` for an internet-facing ALB,
  private subnets with `kubernetes.io/role/internal-elb` for an internal one.
  See [Subnet tags](#subnet-tags).
- An ACM certificate for the hostname, issued in the cluster's Region and
  validated by DNS:
  `aws acm list-certificates --region <region> --certificate-statuses ISSUED`.
  See [ACM certificate](#acm-certificate).
- A DNS zone where you can create the hostname's record.

### Values

```yaml
agw:
  hostname: gw.example.com
  ingress:
    enabled: true
    className: alb
    annotations:
      alb.ingress.kubernetes.io/scheme: internet-facing
      alb.ingress.kubernetes.io/target-type: ip
      alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
      alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000
      alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
      alb.ingress.kubernetes.io/healthcheck-port: "15021"
      alb.ingress.kubernetes.io/healthcheck-path: /healthz/ready
      alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=600
      alb.ingress.kubernetes.io/target-group-attributes: stickiness.enabled=true,stickiness.lb_cookie.duration_seconds=86400
```

| Setting | Value | Controller default | Purpose |
| :---- | :---- | :---- | :---- |
| `className` | `alb` | - | The IngressClass of the AWS Load Balancer Controller |
| [`scheme`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#scheme) | `internet-facing` | `internal` | Public IP addresses. Changing the scheme later replaces the ALB, and its address with it |
| [`target-type`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#target-type) | `ip` | `instance` | Sends requests straight to the pod IPs. Sticky sessions need it |
| [`listen-ports`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#listen-ports) | `[{"HTTPS": 443}]` | HTTPS 443 with a certificate, HTTP 80 without | One HTTPS listener. There is no listener on port 80 |
| [`certificate-arn`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#certificate-arn) | the certificate's ARN | - | The ACM certificate of the listener. Without it the controller looks up an ACM certificate for the hostname, see [Certificate discovery](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/cert_discovery/) |
| [`ssl-policy`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#ssl-policy) | `ELBSecurityPolicy-TLS13-1-2-2021-06` | `ELBSecurityPolicy-2016-08` | TLS 1.2 and 1.3 only. The default also accepts TLS 1.0 and 1.1 |
| [`healthcheck-port`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#healthcheck-port) | `15021` | the traffic port | The readiness port of Hush AGW |
| [`healthcheck-path`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#healthcheck-path) | `/healthz/ready` | `/` | Its readiness path |
| [`load-balancer-attributes`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#load-balancer-attributes) | `idle_timeout.timeout_seconds=600` | AWS's 60 seconds | Keeps an idle connection open for 10 minutes. List every attribute you set here, such as access logs, in this one annotation |
| [`target-group-attributes`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/#target-group-attributes) | `stickiness.enabled=true,stickiness.lb_cookie.duration_seconds=86400` | off | Keeps a client on the Hush AGW pod that served it before, which answers it faster, through a cookie the ALB sets for one day, for clients that send it back |

The annotations are named `alb.ingress.kubernetes.io/<setting>`. See
[Ingress annotations](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/),
and the attributes in
[Application Load Balancer attributes](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html)
and [Target group attributes](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-target-groups.html).

### TLS and the certificate

- **Termination.** The HTTPS listener terminates TLS on port 443 with the ACM
  certificate, and sends the requests to the pod IPs over plain HTTP, on port
  3001. With `ELBSecurityPolicy-TLS13-1-2-2021-06` it accepts TLS 1.2 and 1.3
  only. See
  [Security policies for your Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/describe-ssl-policies.html).
- **Issuance and rotation.** As for the
  [Gateway API](#tls-and-the-certificate): ACM issues the certificate after
  DNS validation and renews it on its own under the same ARN, so the
  annotation stays as it is.

### Internal ALB

To keep the ALB inside your network, set
`alb.ingress.kubernetes.io/scheme: internal` in the values above. Nothing else
changes. The ALB then gets private IP addresses only, and is reachable from
the VPC and the networks connected to it, such as a VPN, a peered VPC or
Direct Connect. It needs private subnets tagged
`kubernetes.io/role/internal-elb` in at least two Availability Zones, and a
DNS record clients resolve, for example in a Route 53 private hosted zone.

The Hush backend never connects to Hush AGW, so an internal ALB works as long
as the AI clients and the browsers of the users and admins who connect
applications reach it. The certificate is the same public ACM certificate: its
validation CNAME record must stay in public DNS for the renewals, even when
the hostname itself resolves only in a private zone.

### After the install

The Ingress shows the ALB's DNS name as its address. Point the hostname at it
with a CNAME record, or with a Route 53 alias record:

```bash
kubectl get ingress hush-agw -n hush-security
```

## Network Load Balancer

Tested with AWS Load Balancer Controller v3.6.3 on EKS 1.35, with and without
`loadBalancerClass`.

The AWS Load Balancer Controller creates a Network Load Balancer (NLB) for the
`hush-agw` Service itself, of type `LoadBalancer`, with a TLS listener on
port 443 and the Hush AGW pods as its targets. There is no Ingress.

### Prerequisites

- The cluster, the AWS Load Balancer Controller, the ACM certificate and the
  DNS zone, as for the [Ingress](#ingress).
- Subnets tagged for the controller: public subnets with
  `kubernetes.io/role/elb` for an internet-facing NLB, private subnets with
  `kubernetes.io/role/internal-elb` for an internal one. See
  [Subnet tags](#subnet-tags).
- Or, instead of the controller, EKS Auto Mode, which creates the NLB itself.
  It needs the subnet tags too. See the Auto Mode notes below.

### Values

```yaml
agw:
  hostname: gw.example.com
  service:
    type: LoadBalancer
    annotations:
      service.beta.kubernetes.io/aws-load-balancer-type: external
      service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
      service.beta.kubernetes.io/aws-load-balancer-scheme: internet-facing
      service.beta.kubernetes.io/aws-load-balancer-ssl-cert: arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000
      service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"
      service.beta.kubernetes.io/aws-load-balancer-ssl-negotiation-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
      service.beta.kubernetes.io/aws-load-balancer-healthcheck-protocol: http
      service.beta.kubernetes.io/aws-load-balancer-healthcheck-port: "15021"
      service.beta.kubernetes.io/aws-load-balancer-healthcheck-path: /healthz/ready
      service.beta.kubernetes.io/aws-load-balancer-attributes: load_balancing.cross_zone.enabled=true
    # loadBalancerClass: service.k8s.aws/nlb
```

| Setting | Value | Controller default | Purpose |
| :---- | :---- | :---- | :---- |
| `type` | `LoadBalancer` | - | The Service listens on port 443 and gets a load balancer |
| [`aws-load-balancer-type`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#lb-type) | `external` | - | Hands the Service to the AWS Load Balancer Controller rather than to the legacy in-tree controller. Do not add or change it on an existing Service |
| [`aws-load-balancer-nlb-target-type`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#nlb-target-type) | `ip` | `instance` with a `loadBalancerClass` | Sends connections straight to the pod IPs |
| [`aws-load-balancer-scheme`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#lb-scheme) | `internet-facing` | `internal` | Public IP addresses |
| [`aws-load-balancer-ssl-cert`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#ssl-cert) | the certificate's ARN | - | The ACM certificate of the TLS listener. The NLB has no certificate discovery |
| [`aws-load-balancer-ssl-ports`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#ssl-ports) | `"443"` | every Service port | A TLS listener on port 443 |
| [`aws-load-balancer-ssl-negotiation-policy`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#ssl-negotiation-policy) | `ELBSecurityPolicy-TLS13-1-2-2021-06` | `ELBSecurityPolicy-2016-08` | TLS 1.2 and 1.3 only |
| [`aws-load-balancer-healthcheck-protocol`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#healthcheck-protocol) | `http` | `tcp` | An HTTP health check, so that the path counts |
| [`aws-load-balancer-healthcheck-port`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#healthcheck-port) | `"15021"` | the traffic port | The readiness port of Hush AGW |
| [`aws-load-balancer-healthcheck-path`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#healthcheck-path) | `/healthz/ready` | `/` | Its readiness path |
| [`aws-load-balancer-attributes`](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/#load-balancer-attributes) | `load_balancing.cross_zone.enabled=true` | AWS's `false` | The NLB's node in each zone reaches the Hush AGW pods in every zone. Without it, a node in a zone without a pod has nowhere to send its connections |

The annotations are named `service.beta.kubernetes.io/<setting>`. See
[Service annotations](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/),
[Network Load Balancer](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/nlb/)
and the attributes in
[Network Load Balancer attributes](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/network-load-balancers.html).

`loadBalancerClass` picks the implementation that handles the Service, and
cannot be changed once set:

- The controller's webhook sets `service.k8s.aws/nlb` on a new `LoadBalancer`
  Service by default, so the class can stay empty where the controller is the
  only implementation.
- EKS Auto Mode takes every `LoadBalancer` Service without a class, since its
  `eks.amazonaws.com/nlb` is the cluster default. On an Auto Mode cluster that
  runs the controller too, set `agw.service.loadBalancerClass:
  service.k8s.aws/nlb` for the controller to handle the Service.
- With Auto Mode handling the NLB, leave out
  `aws-load-balancer-ssl-negotiation-policy`, which is not among the
  annotations Auto Mode supports. See
  [Use Service annotations to configure Network Load Balancers](https://docs.aws.amazon.com/eks/latest/userguide/auto-configure-nlb.html).

Kubernetes also gives a `LoadBalancer` Service a node port, which the NLB does
not use with `ip` targets. The node port opens the plain HTTP port of Hush AGW
on every node, to whatever reaches the nodes. The values have no setting that
turns it off: only the chart's `aws-nlb` preset does. Where the nodes are
reachable from outside the cluster, use the preset.

### TLS and the certificate

- **Termination.** The TLS listener terminates TLS on port 443 with the ACM
  certificate, and forwards the connections to the pod IPs over TCP, on port
  3001, so Hush AGW receives plain HTTP. With
  `ELBSecurityPolicy-TLS13-1-2-2021-06` it accepts TLS 1.2 and 1.3 only. See
  [Security policies for your Network Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/describe-ssl-policies.html).
- **Limits.** A TLS listener closes a connection idle for 350 seconds, and
  this cannot be changed. It also does not support sticky sessions, so it
  cannot keep a client on one Hush AGW pod. Where either matters, use the
  ALB. See [Update the idle timeout](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/update-idle-timeout.html)
  and [Sticky sessions](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/edit-target-group-attributes.html).
- **Issuance and rotation.** As for the
  [Gateway API](#tls-and-the-certificate): ACM issues the certificate after
  DNS validation and renews it on its own while the NLB uses it and the CNAME
  record stays, under the same ARN, and the NLB serves the renewed certificate
  to new connections. See
  [Server certificates for your Network Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/tls-listener-certificates.html).

### After the install

The Service shows the NLB's DNS name as its external address. Point the
hostname at it with a CNAME record, or with a Route 53 alias record:

```bash
kubectl get service hush-agw -n hush-security
```

## Installing the prerequisites

Install these only where the checks under an example show them missing.

### AWS Load Balancer Controller

Create the IAM policy of the release you install, an IAM role for the
controller's service account (IRSA), and install the chart:

```bash
curl -o iam-policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v3.6.3/docs/install/iam_policy.json
aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam-policy.json

eksctl utils associate-iam-oidc-provider --region <region> --cluster <cluster-name> --approve
eksctl create iamserviceaccount \
  --cluster=<cluster-name> \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --attach-policy-arn=arn:aws:iam::<account-id>:policy/AWSLoadBalancerControllerIAMPolicy \
  --override-existing-serviceaccounts \
  --region <region> \
  --approve

helm repo add eks https://aws.github.io/eks-charts
helm repo update eks
helm install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system \
  --version 3.6.3 \
  --set clusterName=<cluster-name> \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller

kubectl get deployment -n kube-system aws-load-balancer-controller
```

- The node security group must admit TCP port 9443 from the control plane,
  for the controller's webhooks.
- On nodes with IMDSv2, set the hop limit to 2 or more, or add
  `--set region=<region> --set vpcId=<vpc-id>`.
- EKS Pod Identity can replace IRSA.
- `helm install` applies the controller's CRDs, but `helm upgrade` does not:
  apply them from the chart before an upgrade.

See the controller's
[installation guide](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/deploy/installation/)
and [Install AWS Load Balancer Controller with Helm](https://docs.aws.amazon.com/eks/latest/userguide/lbc-helm.html).
The EKS guide may name an older release than the controller's own site.

### Subnet tags

The controller places a load balancer in the subnets tagged for it:
`kubernetes.io/role/elb` set to `1` on public subnets for an internet-facing
one, `kubernetes.io/role/internal-elb` set to `1` on private subnets for an
internal one. An ALB needs subnets in at least two Availability Zones. From
v2.12.1, when no subnet carries a role tag, the controller picks subnets by how
they are reachable instead. To list the subnets of the VPC that carry a tag,
and to tag one:

```bash
aws ec2 describe-subnets \
  --filters Name=vpc-id,Values=<vpc-id> Name=tag-key,Values=kubernetes.io/role/elb \
  --query 'Subnets[].[SubnetId,AvailabilityZone]' --output text
aws ec2 create-tags --resources <subnet-id> --tags Key=kubernetes.io/role/elb,Value=1
```

See [Subnet auto-discovery](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/deploy/subnet_discovery/).

### ACM certificate

Request it in the cluster's Region:

```bash
aws acm request-certificate --region <region> --domain-name gw.example.com --validation-method DNS
```

Create the CNAME record that ACM lists for the domain, in the console or in
`aws acm describe-certificate --region <region> --certificate-arn <arn>`, and
leave it in place: ACM needs it for every renewal. The certificate is ready
when its status is `ISSUED`. See
[Request a public certificate](https://docs.aws.amazon.com/acm/latest/userguide/acm-public-certificates.html)
and [DNS validation](https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html).

### Gateway API CRDs

```bash
kubectl apply --server-side=true -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.0/standard-install.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/refs/tags/v3.6.3/config/crd/gateway/gateway-crds.yaml
```

The controller is built for Gateway API v1.6.0. Skip the first command where
the cluster already has the Gateway API CRDs at v1.6.0 or later, and take the
controller's own CRDs from the tag of the controller version you run: those of
a release before v3.5.0 serve no `v1`. The controller looks for the CRDs only
when it starts, so install them before it, or restart it afterwards:

```bash
kubectl rollout restart deployment aws-load-balancer-controller -n kube-system
```

See
[Gateway API](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/gateway/gateway/).
