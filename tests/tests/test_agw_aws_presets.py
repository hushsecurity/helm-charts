import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

CERTIFICATE_ARN = "arn:aws:acm:us-east-1:123456789012:certificate/example"

NLB = (
    "--set agw.service.loadBalancer=aws-nlb "
    f"--set agw.service.awsNlb.certificateArn={CERTIFICATE_ARN}"
)

ALB = "--set agw.ingress.enabled=true --set agw.ingress.controller=aws-alb"

NLB_ANNOTATIONS = {
    "service.beta.kubernetes.io/aws-load-balancer-type": "external",
    "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type": "ip",
    "service.beta.kubernetes.io/aws-load-balancer-scheme": "internet-facing",
    "service.beta.kubernetes.io/aws-load-balancer-ssl-cert": CERTIFICATE_ARN,
    "service.beta.kubernetes.io/aws-load-balancer-ssl-ports": "443",
    "service.beta.kubernetes.io/aws-load-balancer-ssl-negotiation-policy": (
        "ELBSecurityPolicy-TLS13-1-2-2021-06"
    ),
    "service.beta.kubernetes.io/aws-load-balancer-healthcheck-protocol": "http",
    "service.beta.kubernetes.io/aws-load-balancer-healthcheck-port": "15021",
    "service.beta.kubernetes.io/aws-load-balancer-healthcheck-path": "/healthz/ready",
    "service.beta.kubernetes.io/aws-load-balancer-attributes": (
        "load_balancing.cross_zone.enabled=true"
    ),
}

ALB_ANNOTATIONS = {
    "alb.ingress.kubernetes.io/scheme": "internet-facing",
    "alb.ingress.kubernetes.io/target-type": "ip",
    "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}]',
    "alb.ingress.kubernetes.io/healthcheck-port": "15021",
    "alb.ingress.kubernetes.io/healthcheck-path": "/healthz/ready",
    "alb.ingress.kubernetes.io/load-balancer-attributes": (
        "idle_timeout.timeout_seconds=600"
    ),
    "alb.ingress.kubernetes.io/ssl-policy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
    "alb.ingress.kubernetes.io/target-group-attributes": (
        "stickiness.enabled=false,stickiness.lb_cookie.duration_seconds=86400,"
        "load_balancing.cross_zone.enabled=true"
    ),
}


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _service(extra_args=""):
    (service,) = [doc for doc in _docs(extra_args) if doc["kind"] == "Service"]
    return service


def _ingress(extra_args=""):
    (ingress,) = [doc for doc in _docs(extra_args) if doc["kind"] == "Ingress"]
    return ingress


# The aws-nlb preset turns the Service into an AWS Network Load Balancer that
# meets the needs of Hush AGW: TLS 1.2 or later on 443 with the given
# certificate, pod IP targets with no node ports, the health check on the
# readiness port, and cross-zone load balancing. It does so even though 'type'
# keeps its ClusterIP default, so the customer sets the certificate and nothing
# else.
def test_aws_nlb_preset_makes_a_tls_load_balancer_on_443():
    # Render the preset with only the certificate given.
    service = _service(NLB)

    # The Service carries every annotation of the preset.
    assert service["metadata"]["annotations"] == NLB_ANNOTATIONS

    # It is a LoadBalancer on 443 forwarding to the container port.
    spec = service["spec"]
    assert spec["type"] == "LoadBalancer"
    assert spec["ports"] == [
        {"name": "gateway", "port": 443, "targetPort": "gateway-http"}
    ]

    # It allocates no node ports, which pod IP targets do not use.
    assert spec["allocateLoadBalancerNodePorts"] is False


# The preset's scheme, TLS policy and cross-zone load balancing are taken from
# the values, and an annotation given under 'agw.service.annotations' replaces
# the preset's own for the same key while the other preset annotations stay.
def test_aws_nlb_preset_takes_its_values_and_yields_to_given_annotations():
    # Render an internal NLB with another TLS policy, cross-zone load balancing
    # off, the health check path overridden and one extra annotation.
    service = _service(
        f"{NLB} --set agw.service.awsNlb.scheme=internal "
        "--set agw.service.awsNlb.sslPolicy=ELBSecurityPolicy-TLS13-1-3-2021-06 "
        "--set agw.service.awsNlb.crossZone=false "
        "--set-string agw.service.annotations.service\\\\.beta\\\\.kubernetes\\\\.io/"
        "aws-load-balancer-healthcheck-path=/other "
        "--set-string agw.service.annotations.example\\\\.com/extra=yes"
    )

    # The values and the override take effect, the extra annotation is added,
    # and the rest of the preset stays.
    expected = dict(NLB_ANNOTATIONS)
    expected["service.beta.kubernetes.io/aws-load-balancer-scheme"] = "internal"
    expected["service.beta.kubernetes.io/aws-load-balancer-ssl-negotiation-policy"] = (
        "ELBSecurityPolicy-TLS13-1-3-2021-06"
    )
    expected["service.beta.kubernetes.io/aws-load-balancer-attributes"] = (
        "load_balancing.cross_zone.enabled=false"
    )
    expected["service.beta.kubernetes.io/aws-load-balancer-healthcheck-path"] = "/other"
    expected["example.com/extra"] = "yes"
    assert service["metadata"]["annotations"] == expected


