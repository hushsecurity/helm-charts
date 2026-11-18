from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"
NO_CLAIM = "--set agw.persistence.enabled=false"


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


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
