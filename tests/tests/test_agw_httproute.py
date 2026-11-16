import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

FULL_NAME = "release-name-hush-agw"

ROUTE = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.parentRefs[0].name=shared "
    "--set agw.httpRoute.parentRefs[0].namespace=gateway-infra "
    "--set agw.httpRoute.parentRefs[0].sectionName=https"
)

OWN_GATEWAY = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.gateway.enabled=true "
    "--set agw.httpRoute.gateway.className=example"
)


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _kind(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


# No HTTPRoute or Gateway is rendered unless asked for, so an installation that
# fronts Hush AGW with an edge of its own gets no second one after an upgrade.
def test_no_route_or_gateway_by_default():
    # Render the chart with its defaults.
    docs = _docs()

    # Neither kind is among the rendered objects.
    assert _kind(docs, "HTTPRoute") == []
    assert _kind(docs, "Gateway") == []


# The HTTPRoute attaches to the Gateways it is given, answers for the hostname
# alone, and sends every path of it to the chart's Service port by number,
# which is what a backendRef takes.
def test_route_sends_every_path_of_the_hostname_to_hush_agw():
    # Render an HTTPRoute attached to a shared Gateway, with an annotation.
    docs = _docs(
        f"{ROUTE} --set-string agw.httpRoute.annotations.example\\\\.com/team=edge"
    )
    (route,) = _kind(docs, "HTTPRoute")

    # The annotation and the parentRefs are passed through as given, and no
    # Gateway of the chart's own is rendered.
    assert route["metadata"]["annotations"] == {"example.com/team": "edge"}
    assert route["spec"]["parentRefs"] == [
        {"name": "shared", "namespace": "gateway-infra", "sectionName": "https"}
    ]
    assert _kind(docs, "Gateway") == []

    # One rule, for the hostname, sends every path to the Service on port 3001.
    assert route["spec"]["hostnames"] == ["gw.example.com"]
    assert route["spec"]["rules"] == [
        {
            "matches": [{"path": {"type": "PathPrefix", "value": "/"}}],
            "backendRefs": [{"name": FULL_NAME, "port": 3001}],
        }
    ]


# An HTTPRoute in front of a LoadBalancer Service would put a second load
# balancer in front of Hush AGW, so the two are refused together, whether
# the Service is a LoadBalancer by its type or by the aws-nlb preset.
@pytest.mark.parametrize(
    "service_args",
    [
        "--set agw.service.type=LoadBalancer",
        (
            "--set agw.service.loadBalancer=aws-nlb "
            "--set agw.service.awsNlb.certificateArn=example"
        ),
    ],
)
def test_route_is_refused_with_a_load_balancer_service(service_args):
    # Render the HTTPRoute with the Service made a LoadBalancer.
    stderr = _template_error(f"{ROUTE} {service_args}")

    # The error names the conflict.
    assert "'agw.httpRoute' cannot be enabled with a LoadBalancer Service" in stderr


# A Gateway of the chart's own has one HTTPS listener on 443 for the hostname,
# which admits routes from the release's namespace only and terminates TLS with
# the given Secret. The HTTPRoute attaches to that listener, whatever
# parentRefs say.
def test_own_gateway_serves_the_hostname_and_takes_the_route():
    # Render the chart's own Gateway with a TLS Secret and an annotation, and
    # parentRefs that it replaces.
    docs = _docs(
        f"{OWN_GATEWAY} --set agw.httpRoute.gateway.tls.secretName=gw-tls "
        "--set-string agw.httpRoute.gateway.annotations.example\\\\.com/team=edge "
        "--set agw.httpRoute.parentRefs[0].name=shared"
    )
    (gateway,) = _kind(docs, "Gateway")
    (route,) = _kind(docs, "HTTPRoute")

    # The Gateway carries the class, the annotation and the HTTPS listener.
    assert gateway["metadata"]["name"] == FULL_NAME
    assert gateway["metadata"]["annotations"] == {"example.com/team": "edge"}
    assert gateway["spec"] == {
        "gatewayClassName": "example",
        "listeners": [
            {
                "name": "https",
                "protocol": "HTTPS",
                "port": 443,
                "hostname": "gw.example.com",
                "allowedRoutes": {"namespaces": {"from": "Same"}},
                "tls": {
                    "mode": "Terminate",
                    "certificateRefs": [{"name": "gw-tls"}],
                },
            }
        ],
    }

    # The HTTPRoute attaches to the Gateway's listener only.
    assert route["spec"]["parentRefs"] == [{"name": FULL_NAME, "sectionName": "https"}]


# Without a TLS Secret the listener carries no tls section, for an
# implementation that takes the certificate another way.
def test_own_gateway_without_a_secret_has_no_tls_section():
    # Render the chart's own Gateway without a TLS Secret.
    docs = _docs(OWN_GATEWAY)

    # The listener has no tls section.
    (gateway,) = _kind(docs, "Gateway")
    (listener,) = gateway["spec"]["listeners"]
    assert "tls" not in listener


# An HTTPRoute with nowhere to attach is refused rather than left orphaned, and
# so is a Gateway without a class.
@pytest.mark.parametrize(
    "extra_args, message",
    [
        (
            "--set agw.httpRoute.enabled=true",
            "'agw.httpRoute.parentRefs' or 'agw.httpRoute.gateway.enabled' is required",
        ),
        (
            (
                "--set agw.httpRoute.enabled=true "
                "--set agw.httpRoute.gateway.enabled=true"
            ),
            "'agw.httpRoute.gateway.className' is required",
        ),
    ],
)
def test_route_without_a_gateway_or_class_is_refused(extra_args, message):
    # Render the HTTPRoute with the missing value.
    stderr = _template_error(extra_args)

    # The error names it.
    assert message in stderr


# The HTTPRoute and the Ingress are two ways to put an edge in front of
# Hush AGW, so the chart refuses to render both.
def test_route_and_ingress_are_refused_together():
    # Render both.
    stderr = _template_error(f"{ROUTE} --set agw.ingress.enabled=true")

    # The error names both.
    assert "'agw.ingress' and 'agw.httpRoute' cannot both be enabled" in stderr
