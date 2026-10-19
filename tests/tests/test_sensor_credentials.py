import subprocess
import pytest
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.chart import SENSOR_CHART
from common.process import bash


def _template(extra_args="", trace_err=True):
    out = bash(
        f"helm template hush-sensor {extra_args} {SENSOR_CHART}", traceErr=trace_err
    )
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def test_a_stray_sensor_fallback_name_is_ignored():
    # The chart offers no 'hushDeployment.sensorDeploymentSecretName'. One
    # carried over from a hush-am or hush-agw values file must not switch the
    # sensor-Secret fallback on: with no token the render still fails.
    with pytest.raises(subprocess.CalledProcessError) as e:
        _template(
            "--set hushDeployment.sensorDeploymentSecretName=hush-sensor-deploymentsecret",
            trace_err=False,
        )
    assert "'hushDeployment.token' is undefined" in e.value.stderr
