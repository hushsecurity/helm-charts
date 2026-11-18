import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"
NO_CLAIM = "--set agw.persistence.enabled=false"


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _claims(docs):
    return [doc for doc in docs if doc["kind"] == "PersistentVolumeClaim"]


def _data_volume(docs):
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    volumes = deployment["spec"]["template"]["spec"]["volumes"]
    (data,) = [volume for volume in volumes if volume["name"] == "data"]
    return data


EMPTY_DIR = {"name": "data", "emptyDir": {"sizeLimit": "1Gi"}}


# The deprecated volume claim stays the default, so that an upgrade leaves the
# volume of an existing installation as it is.
def test_data_volume_is_the_claim_by_default():
    # Render the chart with its defaults.
    docs = _docs()

    # The chart renders its claim, and the data volume mounts it.
    (claim,) = _claims(docs)
    assert _data_volume(docs) == {
        "name": "data",
        "persistentVolumeClaim": {"claimName": claim["metadata"]["name"]},
    }


# Without the claim each pod rebuilds its state from Hush on an emptyDir of its
# own, bounded at the default size of the claim, so that it cannot fill the
# node's disk.
def test_data_volume_without_the_claim_is_a_bounded_empty_dir():
    # Render the chart with the claim turned off.
    docs = _docs(NO_CLAIM)

    # No claim is rendered, and the data volume is an emptyDir of 1Gi.
    assert not _claims(docs)
    assert _data_volume(docs) == EMPTY_DIR


# 'agw.dataVolume.size' sets the bound.
def test_data_volume_takes_its_size():
    # Render the chart without the claim and with a volume of 512Mi.
    docs = _docs(f"{NO_CLAIM} --set agw.dataVolume.size=512Mi")

    # The emptyDir is bounded at 512Mi.
    assert _data_volume(docs) == {"name": "data", "emptyDir": {"sizeLimit": "512Mi"}}


# 'helm upgrade --reuse-values' from a release made before the data volume
# settings existed carries no 'agw.dataVolume'; a null removes it the same way.
# The volume keeps its default size.
def test_missing_data_volume_values_keep_the_default_size():
    # Render the chart without the claim and without the key.
    docs = _docs(f"{NO_CLAIM} --set agw.dataVolume=null")

    # The emptyDir is bounded at 1Gi.
    assert _data_volume(docs) == EMPTY_DIR


REQUEST = "agw.controller.resources.requests.ephemeral-storage"

REQUEST_TOO_LOW = (
    "'agw.controller.resources.requests.ephemeral-storage' must be at least "
    "'agw.dataVolume.size' ({size}), to reserve the node's disk the data volume "
    "takes"
)

LIMITS_TOO_LOW = (
    "the ephemeral-storage limits of 'agw.controller', 'agw.agentgateway', "
    "'agw.vector' and 'agw.genaiToolbox' must add up to more than "
    "'agw.dataVolume.size' ({size}), or the pod is evicted before its data "
    "volume is full"
)

NO_LIMITS = " ".join(
    f"--set agw.{name}.resources.limits.ephemeral-storage=null"
    for name in ["controller", "agentgateway", "vector", "genaiToolbox"]
)


# The scheduler reserves no node disk for an emptyDir, only what the containers
# request, so a volume larger than the agw-controller's request could land on a
# node without room for it.
def test_request_below_the_size_is_refused():
    # Render the chart without the claim, with a volume of 2Gi and the default
    # request of 1Gi.
    stderr = _template_error(f"{NO_CLAIM} --set agw.dataVolume.size=2Gi")

    # The chart names the request to raise.
    assert REQUEST_TOO_LOW.format(size="2Gi") in stderr


# A request raised along with the size covers the volume.
def test_request_raised_with_the_size():
    # Render the chart without the claim, with a volume and a request of 2Gi.
    docs = _docs(f"{NO_CLAIM} --set agw.dataVolume.size=2Gi --set {REQUEST}=2Gi")

    # The emptyDir is bounded at 2Gi.
    assert _data_volume(docs) == {"name": "data", "emptyDir": {"sizeLimit": "2Gi"}}


# Kubernetes takes the limit for a request that is not set, so the 1Gi limit of
# the agw-controller covers the default volume.
def test_missing_request_falls_back_to_the_limit():
    # Render the chart without the claim and without the request.
    docs = _docs(f"{NO_CLAIM} --set {REQUEST}=null")

    # The emptyDir is rendered.
    assert _data_volume(docs) == EMPTY_DIR


# The kubelet evicts a pod whose disk use, its emptyDir included, passes the
# sum of its containers' limits, 4Gi by default. A volume that large would get
# the pod evicted before it fills.
def test_limits_not_above_the_size_are_refused():
    # Render the chart without the claim, with a volume and a request of 4Gi.
    stderr = _template_error(
        f"{NO_CLAIM} --set agw.dataVolume.size=4Gi --set {REQUEST}=4Gi"
    )

    # The chart names the limits to raise.
    assert LIMITS_TOO_LOW.format(size="4Gi") in stderr


