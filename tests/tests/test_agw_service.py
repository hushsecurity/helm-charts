import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

LOAD_BALANCER = (
    "--set agw.service.type=LoadBalancer "
    "--set agw.service.loadBalancerClass=service.k8s.aws/nlb "
    "--set agw.service.loadBalancerSourceRanges={10.0.0.0/8} "
    "--set-string agw.service.annotations.example\\\\.com/tls-ports=443"
)


def _service(extra_args=""):
    docs = _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)
    (service,) = [doc for doc in docs if doc["kind"] == "Service"]
    return service


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


# The defaults render the Service every installation already has: ClusterIP on
# 3001, so an edge bound to that port by hand keeps working after an upgrade.
def test_default_service_is_cluster_ip_on_the_gateway_port():
    # Render the chart with its defaults.
    service = _service()

    # The Service is ClusterIP, carries no annotations, and nothing that only a
    # load balancer reads.
    assert "annotations" not in service["metadata"]
    spec = service["spec"]
    assert spec["type"] == "ClusterIP"
    assert "loadBalancerClass" not in spec
    assert "loadBalancerSourceRanges" not in spec

    # It listens on 3001 and forwards to the container port.
    assert spec["ports"] == [
        {"name": "gateway", "port": 3001, "targetPort": "gateway-http"}
    ]


# A LoadBalancer Service listens on 443, the port the https URL of Hush AGW
# names, carries the annotations a cloud load balancer is configured through,
# and takes the class and the client ranges.
def test_load_balancer_service_listens_on_443_and_takes_its_settings():
    # Render a LoadBalancer with every load balancer setting given.
    service = _service(LOAD_BALANCER)

    # The annotations are passed through as given.
    assert service["metadata"]["annotations"] == {"example.com/tls-ports": "443"}

    # The type, the class and the ranges are set.
    spec = service["spec"]
    assert spec["type"] == "LoadBalancer"
    assert spec["loadBalancerClass"] == "service.k8s.aws/nlb"
    assert spec["loadBalancerSourceRanges"] == ["10.0.0.0/8"]

    # It listens on 443 and still forwards to the container port.
    assert spec["ports"] == [
        {"name": "gateway", "port": 443, "targetPort": "gateway-http"}
    ]


# A LoadBalancer given no class and no client ranges leaves both to the
# cluster's defaults rather than rendering them empty.
def test_load_balancer_without_class_or_ranges_renders_neither():
    # Render a LoadBalancer with only the type given.
    service = _service("--set agw.service.type=LoadBalancer")

    # The type is LoadBalancer, and neither the class nor the ranges are set.
    spec = service["spec"]
    assert spec["type"] == "LoadBalancer"
    assert "loadBalancerClass" not in spec
    assert "loadBalancerSourceRanges" not in spec


# The class and the client ranges are load balancer settings. Left set when the
# type goes back to ClusterIP, they are dropped rather than rendered, since the
# API refuses a class on any other type.
def test_load_balancer_settings_are_dropped_for_cluster_ip():
    # Render a ClusterIP with the load balancer settings still given.
    service = _service(f"{LOAD_BALANCER} --set agw.service.type=ClusterIP")

    # The type is ClusterIP, and the class and the ranges are left out.
    spec = service["spec"]
    assert spec["type"] == "ClusterIP"
    assert "loadBalancerClass" not in spec
    assert "loadBalancerSourceRanges" not in spec


# No edge of Hush AGW needs a NodePort: an ingress controller reaches it
# through a ClusterIP Service, and a load balancer that terminates TLS through
# a LoadBalancer one. The chart refuses it, as it does every type other than
# ClusterIP and LoadBalancer.
@pytest.mark.parametrize("service_type", ["NodePort", "ExternalName"])
def test_other_service_types_are_refused(service_type):
    # Render with the type set.
    stderr = _template_error(f"--set agw.service.type={service_type}")

    # The error names the types that are accepted.
    assert "'agw.service.type' must be ClusterIP or LoadBalancer" in stderr
