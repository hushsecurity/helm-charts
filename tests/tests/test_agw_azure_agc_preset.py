import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

FULL_NAME = "release-name-hush-agw"

AGC = (
    "--set agw.ingress.enabled=true --set agw.ingress.controller=azure-agc "
    "--set agw.ingress.tls.secretName=gw-example-com-tls "
    "--set agw.ingress.azureAgc.albName=alb "
    "--set agw.ingress.azureAgc.albNamespace=alb-infra"
)


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _kind(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


# The azure-agc preset binds the Ingress to the ApplicationLoadBalancer the
# ALB Controller manages, serves it with the certificate from the Secret, and
# adds a HealthCheckPolicy on the readiness port and an IngressExtension that
# lets a request, an MCP stream included, run for 30 minutes.
def test_azure_agc_preset_sets_up_the_ingress_and_its_objects():
    # Render the preset with a managed ApplicationLoadBalancer.
    docs = _docs(AGC)
    (ingress,) = _kind(docs, "Ingress")
    (policy,) = _kind(docs, "HealthCheckPolicy")
    (extension,) = _kind(docs, "IngressExtension")

    # The Ingress takes the AGC class, names the ApplicationLoadBalancer and
    # the IngressExtension, and carries the TLS Secret for the hostname.
    spec = ingress["spec"]
    assert spec["ingressClassName"] == "azure-alb-external"
    assert ingress["metadata"]["annotations"] == {
        "alb.networking.azure.io/alb-name": "alb",
        "alb.networking.azure.io/alb-namespace": "alb-infra",
        "alb.networking.azure.io/alb-ingress-extension": FULL_NAME,
    }
    assert spec["tls"] == [
        {"hosts": ["gw.example.com"], "secretName": "gw-example-com-tls"}
    ]

    # The HealthCheckPolicy targets the Hush AGW Service and checks the
    # readiness port.
    assert policy["apiVersion"] == "alb.networking.azure.io/v1"
    assert policy["metadata"]["name"] == FULL_NAME
    assert policy["spec"] == {
        "targetRef": {
            "group": "",
            "kind": "Service",
            "name": FULL_NAME,
            "namespace": "default",
        },
        "default": {"port": 15021, "http": {"path": "/healthz/ready"}},
    }

    # The IngressExtension sets the request timeout for the Hush AGW Service.
    assert extension["apiVersion"] == "alb.networking.azure.io/v1"
    assert extension["metadata"]["name"] == FULL_NAME
    assert extension["spec"] == {
        "backendSettings": [
            {"service": FULL_NAME, "timeouts": {"requestTimeout": "1800s"}}
        ]
    }


# An Azure Application Gateway for Containers managed outside the cluster is
# named by its resource ID and frontend instead of an ApplicationLoadBalancer.
def test_azure_agc_preset_takes_agc_by_resource_id():
    # Render the preset with a resource ID and a frontend, and no name.
    docs = _docs(
        "--set agw.ingress.enabled=true --set agw.ingress.controller=azure-agc "
        "--set agw.ingress.tls.secretName=gw-example-com-tls "
        "--set agw.ingress.azureAgc.albId=/subscriptions/example/agc "
        "--set agw.ingress.azureAgc.albFrontend=frontend"
    )

    # The Ingress names AGC by ID and frontend only.
    (ingress,) = _kind(docs, "Ingress")
    assert ingress["metadata"]["annotations"] == {
        "alb.networking.azure.io/alb-id": "/subscriptions/example/agc",
        "alb.networking.azure.io/alb-frontend": "frontend",
        "alb.networking.azure.io/alb-ingress-extension": FULL_NAME,
    }


# AGC can serve the Ingress only once the Ingress names it and has a
# certificate, which AGC takes from a Secret alone, so the preset refuses to
# render without either rather than leave an Ingress nothing serves.
@pytest.mark.parametrize(
    "extra_args, message",
    [
        (
            "--set agw.ingress.tls.secretName=gw-example-com-tls",
            (
                "'agw.ingress.azureAgc.albName' and 'albNamespace', or 'albId' and "
                "'albFrontend', are required"
            ),
        ),
        (
            (
                "--set agw.ingress.tls.secretName=gw-example-com-tls "
                "--set agw.ingress.azureAgc.albName=alb"
            ),
            "'agw.ingress.azureAgc.albNamespace' is required with 'albName'",
        ),
        (
            (
                "--set agw.ingress.tls.secretName=gw-example-com-tls "
                "--set agw.ingress.azureAgc.albId=/subscriptions/example/agc"
            ),
            "'agw.ingress.azureAgc.albFrontend' is required with 'albId'",
        ),
        (
            (
                "--set agw.ingress.azureAgc.albName=alb "
                "--set agw.ingress.azureAgc.albNamespace=alb-infra"
            ),
            (
                "'agw.ingress.tls.secretName' is required for "
                "'agw.ingress.controller: azure-agc'"
            ),
        ),
    ],
)
def test_azure_agc_preset_requires_agc_and_the_secret(extra_args, message):
    # Render the preset with one required value missing.
    stderr = _template_error(
        "--set agw.ingress.enabled=true --set agw.ingress.controller=azure-agc "
        f"{extra_args}"
    )

    # The error names what is missing.
    assert message in stderr


# The ALB Controller serves only Ingresses of the class azure-alb-external: it
# leaves an Ingress of another class unserved, one of an IngressClass that names
# the controller included. The preset refuses 'className' rather than render an
# Ingress nothing serves.
def test_azure_agc_preset_refuses_a_class_name():
    # Render the preset with a class name.
    stderr = _template_error(f"{AGC} --set agw.ingress.className=agc-edge")

    # The error says why.
    assert (
        "'agw.ingress.className' cannot be used with azure-agc, since the ALB "
        "Controller serves only Ingresses of the class azure-alb-external"
    ) in stderr


# Each object of the preset can be turned off, for a customer who provides it
# another way, and the timeout and the session affinity are taken from the
# values.
def test_azure_agc_preset_objects_can_be_turned_off_and_configured():
    # Render the preset without the HealthCheckPolicy and without the
    # IngressExtension.
    docs = _docs(
        f"{AGC} --set agw.ingress.azureAgc.healthCheckPolicy.enabled=false "
        "--set agw.ingress.azureAgc.ingressExtension.enabled=false"
    )

    # Neither object is rendered, and the Ingress no longer names the
    # IngressExtension.
    assert _kind(docs, "HealthCheckPolicy") == []
    assert _kind(docs, "IngressExtension") == []
    (ingress,) = _kind(docs, "Ingress")
    assert (
        "alb.networking.azure.io/alb-ingress-extension"
        not in (ingress["metadata"]["annotations"])
    )

    # Render the preset with a two hour request timeout and managed cookie
    # affinity.
    docs = _docs(
        f"{AGC} --set agw.ingress.azureAgc.ingressExtension.requestTimeout=2h "
        "--set agw.ingress.azureAgc.ingressExtension.sessionAffinity.affinityType="
        "managed-cookie"
    )

    # The IngressExtension carries both.
    (extension,) = _kind(docs, "IngressExtension")
    (settings,) = extension["spec"]["backendSettings"]
    assert settings["timeouts"] == {"requestTimeout": "2h"}
    assert settings["sessionAffinity"] == {"affinityType": "managed-cookie"}
