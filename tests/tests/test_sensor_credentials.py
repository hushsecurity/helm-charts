import base64
import os
import subprocess
import tempfile
import pytest
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.chart import DUMMY_TOKEN, SENSOR_CHART
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


def test_numeric_credentials_from_set_are_stored_as_given():
    # '--set' turns digits into an int64, which keeps every digit.
    docs = _template(
        f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=12345678"
    )
    (secret,) = [d for d in docs if d.get("kind") == "Secret"]
    assert (
        base64.b64decode(secret["data"]["deployment-password"]).decode() == "12345678"
    )


def test_numeric_credentials_from_a_values_file_fail_the_render():
    # A bare number in a values file arrives as a float: 12345678 would be
    # stored as 1.2345678e+07, so the render refuses it.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "values.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"hushDeployment:\n  token: {DUMMY_TOKEN}\n  password: 12345678\n")
        with pytest.raises(subprocess.CalledProcessError) as e:
            _template(f"-f {path}", trace_err=False)
    assert "'hushDeployment.password' must be a string" in e.value.stderr