# Without any limit the kubelet does not limit the pod's disk use, so a volume
# of any size fits.
def test_no_limits_fit_any_size():
    # Render the chart without the claim and without limits, with a volume and
    # a request of 4Gi.
    docs = _docs(
        f"{NO_CLAIM} {NO_LIMITS} --set agw.dataVolume.size=4Gi --set {REQUEST}=4Gi"
    )

    # The emptyDir is bounded at 4Gi.
    assert _data_volume(docs) == {"name": "data", "emptyDir": {"sizeLimit": "4Gi"}}


# Sizes are compared in bytes, whatever the units they are written in.
@pytest.mark.parametrize(
    "size,request_,fits",
    [
        # 2G is 2000000000 bytes, more than 1536Mi.
        ("1536Mi", "2G", True),
        # 1907Mi is 1999634432 bytes, less than 2G.
        ("2G", "1907Mi", False),
        # A plain number is bytes: 1.5Gi exactly.
        ("1.5Gi", "1610612736", True),
        # A decimal exponent: 2e9 is 2G.
        ("1.5Gi", "2e9", True),
        # A bare E is exa, not an exponent: 1E is 10^18 bytes.
        ("1Gi", "1E", True),
    ],
)
def test_sizes_are_compared_in_bytes(size, request_, fits):
    # Render the chart without the claim, with the size and the request.
    args = f"{NO_CLAIM} --set agw.dataVolume.size={size} --set {REQUEST}={request_}"

    # The volume fits only when the request is at least as large.
    if fits:
        assert _data_volume(_docs(args))["emptyDir"]["sizeLimit"] == size
    else:
        assert REQUEST_TOO_LOW.format(size=size) in _template_error(args)


# A size that is no quantity cannot be compared.
def test_size_must_be_a_quantity():
    # Render the chart without the claim and with a size that is no quantity.
    stderr = _template_error(f"{NO_CLAIM} --set agw.dataVolume.size=lots")

    # The chart names the setting.
    assert (
        "'agw.dataVolume.size' must be a quantity such as 1Gi or 512Mi, not \"lots\""
    ) in stderr


# The volume claim keeps the data off the node's disk, so the size is not
# checked against the containers' resources.
def test_size_is_not_checked_with_the_claim():
    # Render the chart with the claim and a size above the request and limits.
    docs = _docs("--set agw.dataVolume.size=5Gi")

    # The claim is mounted.
    assert "persistentVolumeClaim" in _data_volume(docs)


# 'ephemeral' gives each pod a volume of its own from a StorageClass, through a
# claim created with the pod and deleted with it, so that the pod gets the
# capacity and IOPS of the class rather than a share of the node's disk.
def test_ephemeral_data_volume_takes_its_class_and_size():
    # Render the chart without the claim and with a 2Gi volume of the gp3
    # class.
    docs = _docs(
        f"{NO_CLAIM} --set agw.dataVolume.type=ephemeral "
        "--set agw.dataVolume.storageClassName=gp3 "
        "--set agw.dataVolume.size=2Gi"
    )

    # The chart renders no claim of its own; the pod carries the claim's
    # template, labelled as the data volume claim of Hush AGW.
    assert not _claims(docs)
    template = _data_volume(docs)["ephemeral"]["volumeClaimTemplate"]
    labels = template["metadata"]["labels"]
    assert labels["app.kubernetes.io/component"] == "gateway-data-volume-claim"
    assert template["spec"] == {
        "accessModes": ["ReadWriteOnce"],
        "storageClassName": "gp3",
        "resources": {"requests": {"storage": "2Gi"}},
    }


# Without a class the claim names none, so that the cluster's default
# StorageClass provides the volume.
def test_ephemeral_data_volume_defaults_to_the_cluster_class():
    # Render the chart without the claim and with an ephemeral volume and no
    # class.
    docs = _docs(f"{NO_CLAIM} --set agw.dataVolume.type=ephemeral")

    # The claim names no class and asks for 1Gi.
    spec = _data_volume(docs)["ephemeral"]["volumeClaimTemplate"]["spec"]
    assert "storageClassName" not in spec
    assert spec["resources"] == {"requests": {"storage": "1Gi"}}


# Any other type is refused.
def test_unknown_data_volume_type_is_refused():
    # Render the chart without the claim and with a type the chart does not
    # know.
    stderr = _template_error(
        f"{NO_CLAIM} --set agw.dataVolume.type=persistentVolumeClaim"
    )

    # The chart names the setting and the types it takes.
    assert "'agw.dataVolume.type' must be emptyDir or ephemeral" in stderr


# A volume from a StorageClass keeps the data off the node's disk, so its size
# is not checked against the containers' resources.
def test_ephemeral_data_volume_size_is_not_checked():
    # Render the chart without the claim and with an ephemeral volume above the
    # request and limits.
    docs = _docs(
        f"{NO_CLAIM} --set agw.dataVolume.type=ephemeral --set agw.dataVolume.size=5Gi"
    )

    # The claim's template asks for the size.
    spec = _data_volume(docs)["ephemeral"]["volumeClaimTemplate"]["spec"]
    assert spec["resources"] == {"requests": {"storage": "5Gi"}}
