import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

GKE = "--set agw.ingress.enabled=true --set agw.ingress.controller=gke-ingress"

FULL_NAME = "release-name-hush-agw"


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _kind(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


# The gke-ingress preset takes GKE Ingress through everything Hush AGW needs:
# the class annotation GKE reads, container-native load balancing to the
# Hush AGW pods, a BackendConfig that health checks the readiness port and
# keeps a response open for 30 minutes, a Google-managed certificate for the
# hostname, and a FrontendConfig that redirects plain HTTP to HTTPS.
def test_gke_ingress_preset_sets_up_the_ingress_and_its_objects():
    # Render the preset with its defaults.
    docs = _docs(GKE)
    (ingress,) = _kind(docs, "Ingress")
    (service,) = _kind(docs, "Service")
    (backend_config,) = _kind(docs, "BackendConfig")
    (certificate,) = _kind(docs, "ManagedCertificate")
    (frontend_config,) = _kind(docs, "FrontendConfig")

    # The Ingress names its class by annotation, which GKE reads, and refers to
    # the certificate and the FrontendConfig.
    assert "ingressClassName" not in ingress["spec"]
    assert ingress["metadata"]["annotations"] == {
        "kubernetes.io/ingress.class": "gce",
        "networking.gke.io/managed-certificates": FULL_NAME,
        "networking.gke.io/v1beta1.FrontendConfig": FULL_NAME,
    }

    # The Service asks for container-native load balancing and refers to the
    # BackendConfig, and stays ClusterIP.
    assert service["metadata"]["annotations"] == {
        "cloud.google.com/neg": '{"ingress":true}',
        "cloud.google.com/backend-config": f'{{"default":"{FULL_NAME}"}}',
    }
    assert service["spec"]["type"] == "ClusterIP"

    # The BackendConfig health checks the readiness port and allows 30 minutes.
    assert backend_config["apiVersion"] == "cloud.google.com/v1"
    assert backend_config["metadata"]["name"] == FULL_NAME
    assert backend_config["spec"] == {
        "timeoutSec": 1800,
        "healthCheck": {
            "type": "HTTP",
            "port": 15021,
            "requestPath": "/healthz/ready",
        },
        "sessionAffinity": {"affinityType": "NONE"},
    }

    # The certificate covers the hostname.
    assert certificate["apiVersion"] == "networking.gke.io/v1"
    assert certificate["metadata"]["name"] == FULL_NAME
    assert certificate["spec"] == {"domains": ["gw.example.com"]}

    # The FrontendConfig redirects plain HTTP to HTTPS and names no SSL policy.
    assert frontend_config["apiVersion"] == "networking.gke.io/v1beta1"
    assert frontend_config["metadata"]["name"] == FULL_NAME
    assert frontend_config["spec"] == {
        "redirectToHttps": {"enabled": True},
        "sslPolicy": "",
    }


# Each object of the preset can be turned off, for a customer who provides it
# another way, and the annotation that refers to it goes with it. Container-
# native load balancing stays, since the Ingress needs it to reach the pods.
def test_gke_ingress_preset_objects_can_be_turned_off():
    # Render the preset with all three objects turned off.
    docs = _docs(
        f"{GKE} --set agw.ingress.gkeIngress.backendConfig.enabled=false "
        "--set agw.ingress.gkeIngress.managedCertificate.enabled=false "
        "--set agw.ingress.gkeIngress.frontendConfig.enabled=false"
    )

    # None of the objects is rendered.
    for kind in ("BackendConfig", "ManagedCertificate", "FrontendConfig"):
        assert _kind(docs, kind) == []

    # Only the class annotation and container-native load balancing remain.
    (ingress,) = _kind(docs, "Ingress")
    assert ingress["metadata"]["annotations"] == {"kubernetes.io/ingress.class": "gce"}
    (service,) = _kind(docs, "Service")
    assert service["metadata"]["annotations"] == {
        "cloud.google.com/neg": '{"ingress":true}'
    }


# The backend timeout, the session affinity and the SSL policy are taken from
# the values. Without them the BackendConfig sets affinity NONE and the
# FrontendConfig an empty policy, since GKE keeps what an earlier
# BackendConfig or FrontendConfig set once the field is left out.
def test_gke_ingress_preset_takes_the_timeout_affinity_and_ssl_policy():
    # Render the preset with a two hour timeout, cookie affinity and an SSL
    # policy.
    docs = _docs(
        f"{GKE} --set agw.ingress.gkeIngress.backendConfig.timeoutSec=7200 "
        "--set agw.ingress.gkeIngress.backendConfig.sessionAffinity.affinityType="
        "GENERATED_COOKIE "
        "--set agw.ingress.gkeIngress.backendConfig.sessionAffinity.affinityCookieTtlSec="
        "86400 "
        "--set agw.ingress.gkeIngress.frontendConfig.sslPolicy=tls-1-2"
    )

    # The BackendConfig carries the timeout and the affinity, and the
    # FrontendConfig the policy.
    (backend_config,) = _kind(docs, "BackendConfig")
    assert backend_config["spec"]["timeoutSec"] == 7200
    assert backend_config["spec"]["sessionAffinity"] == {
        "affinityType": "GENERATED_COOKIE",
        "affinityCookieTtlSec": 86400,
    }
    (frontend_config,) = _kind(docs, "FrontendConfig")
    assert frontend_config["spec"]["sslPolicy"] == "tls-1-2"


# The preset applies to the Ingress the chart creates. With the Ingress turned
# off, the Service is left as it is and no GKE object is rendered, even with
# the controller still set.
def test_gke_ingress_preset_does_nothing_without_the_ingress():
    # Render with the controller set and the Ingress turned off.
    docs = _docs("--set agw.ingress.controller=gke-ingress")

    # No Ingress or GKE object is rendered, and the Service carries no
    # annotations.
    for kind in ("Ingress", "BackendConfig", "ManagedCertificate", "FrontendConfig"):
        assert _kind(docs, kind) == []
    (service,) = _kind(docs, "Service")
    assert "annotations" not in service["metadata"]


# GKE reads the class from the annotation alone: it ignores a class name, and
# the API refuses to create an Ingress whose class name differs from the
# annotation. The preset refuses 'className' rather than render either.
def test_gke_ingress_preset_refuses_a_class_name():
    # Render the preset with a class name.
    stderr = _template_error(f"{GKE} --set agw.ingress.className=gce-internal")

    # The error says why.
    assert (
        "'agw.ingress.className' cannot be used with gke-ingress, which takes the "
        "class from the 'kubernetes.io/ingress.class' annotation"
    ) in stderr