# The client ranges and the class still apply to a LoadBalancer the preset
# makes, since the type the preset sets is what decides.
def test_aws_nlb_preset_keeps_the_class_and_the_client_ranges():
    # Render the preset with a class and client ranges.
    service = _service(
        f"{NLB} --set agw.service.loadBalancerClass=service.k8s.aws/nlb "
        "--set agw.service.loadBalancerSourceRanges={203.0.113.0/24}"
    )

    # Both are rendered.
    spec = service["spec"]
    assert spec["loadBalancerClass"] == "service.k8s.aws/nlb"
    assert spec["loadBalancerSourceRanges"] == ["203.0.113.0/24"]


# A LoadBalancer without the preset keeps the node ports Kubernetes allocates
# by default, since its load balancer may reach Hush AGW through the nodes.
def test_load_balancer_without_the_preset_keeps_its_node_ports():
    # Render a LoadBalancer with no preset.
    service = _service("--set agw.service.type=LoadBalancer")

    # The Service leaves the node ports to Kubernetes.
    assert "allocateLoadBalancerNodePorts" not in service["spec"]


# An NLB TLS listener cannot be made without a certificate, so the preset
# refuses to render without one rather than leave a plain TCP listener on 443.
def test_aws_nlb_preset_requires_a_certificate():
    # Render the preset without a certificate.
    stderr = _template_error("--set agw.service.loadBalancer=aws-nlb")

    # The error names the missing value.
    assert "'agw.service.awsNlb.certificateArn' is required" in stderr


# A load balancer the chart has no preset for is refused rather than ignored.
def test_unknown_load_balancer_is_refused():
    # Render with a load balancer that has no preset.
    stderr = _template_error("--set agw.service.loadBalancer=azure-lb")

    # The error lists what is accepted.
    assert "'agw.service.loadBalancer' must be empty or one of: aws-nlb" in stderr


# The aws-alb preset gives the Ingress the alb class and the annotations that
# meet the needs of Hush AGW: HTTPS on 443 only with TLS 1.2 or later, pod IP
# targets, the health check on the readiness port, and an idle timeout well
# above the default. The target group attributes keep AWS's defaults: no
# stickiness and cross-zone load balancing on. Without a certificate ARN the
# controller finds the certificate from the rule's host, so none is named.
def test_aws_alb_preset_sets_the_class_and_the_annotations():
    # Render the preset with its defaults.
    ingress = _ingress(ALB)

    # The class is alb and the preset's annotations are set, with no
    # certificate named.
    assert ingress["spec"]["ingressClassName"] == "alb"
    assert ingress["metadata"]["annotations"] == ALB_ANNOTATIONS

    # The Service is left as it is by default.
    service = _service(ALB)
    assert "annotations" not in service["metadata"]
    assert service["spec"]["type"] == "ClusterIP"


# The scheme, the certificate, the idle timeout, the TLS policy, the
# stickiness and cross-zone load balancing are taken from the values.
def test_aws_alb_preset_takes_its_values():
    # Render an internal ALB with a certificate, a longer idle timeout, another
    # TLS policy and sticky sessions of an hour.
    ingress = _ingress(
        f"{ALB} --set agw.ingress.awsAlb.scheme=internal "
        f"--set agw.ingress.awsAlb.certificateArn={CERTIFICATE_ARN} "
        "--set agw.ingress.awsAlb.idleTimeout=1200 "
        "--set agw.ingress.awsAlb.sslPolicy=ELBSecurityPolicy-TLS13-1-3-2021-06 "
        "--set agw.ingress.awsAlb.stickiness.enabled=true "
        "--set agw.ingress.awsAlb.stickiness.duration=3600"
    )

    # Each value reaches its annotation.
    annotations = ingress["metadata"]["annotations"]
    assert annotations["alb.ingress.kubernetes.io/scheme"] == "internal"
    assert annotations["alb.ingress.kubernetes.io/certificate-arn"] == CERTIFICATE_ARN
    assert annotations["alb.ingress.kubernetes.io/load-balancer-attributes"] == (
        "idle_timeout.timeout_seconds=1200"
    )
    assert annotations["alb.ingress.kubernetes.io/ssl-policy"] == (
        "ELBSecurityPolicy-TLS13-1-3-2021-06"
    )
    assert annotations["alb.ingress.kubernetes.io/target-group-attributes"] == (
        "stickiness.enabled=true,stickiness.lb_cookie.duration_seconds=3600,"
        "load_balancing.cross_zone.enabled=true"
    )


