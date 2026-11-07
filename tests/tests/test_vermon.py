import pytest
from common.chart import SENSOR_CHART, template

ENV_NAME = "FALLBACK_RESTART_AGE"


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
