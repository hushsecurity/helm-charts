import pytest
from common.chart import CONNECTOR_CHART, SENSOR_CHART, template

ENV_NAME = "FALLBACK_RESTART_AGE"
MANAGED_LABEL = "hush.security/vermon-managed"
WORKLOADS = ("Deployment", "DaemonSet")


def _vermon_env(extra_args=""):
    docs = template(extra_args, chart=SENSOR_CHART)
    containers = [
        c
        for d in docs
        if d.get("kind") == "Deployment"
        for c in d["spec"]["template"]["spec"]["containers"]
        if c["name"] == "hush-vermon"
    ]
    assert len(containers) == 1
    return {e["name"]: e.get("value") for e in containers[0]["env"]}


def test_fallback_restart_age_default():
    assert _vermon_env()[ENV_NAME] == "240h"


@pytest.mark.parametrize(
    "extra_args, expected",
    [
        ("--set vermon.fallbackRestartAge=72h", "72h"),
        # A bare 0 is a number; env values must be strings.
        ("--set vermon.fallbackRestartAge=0", "0"),
        ("--set-string vermon.fallbackRestartAge=0", "0"),
    ],
)
def test_fallback_restart_age_override(extra_args, expected):
    assert _vermon_env(extra_args)[ENV_NAME] == expected


@pytest.mark.parametrize(
    "chart, extra_args, expected",
    [
        (
            SENSOR_CHART,
            "--set connector.enabled=true",
            {
                "release-name-hush-sensor",
                "release-name-hush-sensor-connector",
                "release-name-hush-sensor-sentry",
                "release-name-hush-sensor-vermon",
            },
        ),
        (CONNECTOR_CHART, "", {"release-name-hush-connector"}),
    ],
)
def test_vermon_managed_pod_label(chart, extra_args, expected):
    workloads = [
        d for d in template(extra_args, chart=chart) if d.get("kind") in WORKLOADS
    ]
    assert {d["metadata"]["name"] for d in workloads} == expected
    for d in workloads:
        assert d["spec"]["template"]["metadata"]["labels"][MANAGED_LABEL] == "true"
        # Selectors are immutable, so the label must stay out of them.
        assert MANAGED_LABEL not in d["spec"]["selector"]["matchLabels"]
