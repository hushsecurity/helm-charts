import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

FULL_NAME = "release-name-hush-agw"

SHARED = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.controller=azure-agc "
    "--set agw.httpRoute.parentRefs[0].name=shared"
)

OWN = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.controller=azure-agc "
    "--set agw.httpRoute.gateway.enabled=true "
    "--set agw.httpRoute.gateway.tls.secretName=gw-example-com-tls"
)

MANAGED = (
    "--set agw.httpRoute.azureAgc.albName=alb "
    "--set agw.httpRoute.azureAgc.albNamespace=alb-infra"
)


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _kind(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


# With a shared Gateway, the azure-agc preset health checks Hush AGW on its
# readiness port, lets a request on the HTTPRoute last 30 minutes, since AGC
# cuts it at the timeout even while an MCP stream flows, and keeps a client on
# one pod through a cookie. The Gateway belongs to its owner.
def test_azure_agc_preset_configures_the_backend_of_a_shared_gateway():
    # Render the preset with a shared Gateway.
    docs = _docs(SHARED)

    # The HealthCheckPolicy checks the readiness port of the chart's Service.
    (health_check,) = _kind(docs, "HealthCheckPolicy")
    assert health_check["apiVersion"] == "alb.networking.azure.io/v1"
    assert health_check["spec"] == {
        "targetRef": {"group": "", "kind": "Service", "name": FULL_NAME},
        "default": {"port": 15021, "http": {"path": "/healthz/ready"}},
    }

    # The HTTPRoute's rule carries the request timeout.
    (route,) = _kind(docs, "HTTPRoute")
    (rule,) = route["spec"]["rules"]
    assert rule["timeouts"] == {"request": "1800s"}

    # The RoutePolicy targets the HTTPRoute with the affinity. It names the
    # HTTPRoute by its API group, which the ALB Controller requires, rather
    # than the empty group of Microsoft's RoutePolicy example.
    (route_policy,) = _kind(docs, "RoutePolicy")
    assert route_policy["apiVersion"] == "alb.networking.azure.io/v1"
    assert route_policy["spec"] == {
        "targetRef": {
            "group": "gateway.networking.k8s.io",
            "kind": "HTTPRoute",
            "name": FULL_NAME,
        },
        "default": {"sessionAffinity": {"affinityType": "managed-cookie"}},
    }

    # No Gateway is rendered.
    assert _kind(docs, "Gateway") == []


# The chart's own Gateway defaults to the azure-alb-external class, binds to
# the ApplicationLoadBalancer the ALB Controller manages, and terminates TLS
# with the Secret.
def test_azure_agc_preset_binds_its_own_gateway_to_a_managed_load_balancer():
    # Render the chart's own Gateway bound to a managed ApplicationLoadBalancer.
    docs = _docs(f"{OWN} {MANAGED}")
    (gateway,) = _kind(docs, "Gateway")

    # The class and the binding annotations are set, with no addresses.
    assert gateway["spec"]["gatewayClassName"] == "azure-alb-external"
    assert gateway["metadata"]["annotations"] == {
        "alb.networking.azure.io/alb-name": "alb",
        "alb.networking.azure.io/alb-namespace": "alb-infra",
    }
    assert "addresses" not in gateway["spec"]

    # The listener terminates TLS with the Secret.
    (listener,) = gateway["spec"]["listeners"]
    assert listener["tls"] == {
        "mode": "Terminate",
        "certificateRefs": [{"name": "gw-example-com-tls"}],
    }


# An Azure Application Gateway for Containers managed outside the cluster is
# named by its resource ID, and its frontend by the Gateway's addresses.
def test_azure_agc_preset_binds_its_own_gateway_to_an_existing_agc():
    # Render the chart's own Gateway bound by resource ID.
    docs = _docs(
        f"{OWN} --set agw.httpRoute.azureAgc.albId=/subscriptions/x/agc "
        "--set agw.httpRoute.azureAgc.albFrontend=frontend"
    )
    (gateway,) = _kind(docs, "Gateway")

    # The resource ID is an annotation, and the frontend an address.
    assert gateway["metadata"]["annotations"] == {
        "alb.networking.azure.io/alb-id": "/subscriptions/x/agc"
    }
    assert gateway["spec"]["addresses"] == [
        {"type": "alb.networking.azure.io/alb-frontend", "value": "frontend"}
    ]


# The chart's own Gateway is refused without what AGC needs: a binding to a
# load balancer, the frontend of one bound by resource ID, and a TLS Secret.
@pytest.mark.parametrize(
    "extra_args, message",
    [
        ("", "'agw.httpRoute.azureAgc.albName' and 'albNamespace', or 'albId'"),
        (
            "--set agw.httpRoute.azureAgc.albName=alb",
            "'agw.httpRoute.azureAgc.albNamespace' is required with 'albName'",
        ),
        (
            "--set agw.httpRoute.azureAgc.albId=/subscriptions/x/agc",
            "'agw.httpRoute.azureAgc.albFrontend' is required with 'albId'",
        ),
        (
            f"{MANAGED} --set agw.httpRoute.gateway.tls.secretName=",
            "'agw.httpRoute.gateway.tls.secretName' is required for azure-agc",
        ),
    ],
)
def test_azure_agc_preset_refuses_an_incomplete_gateway(extra_args, message):
    # Render the chart's own Gateway with the value missing.
    stderr = _template_error(f"{OWN} {extra_args}")

    # The error names it.
    assert message in stderr


# The request timeout is taken from the values, and a null session affinity
# turns it off, with the RoutePolicy that carries it.
def test_azure_agc_preset_takes_the_timeout_and_turns_the_affinity_off():
    # Render the preset with a two hour timeout and no affinity.
    docs = _docs(
        f"{SHARED} --set agw.httpRoute.azureAgc.requestTimeout=2h "
        "--set agw.httpRoute.azureAgc.sessionAffinity=null"
    )

    # The HTTPRoute carries the timeout.
    (route,) = _kind(docs, "HTTPRoute")
    (rule,) = route["spec"]["rules"]
    assert rule["timeouts"] == {"request": "2h"}

    # No RoutePolicy is rendered.
    assert _kind(docs, "RoutePolicy") == []


# The HealthCheckPolicy can be turned off, for a customer who provides it
# another way.
def test_azure_agc_preset_health_check_can_be_turned_off():
    # Render the preset with the HealthCheckPolicy off.
    docs = _docs(
        f"{SHARED} --set agw.httpRoute.azureAgc.healthCheckPolicy.enabled=false"
    )

    # No HealthCheckPolicy is rendered.
    assert _kind(docs, "HealthCheckPolicy") == []