# Cross-zone load balancing can be turned off while stickiness stays off.
def test_aws_alb_preset_turns_cross_zone_off():
    # Render the preset with cross-zone load balancing off.
    ingress = _ingress(f"{ALB} --set agw.ingress.awsAlb.crossZone=false")

    # The target group attributes turn it off and keep stickiness off.
    annotations = ingress["metadata"]["annotations"]
    assert annotations["alb.ingress.kubernetes.io/target-group-attributes"] == (
        "stickiness.enabled=false,stickiness.lb_cookie.duration_seconds=86400,"
        "load_balancing.cross_zone.enabled=false"
    )


# AWS refuses stickiness on an ALB target group with cross-zone load balancing
# off, and the controller then applies none of the Ingress's settings, so the
# preset refuses the pair rather than render it.
def test_aws_alb_preset_refuses_stickiness_without_cross_zone():
    # Render the preset with stickiness on and cross-zone load balancing off.
    stderr = _template_error(
        f"{ALB} --set agw.ingress.awsAlb.stickiness.enabled=true "
        "--set agw.ingress.awsAlb.crossZone=false"
    )

    # The error says why.
    assert (
        "'agw.ingress.awsAlb.stickiness.enabled' cannot be used with "
        "'crossZone: false', which AWS refuses on an ALB target group"
    ) in stderr


# 'className' and 'annotations' given with a preset replace what the preset
# sets, so a setting the preset gets wrong for one cluster can still be fixed.
def test_aws_alb_preset_yields_to_the_given_class_and_annotations():
    # Render the preset with a class and an annotation of the customer's own.
    ingress = _ingress(
        f"{ALB} --set agw.ingress.className=alb-internal "
        "--set-string agw.ingress.annotations.alb\\\\.ingress\\\\.kubernetes\\\\.io/"
        "target-type=instance"
    )

    # The class and the annotation are the customer's; the rest of the preset
    # stays.
    assert ingress["spec"]["ingressClassName"] == "alb-internal"
    expected = dict(ALB_ANNOTATIONS)
    expected["alb.ingress.kubernetes.io/target-type"] = "instance"
    assert ingress["metadata"]["annotations"] == expected


# A target group attributes annotation given under 'agw.ingress.annotations'
# replaces the one the preset builds from 'stickiness' and 'crossZone', so
# attributes the values do not cover can still be set.
def test_aws_alb_preset_yields_to_given_target_group_attributes():
    # Render the preset with stickiness on and an annotation of the customer's
    # own holding another attribute.
    ingress = _ingress(
        f"{ALB} --set agw.ingress.awsAlb.stickiness.enabled=true "
        "--set-string agw.ingress.annotations.alb\\\\.ingress\\\\.kubernetes\\\\.io/"
        "target-group-attributes=slow_start.duration_seconds=30"
    )

    # The customer's annotation is used as it is, and the values are not
    # merged into it.
    annotations = ingress["metadata"]["annotations"]
    assert annotations["alb.ingress.kubernetes.io/target-group-attributes"] == (
        "slow_start.duration_seconds=30"
    )


# An empty TLS policy leaves its annotation out, so that the controller's own
# default applies, for a load balancer that does not take the annotation, such
# as an NLB of EKS Auto Mode. An empty annotation under 'annotations' cannot
# do it, since the preset's value takes the place of an empty one.
@pytest.mark.parametrize(
    "extra_args, kind, preset, annotation",
    [
        pytest.param(
            f"{NLB} --set agw.service.awsNlb.sslPolicy=",
            "Service",
            NLB_ANNOTATIONS,
            "service.beta.kubernetes.io/aws-load-balancer-ssl-negotiation-policy",
            id="aws-nlb",
        ),
        pytest.param(
            f"{ALB} --set agw.ingress.awsAlb.sslPolicy=",
            "Ingress",
            ALB_ANNOTATIONS,
            "alb.ingress.kubernetes.io/ssl-policy",
            id="aws-alb",
        ),
    ],
)
def test_aws_presets_leave_an_empty_tls_policy_out(
    extra_args, kind, preset, annotation
):
    # Render the preset with the TLS policy emptied.
    (doc,) = [doc for doc in _docs(extra_args) if doc["kind"] == kind]

    # Every annotation of the preset is set but the TLS policy.
    expected = dict(preset)
    del expected[annotation]
    assert doc["metadata"]["annotations"] == expected


# An ingress controller the chart has no preset for is refused rather than
# ignored.
def test_unknown_ingress_controller_is_refused():
    # Render with a controller that has no preset.
    stderr = _template_error(
        "--set agw.ingress.enabled=true --set agw.ingress.controller=traefik"
    )

    # The error lists what is accepted.
    assert "'agw.ingress.controller' must be empty or one of: aws-alb" in stderr


# The aws-nlb preset makes the Service a LoadBalancer, so it is refused with an
# Ingress like any other LoadBalancer.
def test_aws_nlb_preset_is_refused_with_an_ingress():
    # Render the NLB preset with the ALB preset's Ingress.
    stderr = _template_error(f"{NLB} {ALB}")

    # The error names the conflict.
    assert "'agw.ingress' cannot be enabled with a LoadBalancer Service" in stderr
