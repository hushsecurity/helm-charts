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


def _deployment(docs):
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    return deployment


# Without the volume claim an upgrade starts a new Hush AGW pod and stops an
# old one only once the new one is ready, so Hush AGW stays up and keeps its
# capacity throughout.
def test_rollout_starts_a_new_pod_before_stopping_an_old_one():
    # Render the chart with the claim turned off.
    spec = _deployment(_docs(NO_CLAIM))["spec"]

    # One extra pod at a time, and no old pod stopped before its successor is
    # ready.
    assert spec["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
    }


# Two pods cannot share the volume claim, so with the claim, the default, an
# upgrade stops the old pod before it starts the new one.
def test_rollout_with_the_claim_stops_the_old_pod_first():
    # Render the chart with its defaults.
    spec = _deployment(_docs())["spec"]

    # The old pod goes before the new one starts.
    assert spec["strategy"] == {"type": "Recreate"}


# Hush AGW runs one pod unless asked for more.
def test_one_pod_by_default():
    # Render the chart with its defaults.
    spec = _deployment(_docs())["spec"]

    # One pod.
    assert spec["replicas"] == 1


# 'agw.replicas' sets the number of Hush AGW pods.
def test_replicas_set_the_number_of_pods():
    # Render the chart without the claim and with three replicas.
    spec = _deployment(_docs(f"{NO_CLAIM} --set agw.replicas=3"))["spec"]

    # Three pods.
    assert spec["replicas"] == 3


# Hush AGW pods cannot share the volume claim, so the chart refuses more than
# one pod while the claim is on, whether the chart creates it or is given one.
@pytest.mark.parametrize(
    "claim", ["", "--set agw.persistence.existingClaim=my-existing-claim"]
)
def test_several_pods_with_the_claim_are_refused(claim):
    # Render two pods with the claim.
    stderr = _template_error(f"{claim} --set agw.replicas=2")

    # The chart names the setting that allows them.
    assert (
        "'agw.replicas' above 1 needs 'agw.persistence.enabled: false', since "
        "Hush AGW pods cannot share the volume claim"
    ) in stderr


# 'helm upgrade --reuse-values' renders the chart with the values of a release
# made before 'agw.replicas' existed, so the key is missing; a null removes it
# the same way. Such an upgrade keeps one pod.
def test_missing_replicas_keep_one_pod():
    # Render the chart without the key.
    spec = _deployment(_docs("--set agw.replicas=null"))["spec"]

    # One pod.
    assert spec["replicas"] == 1


# Zero or fewer pods would leave no Hush AGW at all, so the chart refuses them.
@pytest.mark.parametrize("replicas", ["0", "-1"])
def test_fewer_than_one_replica_is_refused(replicas):
    # Render the chart with the replica count.
    stderr = _template_error(f"--set agw.replicas={replicas}")

    # The chart names the setting.
    assert "'agw.replicas' must be at least 1" in stderr
