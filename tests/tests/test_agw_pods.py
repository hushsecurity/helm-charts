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


# Several pods need the volume claim off, so the spreading is rendered without
# it.
def _spread(extra_args=""):
    spec = _deployment(_docs(f"{NO_CLAIM} {extra_args}"))["spec"]
    return spec["template"]["spec"].get("topologySpreadConstraints"), spec


# One pod has nothing to spread, so it gets no constraints.
def test_one_pod_is_not_spread():
    # Render the chart with its defaults.
    spread, _ = _spread()

    # No constraints.
    assert spread is None


# Several pods spread across zones and across the nodes of each zone by
# default, so that losing a zone or a node leaves Hush AGW pods running. A
# zone constraint alone would turn off the scheduler's own spreading across
# nodes.
def test_several_pods_spread_across_zones_and_nodes():
    # Render three pods with the default spreading.
    spread, spec = _spread("--set agw.replicas=3")

    # One constraint per zone and per node, each satisfied as well as the
    # scheduler can and each selecting the Hush AGW pods of the same rollout,
    # so that the old pods of an upgrade do not skew where the new ones go.
    assert [c["topologyKey"] for c in spread] == [
        "topology.kubernetes.io/zone",
        "kubernetes.io/hostname",
    ]
    for constraint in spread:
        assert constraint["maxSkew"] == 1
        assert constraint["whenUnsatisfiable"] == "ScheduleAnyway"
        assert constraint["labelSelector"] == spec["selector"]
        assert constraint["matchLabelKeys"] == ["pod-template-hash"]


# 'zones' spreads across zones only, and 'whenUnsatisfiable' is passed on.
def test_zones_spread_takes_when_unsatisfiable():
    # Render two pods spread across zones, never scheduled against it.
    spread, _ = _spread(
        "--set agw.replicas=2 "
        "--set agw.topologySpreadConstraints.type=zones "
        "--set agw.topologySpreadConstraints.whenUnsatisfiable=DoNotSchedule"
    )

    # One zone constraint that leaves a pod pending rather than break it.
    assert [(c["topologyKey"], c["whenUnsatisfiable"]) for c in spread] == [
        ("topology.kubernetes.io/zone", "DoNotSchedule")
    ]


# 'nodes' spreads across nodes only, for a cluster whose nodes carry no zone
# label, on which a zone constraint would spread nothing.
def test_nodes_spread_across_nodes_only():
    # Render two pods spread across nodes.
    spread, _ = _spread(
        "--set agw.replicas=2 --set agw.topologySpreadConstraints.type=nodes"
    )

    # One node constraint.
    assert [c["topologyKey"] for c in spread] == ["kubernetes.io/hostname"]


# 'none' leaves the spreading to the scheduler's defaults.
def test_none_renders_no_constraints():
    # Render two pods without spreading.
    spread, _ = _spread(
        "--set agw.replicas=2 --set agw.topologySpreadConstraints.type=none"
    )

    # No constraints.
    assert spread is None


# 'custom' renders the constraints given, as they are.
def test_custom_constraints_are_used_as_given():
    # Render two pods with one constraint of their own.
    spread, _ = _spread(
        "--set agw.replicas=2 "
        "--set agw.topologySpreadConstraints.type=custom "
        "--set agw.topologySpreadConstraints.custom[0].maxSkew=2 "
        "--set agw.topologySpreadConstraints.custom[0].topologyKey=example.com/rack "
        "--set agw.topologySpreadConstraints.custom[0].whenUnsatisfiable=DoNotSchedule"
    )

    # The constraint is rendered unchanged.
    assert spread == [
        {
            "maxSkew": 2,
            "topologyKey": "example.com/rack",
            "whenUnsatisfiable": "DoNotSchedule",
        }
    ]


# 'helm upgrade --reuse-values' from a release made before the spreading
# existed carries no 'agw.topologySpreadConstraints'; a null removes it the
# same way. The defaults apply.
def test_missing_spread_values_spread_across_zones_and_nodes():
    # Render two pods without the key.
    spread, _ = _spread("--set agw.replicas=2 --set agw.topologySpreadConstraints=null")

    # The default zone and node constraints.
    assert [c["topologyKey"] for c in spread] == [
        "topology.kubernetes.io/zone",
        "kubernetes.io/hostname",
    ]


# A wrong type, a wrong policy or an empty custom list is refused, even with
# one pod, so that the mistake shows before a second pod is added.
@pytest.mark.parametrize(
    "extra_args,message",
    [
        (
            "--set agw.topologySpreadConstraints.type=regions",
            "'agw.topologySpreadConstraints.type' must be one of",
        ),
        (
            "--set agw.topologySpreadConstraints.whenUnsatisfiable=Never",
            "'agw.topologySpreadConstraints.whenUnsatisfiable' must be one of",
        ),
        (
            "--set agw.topologySpreadConstraints.type=custom",
            "'agw.topologySpreadConstraints.custom' must not be empty",
        ),
    ],
)
def test_wrong_spread_values_are_refused(extra_args, message):
    # Render one pod with the wrong value.
    stderr = _template_error(extra_args)

    # The chart names the setting.
    assert message in stderr
