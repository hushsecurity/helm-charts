from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

LOAD_BALANCER = (
    "--set agw.service.type=LoadBalancer "
    "--set agw.service.port=443 "
    "--set agw.service.loadBalancerClass=service.k8s.aws/nlb "
    "--set agw.service.loadBalancerSourceRanges={10.0.0.0/8} "
    "--set-string agw.service.annotations.example\\\\.com/tls-ports=443"
)


def _service(extra_args=""):
    docs = _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)
    (service,) = [doc for doc in docs if doc["kind"] == "Service"]
    return service


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

    # It listens on 3001 and forwards to the gateway port.
    assert spec["ports"] == [{"name": "gateway", "port": 3001, "targetPort": "gateway"}]


# A LoadBalancer Service listens on the port it is given, carries the
# annotations a cloud load balancer is configured through, and takes the class
# and the client ranges.
def test_load_balancer_service_takes_its_port_annotations_class_and_ranges():
    # Render a LoadBalancer on 443 with every load balancer setting given.
    service = _service(LOAD_BALANCER)

    # The annotations are passed through as given.
    assert service["metadata"]["annotations"] == {"example.com/tls-ports": "443"}

    # The type, the class and the ranges are set.
    spec = service["spec"]
    assert spec["type"] == "LoadBalancer"
    assert spec["loadBalancerClass"] == "service.k8s.aws/nlb"
    assert spec["loadBalancerSourceRanges"] == ["10.0.0.0/8"]

    # It listens on 443 and still forwards to the gateway port.
    assert spec["ports"] == [{"name": "gateway", "port": 443, "targetPort": "gateway"}]


# A LoadBalancer given no class and no client ranges leaves both to the
# cluster's defaults rather than rendering them empty.
def test_load_balancer_without_class_or_ranges_renders_neither():
    # Render a LoadBalancer with only the type and the port given.
    service = _service("--set agw.service.type=LoadBalancer --set agw.service.port=443")

    # The type is LoadBalancer, and neither the class nor the ranges are set.
    spec = service["spec"]
    assert spec["type"] == "LoadBalancer"
    assert "loadBalancerClass" not in spec
    assert "loadBalancerSourceRanges" not in spec


# The class and the client ranges are load balancer settings. Left set when the
# type changes away from LoadBalancer, they are dropped rather than rendered,
# since the API refuses a class on any other type.
def test_load_balancer_settings_are_dropped_for_other_types():
    # Render a NodePort with the load balancer settings still given.
    service = _service(f"{LOAD_BALANCER} --set agw.service.type=NodePort")

    # The type is NodePort, and the class and the ranges are left out.
    spec = service["spec"]
    assert spec["type"] == "NodePort"
    assert "loadBalancerClass" not in spec
    assert "loadBalancerSourceRanges" not in spec
