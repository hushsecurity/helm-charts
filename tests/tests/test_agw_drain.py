import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

NO_CLAIM = "--set agw.persistence.enabled=false"

SIDECARS = ["agw-controller", "agw-vector", "agw-genai-toolbox"]


def _pod(extra_args="", claim=False):
    claim_args = "" if claim else NO_CLAIM
    docs = _template(f"{AGW_BASE} {claim_args} {extra_args}", chart=AGW_CHART)
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    pod = deployment["spec"]["template"]["spec"]
    containers = {c["name"]: c for c in pod["containers"]}
    return pod, containers


def _drain_env(container):
    return {
        e["name"]: e["value"]
        for e in container["env"]
        if e["name"].startswith("CONNECTION_")
    }


# Without the volume claim a stopping pod has two and a half minutes by
# default: agentgateway accepts connections for 30 seconds while the load
# balancer stops sending them, and finishes the requests in flight for up to
# two minutes, while the other containers keep serving it for 130 seconds
# before they get SIGTERM.
def test_default_drain():
    # Render the chart on a Kubernetes that runs the sleep action.
    pod, containers = _pod("--kube-version 1.30.0")

    # The grace period covers the whole drain.
    assert pod["terminationGracePeriodSeconds"] == 150

    # agentgateway keeps accepting for 30 seconds and drains for 120.
    assert _drain_env(containers["agw-agentgateway"]) == {
        "CONNECTION_MIN_TERMINATION_DEADLINE": "30s",
        "CONNECTION_TERMINATION_DEADLINE": "120s",
    }
    assert "lifecycle" not in containers["agw-agentgateway"]

    # The other containers outlive the drain by ten seconds.
    for name in SIDECARS:
        assert containers[name]["lifecycle"] == {"preStop": {"sleep": {"seconds": 130}}}


# Every timing follows the grace period.
def test_drain_follows_the_grace_period():
    # Render the chart with five minutes to stop.
    pod, containers = _pod(
        "--kube-version 1.30.0 --set agw.terminationGracePeriodSeconds=300"
    )

    # agentgateway drains until 30 seconds before the end, and the other
    # containers stay up until 20 seconds before it.
    assert pod["terminationGracePeriodSeconds"] == 300
    env = _drain_env(containers["agw-agentgateway"])
    assert env["CONNECTION_TERMINATION_DEADLINE"] == "270s"
    for name in SIDECARS:
        assert containers[name]["lifecycle"]["preStop"]["sleep"]["seconds"] == 280


# The shortest grace period that drains: agentgateway accepts for its first 30
# seconds and cuts what is left at the same time, and the other containers
# stay up for 40 seconds.
def test_drain_at_sixty_seconds():
    # Render the chart with one minute to stop.
    _, containers = _pod(
        "--kube-version 1.30.0 --set agw.terminationGracePeriodSeconds=60"
    )

    # Both deadlines fall at 30 seconds, and the sleep lasts 40.
    assert _drain_env(containers["agw-agentgateway"]) == {
        "CONNECTION_MIN_TERMINATION_DEADLINE": "30s",
        "CONNECTION_TERMINATION_DEADLINE": "30s",
    }
    for name in SIDECARS:
        assert containers[name]["lifecycle"]["preStop"]["sleep"]["seconds"] == 40


# Managed clusters report versions with a suffix, which semver reads as a
# prerelease of the version, so 1.30 and later get the sleep whatever the
# suffix.
@pytest.mark.parametrize(
    "kube_version", ["1.30.0", "1.30.2-gke.1146000", "1.31.4-eks-2d5f260"]
)
def test_sleep_from_kubernetes_1_30(kube_version):
    # Render the chart on the version.
    _, containers = _pod(f"--kube-version {kube_version}")

    # Every container but agentgateway sleeps before it stops.
    for name in SIDECARS:
        assert containers[name]["lifecycle"]["preStop"]["sleep"]["seconds"] == 130


# Kubernetes turns the sleep action on by default from 1.30 on, so earlier
# versions get agentgateway's drain only, and the other containers stop at once.
@pytest.mark.parametrize("kube_version", ["1.29.0", "1.29.10-eks-7f9249a"])
def test_no_sleep_before_kubernetes_1_30(kube_version):
    # Render the chart on the version.
    _, containers = _pod(f"--kube-version {kube_version}")

    # agentgateway still drains.
    assert _drain_env(containers["agw-agentgateway"]) == {
        "CONNECTION_MIN_TERMINATION_DEADLINE": "30s",
        "CONNECTION_TERMINATION_DEADLINE": "120s",
    }

    # No container has a preStop hook.
    for name in SIDECARS:
        assert "lifecycle" not in containers[name]


# A grace period below a minute leaves no room for the drain. 'helm upgrade
# --reuse-values' carries the former default of 30 from an earlier release, and
# such a pod stops as it did before.
@pytest.mark.parametrize("grace", ["30", "59"])
def test_short_grace_period_has_no_drain(grace):
    # Render the chart with the short grace period.
    pod, containers = _pod(
        f"--kube-version 1.30.0 --set agw.terminationGracePeriodSeconds={grace}"
    )

    # The grace period is kept, and nothing drains.
    assert pod["terminationGracePeriodSeconds"] == int(grace)
    assert _drain_env(containers["agw-agentgateway"]) == {}
    for name in SIDECARS:
        assert "lifecycle" not in containers[name]


# With the volume claim the new pod of an upgrade starts only once the old one
# is gone, so a drain would only keep Hush AGW down longer, and none is
# rendered.
def test_no_drain_with_the_claim():
    # Render the chart with the claim, as by default, on a Kubernetes that runs
    # the sleep action.
    pod, containers = _pod("--kube-version 1.30.0", claim=True)

    # The grace period is kept, and nothing drains.
    assert pod["terminationGracePeriodSeconds"] == 150
    assert _drain_env(containers["agw-agentgateway"]) == {}
    for name in SIDECARS:
        assert "lifecycle" not in containers[name]
