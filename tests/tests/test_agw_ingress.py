import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

INGRESS = (
    "--set agw.ingress.enabled=true "
    "--set agw.ingress.className=example "
    "--set-string agw.ingress.annotations.example\\\\.com/proxy-read-timeout=3600"
)


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _ingresses(docs):
    return [doc for doc in docs if doc["kind"] == "Ingress"]


# No Ingress is rendered unless asked for, so an installation that fronts
# Hush AGW with an edge of its own gets no second one after an upgrade.
def test_no_ingress_by_default():
    # Render the chart with its defaults.
    docs = _docs()

    # No Ingress is among the rendered objects.
    assert _ingresses(docs) == []


# The Ingress answers for the hostname alone and sends every path of it to the
# chart's Service port named gateway. Without a TLS Secret it carries no tls
# section, for a controller that takes the certificate from an annotation.
def test_ingress_sends_every_path_of_the_hostname_to_hush_agw():
    # Render an Ingress with a class and an annotation.
    docs = _docs(INGRESS)
    (ingress,) = _ingresses(docs)
    (service,) = [doc for doc in docs if doc["kind"] == "Service"]

    # The class and the annotation are passed through as given.
    assert ingress["metadata"]["annotations"] == {
        "example.com/proxy-read-timeout": "3600"
    }
    spec = ingress["spec"]
    assert spec["ingressClassName"] == "example"

    # One rule, for the hostname, sends every path to the Service port named
    # gateway.
    assert spec["rules"] == [
        {
            "host": "gw.example.com",
            "http": {
                "paths": [
                    {
                        "path": "/",
                        "pathType": "Prefix",
                        "backend": {
                            "service": {
                                "name": service["metadata"]["name"],
                                "port": {"name": "gateway"},
                            }
                        },
                    }
                ]
            },
        }
    ]

    # Without a TLS Secret there is no tls section.
    assert "tls" not in spec


# A TLS Secret is used for the hostname, and a class left empty is
# left to the cluster's default IngressClass.
def test_ingress_tls_secret_covers_the_hostname():
    # Render an Ingress with a TLS Secret and no class.
    docs = _docs(
        "--set agw.ingress.enabled=true "
        "--set agw.ingress.tls.secretName=gw-example-com-tls"
    )
    (ingress,) = _ingresses(docs)

    # The Secret is used for the hostname.
    spec = ingress["spec"]
    assert spec["tls"] == [
        {"hosts": ["gw.example.com"], "secretName": "gw-example-com-tls"}
    ]

    # No class is named.
    assert "ingressClassName" not in spec


# An Ingress in front of a LoadBalancer Service would put a second load
# balancer in front of Hush AGW, so the two are refused together.
def test_ingress_is_refused_with_a_load_balancer_service():
    # Render an Ingress with the Service made a LoadBalancer.
    stderr = _template_error(f"{INGRESS} --set agw.service.type=LoadBalancer")

    # The error names the conflict.
    assert "'agw.ingress' cannot be enabled with a LoadBalancer Service" in stderr
