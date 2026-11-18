import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

FULL_NAME = "release-name-hush-agw"

SHARED = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.controller=gke-gateway "
    "--set agw.httpRoute.parentRefs[0].name=shared"
)

OWN = (
    "--set agw.httpRoute.enabled=true "
    "--set agw.httpRoute.controller=gke-gateway "
    "--set agw.httpRoute.gateway.enabled=true"
)


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _kind(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


# With a shared Gateway, the gke-gateway preset configures the Hush AGW
# backend only: a HealthCheckPolicy on the readiness port, which GKE Gateway
# does not infer, and a GCPBackendPolicy that lets a response last 30 minutes
# and keeps a client on one pod through a cookie. The Gateway belongs to its
# owner, so no GCPGatewayPolicy is rendered.
def test_gke_gateway_preset_configures_the_backend_of_a_shared_gateway():
    # Render the preset with a shared Gateway.
    docs = _docs(SHARED)

    # The HealthCheckPolicy checks the readiness port of the chart's Service.
    (health_check,) = _kind(docs, "HealthCheckPolicy")
    assert health_check["apiVersion"] == "networking.gke.io/v1"
    assert health_check["spec"] == {
        "default": {
            "config": {
                "type": "HTTP",
                "httpHealthCheck": {
                    "portSpecification": "USE_FIXED_PORT",
                    "port": 15021,
                    "requestPath": "/healthz/ready",
                },
            }
        },
        "targetRef": {"group": "", "kind": "Service", "name": FULL_NAME},
    }

    # The GCPBackendPolicy sets the backend timeout and cookie affinity.
    (backend_policy,) = _kind(docs, "GCPBackendPolicy")
    assert backend_policy["apiVersion"] == "networking.gke.io/v1"
    assert backend_policy["spec"] == {
        "default": {
            "timeoutSec": 1800,
            "sessionAffinity": {"type": "GENERATED_COOKIE"},
        },
        "targetRef": {"group": "", "kind": "Service", "name": FULL_NAME},
    }

    # Neither a GCPGatewayPolicy nor a Gateway is rendered.
    assert _kind(docs, "GCPGatewayPolicy") == []
    assert _kind(docs, "Gateway") == []


# The chart's own Gateway defaults to the global external Application Load
# Balancer and takes its certificate from exactly one source: a Secret, a
# Certificate Manager map through an annotation and no tls section, or a
# Compute Engine SSL certificate through the listener's tls options.
@pytest.mark.parametrize(
    "extra_args, annotations, tls",
    [
        (
            "--set agw.httpRoute.gateway.tls.secretName=gw-tls",
            None,
            {"mode": "Terminate", "certificateRefs": [{"name": "gw-tls"}]},
        ),
        (
            "--set agw.httpRoute.gkeGateway.certificateMap=hush-agw-map",
            {"networking.gke.io/certmap": "hush-agw-map"},
            None,
        ),
        (
            "--set agw.httpRoute.gkeGateway.preSharedCertificate=hush-agw",
            None,
            {
                "mode": "Terminate",
                "options": {"networking.gke.io/pre-shared-certs": "hush-agw"},
            },
        ),
    ],
)
def test_gke_gateway_preset_takes_the_certificate_of_its_own_gateway(
    extra_args, annotations, tls
):
    # Render the chart's own Gateway with one certificate source.
    docs = _docs(f"{OWN} {extra_args}")
    (gateway,) = _kind(docs, "Gateway")

    # The class is the global external one.
    assert gateway["spec"]["gatewayClassName"] == "gke-l7-global-external-managed"

    # The certificate source shows up as an annotation or as the listener's tls.
    assert gateway["metadata"].get("annotations") == annotations
    (listener,) = gateway["spec"]["listeners"]
    assert listener.get("tls") == tls


# The chart's own Gateway needs one certificate source, so none and more than
# one are both refused.
@pytest.mark.parametrize(
    "extra_args",
    [
        "",
        (
            "--set agw.httpRoute.gkeGateway.certificateMap=hush-agw-map "
            "--set agw.httpRoute.gateway.tls.secretName=gw-tls"
        ),
    ],
)
def test_gke_gateway_preset_needs_exactly_one_certificate(extra_args):
    # Render the chart's own Gateway with no or two certificate sources.
    stderr = _template_error(f"{OWN} {extra_args}")

    # The error lists the sources.
    assert "exactly one of 'agw.httpRoute.gateway.tls.secretName'" in stderr


# Annotations given under 'agw.httpRoute.gateway.annotations' replace the ones
# the preset sets on the chart's own Gateway, so a setting the preset gets
# wrong for one cluster can still be fixed.
def test_gke_gateway_preset_yields_to_the_given_gateway_annotations():
    # Render the chart's own Gateway with a certificate map and an annotation
    # of the customer's own naming another map.
    docs = _docs(
        f"{OWN} --set agw.httpRoute.gkeGateway.certificateMap=hush-agw-map "
        "--set-string agw.httpRoute.gateway.annotations.networking\\\\.gke\\\\.io/"
        "certmap=other-map"
    )

    # The Gateway carries the customer's map in place of the preset's.
    (gateway,) = _kind(docs, "Gateway")
    assert gateway["metadata"]["annotations"] == {
        "networking.gke.io/certmap": "other-map"
    }


# The SSL policy is applied to the chart's own Gateway through a
# GCPGatewayPolicy, and the class, the timeout and the affinity are taken from
# the values.
def test_gke_gateway_preset_takes_its_values():
    # Render the chart's own Gateway with an internal class, an SSL policy, a
    # two hour timeout and client IP affinity.
    docs = _docs(
        f"{OWN} --set agw.httpRoute.gkeGateway.certificateMap=hush-agw-map "
        "--set agw.httpRoute.gateway.className=gke-l7-rilb "
        "--set agw.httpRoute.gkeGateway.sslPolicy=hush-agw-tls "
        "--set agw.httpRoute.gkeGateway.backendPolicy.timeoutSec=7200 "
        "--set agw.httpRoute.gkeGateway.backendPolicy.sessionAffinity.type="
        "CLIENT_IP"
    )

    # The Gateway takes the class.
    (gateway,) = _kind(docs, "Gateway")
    assert gateway["spec"]["gatewayClassName"] == "gke-l7-rilb"

    # The GCPGatewayPolicy names the SSL policy and targets the Gateway.
    (gateway_policy,) = _kind(docs, "GCPGatewayPolicy")
    assert gateway_policy["apiVersion"] == "networking.gke.io/v1"
    assert gateway_policy["spec"] == {
        "default": {"sslPolicy": "hush-agw-tls"},
        "targetRef": {
            "group": "gateway.networking.k8s.io",
            "kind": "Gateway",
            "name": FULL_NAME,
        },
    }

    # The GCPBackendPolicy carries the timeout and the affinity, with nothing
    # of the cookie affinity it replaces.
    (backend_policy,) = _kind(docs, "GCPBackendPolicy")
    assert backend_policy["spec"]["default"] == {
        "timeoutSec": 7200,
        "sessionAffinity": {"type": "CLIENT_IP"},
    }


# Each backend object of the preset can be turned off, for a customer who
# provides it another way.
def test_gke_gateway_preset_objects_can_be_turned_off():
    # Render the preset with both backend objects off.
    docs = _docs(
        f"{SHARED} --set agw.httpRoute.gkeGateway.healthCheckPolicy.enabled=false "
        "--set agw.httpRoute.gkeGateway.backendPolicy.enabled=false"
    )

    # Neither object is rendered.
    assert _kind(docs, "HealthCheckPolicy") == []
    assert _kind(docs, "GCPBackendPolicy") == []


# A null session affinity turns it off, leaving Google's default of none.
def test_gke_gateway_preset_affinity_can_be_turned_off():
    # Render the preset without session affinity.
    docs = _docs(
        f"{SHARED} --set agw.httpRoute.gkeGateway.backendPolicy.sessionAffinity=null"
    )

    # The GCPBackendPolicy sets the timeout only.
    (backend_policy,) = _kind(docs, "GCPBackendPolicy")
    assert backend_policy["spec"]["default"] == {"timeoutSec": 1800}
