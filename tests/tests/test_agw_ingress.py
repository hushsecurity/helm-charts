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


def _ingresses(docs):
    return [doc for doc in docs if doc["kind"] == "Ingress"]


# No Ingress is rendered unless asked for, so an installation that fronts the
# gateway with an edge of its own gets no second one after an upgrade.
def test_no_ingress_by_default():
    # Render the chart with its defaults.
    docs = _docs()

    # No Ingress is among the rendered objects.
    assert _ingresses(docs) == []


# The Ingress answers for the gateway's hostname alone and sends every path of
# it to the gateway port of the chart's Service, by name, so a Service port
# other than the default needs nothing here. Without a TLS Secret it carries no
# tls section, for a controller that takes the certificate from an annotation.
def test_ingress_sends_every_path_of_the_hostname_to_the_gateway():
    # Render an Ingress with a class and an annotation, and the Service on 443.
    docs = _docs(f"{INGRESS} --set agw.service.port=443")
    (ingress,) = _ingresses(docs)
    (service,) = [doc for doc in docs if doc["kind"] == "Service"]

    # The class and the annotation are passed through as given.
    assert ingress["metadata"]["annotations"] == {
        "example.com/proxy-read-timeout": "3600"
    }
    spec = ingress["spec"]
    assert spec["ingressClassName"] == "example"

    # One rule, for the hostname, sends every path to the Service's gateway
    # port.
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


# A TLS Secret is used for the gateway's hostname, and a class left empty is
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
