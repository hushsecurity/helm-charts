import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

FULL_NAME = "release-name-hush-agw"

CERTIFICATE_ARN = "arn:aws:acm:us-east-1:123456789012:certificate/example"

SHARED = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.controller=aws-alb "
    "--set agw.httpRoute.parentRefs[0].name=shared"
)

OWN = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.controller=aws-alb "
    "--set agw.httpRoute.gateway.enabled=true "
    "--set agw.httpRoute.gateway.className=aws-alb"
)


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _kind(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


# With a shared Gateway, the aws-alb preset configures the Hush AGW target
# group only: pod IP targets, a health check on the readiness port, and the
# target group attributes at AWS's defaults. The load balancer belongs to the
# Gateway's owner, so no LoadBalancerConfiguration is rendered.
def test_aws_alb_preset_configures_the_target_group_of_a_shared_gateway():
    # Render the preset with a shared Gateway.
    docs = _docs(SHARED)

    # The TargetGroupConfiguration targets the chart's Service.
    (target_group,) = _kind(docs, "TargetGroupConfiguration")
    assert target_group["apiVersion"] == "gateway.k8s.aws/v1"
    assert target_group["spec"] == {
        "targetReference": {"name": FULL_NAME},
        "defaultConfiguration": {
            "targetType": "ip",
            "healthCheckConfig": {
                "healthCheckProtocol": "HTTP",
                "healthCheckPort": "15021",
                "healthCheckPath": "/healthz/ready",
            },
            "targetGroupAttributes": [
                {"key": "stickiness.enabled", "value": "false"},
                {"key": "stickiness.lb_cookie.duration_seconds", "value": "86400"},
                {"key": "load_balancing.cross_zone.enabled", "value": "true"},
            ],
        },
    }

    # Neither a LoadBalancerConfiguration nor a Gateway is rendered.
    assert _kind(docs, "LoadBalancerConfiguration") == []
    assert _kind(docs, "Gateway") == []


# With the chart's own Gateway, the preset adds a LoadBalancerConfiguration
# that makes the ALB internet-facing, HTTPS-only with TLS 1.2 or later, and
# keeps idle connections for ten minutes. The Gateway refers to it, and its
# listener carries no tls section: the controller finds the ACM certificate by
# the listener's hostname.
def test_aws_alb_preset_configures_the_load_balancer_of_its_own_gateway():
    # Render the preset with the chart's own Gateway.
    docs = _docs(OWN)

    # The LoadBalancerConfiguration carries the preset's defaults and names no
    # certificate.
    (load_balancer,) = _kind(docs, "LoadBalancerConfiguration")
    assert load_balancer["apiVersion"] == "gateway.k8s.aws/v1"
    assert load_balancer["metadata"]["name"] == FULL_NAME
    assert load_balancer["spec"] == {
        "scheme": "internet-facing",
        "loadBalancerAttributes": [
            {"key": "idle_timeout.timeout_seconds", "value": "600"}
        ],
        "listenerConfigurations": [
            {
                "protocolPort": "HTTPS:443",
                "sslPolicy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
            }
        ],
    }

    # The Gateway refers to it, and its listener has no tls section.
    (gateway,) = _kind(docs, "Gateway")
    assert gateway["spec"]["infrastructure"] == {
        "parametersRef": {
            "group": "gateway.k8s.aws",
            "kind": "LoadBalancerConfiguration",
            "name": FULL_NAME,
        }
    }
    (listener,) = gateway["spec"]["listeners"]
    assert "tls" not in listener


# The scheme, the certificate, the idle timeout, the TLS policy, the stickiness
# and cross-zone load balancing are taken from the values.
def test_aws_alb_preset_takes_its_values():
    # Render an internal ALB with a certificate, a longer idle timeout, another
    # TLS policy and sticky sessions of an hour.
    lb = "agw.httpRoute.awsAlb.loadBalancerConfiguration"
    tg = "agw.httpRoute.awsAlb.targetGroupConfiguration"
    docs = _docs(
        f"{OWN} --set {lb}.scheme=internal "
        f"--set {lb}.certificateArn={CERTIFICATE_ARN} "
        f"--set {lb}.idleTimeout=1200 "
        f"--set {lb}.sslPolicy=ELBSecurityPolicy-TLS13-1-3-2021-06 "
        f"--set {tg}.stickiness.enabled=true "
        f"--set {tg}.stickiness.duration=3600"
    )

    # Each value reaches its field.
    (load_balancer,) = _kind(docs, "LoadBalancerConfiguration")
    assert load_balancer["spec"]["scheme"] == "internal"
    assert load_balancer["spec"]["loadBalancerAttributes"] == [
        {"key": "idle_timeout.timeout_seconds", "value": "1200"}
    ]
    assert load_balancer["spec"]["listenerConfigurations"] == [
        {
            "protocolPort": "HTTPS:443",
            "sslPolicy": "ELBSecurityPolicy-TLS13-1-3-2021-06",
            "defaultCertificate": CERTIFICATE_ARN,
        }
    ]
    (target_group,) = _kind(docs, "TargetGroupConfiguration")
    assert target_group["spec"]["defaultConfiguration"]["targetGroupAttributes"] == [
        {"key": "stickiness.enabled", "value": "true"},
        {"key": "stickiness.lb_cookie.duration_seconds", "value": "3600"},
        {"key": "load_balancing.cross_zone.enabled", "value": "true"},
    ]


# Cross-zone load balancing can be turned off while stickiness stays off.
def test_aws_alb_preset_turns_cross_zone_off():
    # Render the preset with cross-zone load balancing off.
    tg = "agw.httpRoute.awsAlb.targetGroupConfiguration"
    docs = _docs(f"{SHARED} --set {tg}.crossZone=false")

    # The target group attributes turn it off and keep stickiness off.
    (target_group,) = _kind(docs, "TargetGroupConfiguration")
    assert target_group["spec"]["defaultConfiguration"]["targetGroupAttributes"] == [
        {"key": "stickiness.enabled", "value": "false"},
        {"key": "stickiness.lb_cookie.duration_seconds", "value": "86400"},
        {"key": "load_balancing.cross_zone.enabled", "value": "false"},
    ]


# AWS refuses stickiness on an ALB target group with cross-zone load balancing
# off, and the controller then applies no change to the Gateway, so the preset
# refuses the pair rather than render it.
def test_aws_alb_preset_refuses_stickiness_without_cross_zone():
    # Render the preset with stickiness on and cross-zone load balancing off.
    tg = "agw.httpRoute.awsAlb.targetGroupConfiguration"
    stderr = _template_error(
        f"{SHARED} --set {tg}.stickiness.enabled=true --set {tg}.crossZone=false"
    )

    # The error says why.
    assert (
        "'agw.httpRoute.awsAlb.targetGroupConfiguration.stickiness.enabled' "
        "cannot be used with 'crossZone: false', which AWS refuses on an ALB "
        "target group"
    ) in stderr


# An empty TLS policy is left out of the listener, so that the controller's own
# default applies.
def test_aws_alb_preset_leaves_an_empty_tls_policy_out():
    # Render the preset with the chart's own Gateway and the TLS policy emptied.
    docs = _docs(
        f"{OWN} --set agw.httpRoute.awsAlb.loadBalancerConfiguration.sslPolicy="
    )

    # The listener names no policy.
    (load_balancer,) = _kind(docs, "LoadBalancerConfiguration")
    assert load_balancer["spec"]["listenerConfigurations"] == [
        {"protocolPort": "HTTPS:443"}
    ]


# Each object of the preset can be turned off, for a customer who provides it
# another way, and the Gateway then refers to no LoadBalancerConfiguration.
def test_aws_alb_preset_objects_can_be_turned_off():
    # Render the preset with the chart's own Gateway and both objects off.
    docs = _docs(
        f"{OWN} "
        "--set agw.httpRoute.awsAlb.targetGroupConfiguration.enabled=false "
        "--set agw.httpRoute.awsAlb.loadBalancerConfiguration.enabled=false"
    )

    # Neither object is rendered, and the Gateway has no infrastructure.
    assert _kind(docs, "TargetGroupConfiguration") == []
    assert _kind(docs, "LoadBalancerConfiguration") == []
    (gateway,) = _kind(docs, "Gateway")
    assert "infrastructure" not in gateway["spec"]


# The controller takes no certificate from a Secret, so a TLS Secret on the
# chart's own Gateway is refused rather than silently ignored.
def test_aws_alb_preset_refuses_a_tls_secret():
    # Render the preset with a TLS Secret on the chart's own Gateway.
    stderr = _template_error(f"{OWN} --set agw.httpRoute.gateway.tls.secretName=gw-tls")

    # The error says why.
    assert "cannot be used with aws-alb, which takes the certificate from ACM" in (
        stderr
    )


# An implementation the chart has no preset for is refused rather than
# ignored.
def test_unknown_route_controller_is_refused():
    # Render the HTTPRoute with an implementation that has no preset.
    stderr = _template_error(
        "--set agw.httpRoute.enabled=true "
        "--set agw.httpRoute.parentRefs[0].name=shared "
        "--set agw.httpRoute.controller=envoy"
    )

    # The error lists what is accepted.
    assert "'agw.httpRoute.controller' must be empty or one of: aws-alb" in stderr
