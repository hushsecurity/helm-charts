from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"
NO_CLAIM = "--set agw.persistence.enabled=false"


def _docs(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


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
