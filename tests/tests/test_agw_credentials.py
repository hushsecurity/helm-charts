import base64
import os
import shutil
import subprocess
import tempfile
import pytest
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.chart import AGW_CHART, DUMMY_TOKEN
from common.process import bash

CI_DIR = os.path.join(AGW_CHART, "ci")
# The Secret a sensor release called 'hush-sensor' creates, the chart's default.
SENSOR_SECRET = "hush-sensor-deploymentsecret"
CREDENTIALS = (
    f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
)


def _template(extra_args="", values_file=None, trace_err=True):
    args = "--set agw.hostname=gw.example.com " + extra_args
    if values_file:
        args += f" -f {os.path.join(CI_DIR, values_file)}"
    out = bash(f"helm template hush-agw {args} {AGW_CHART}", traceErr=trace_err)
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _of_kind(docs, kind):
    return [d for d in docs if d.get("kind") == kind]


def _identity_containers(docs):
    # The controller (init and server) and the vector sidecar identify
    # themselves to the platform; the agentgateway and toolbox containers do not.
    (deployment,) = _of_kind(docs, "Deployment")
    spec = deployment["spec"]["template"]["spec"]
    containers = [
        c
        for c in spec.get("initContainers", []) + spec["containers"]
        if any(e["name"] == "DEPLOYMENT_TOKEN" for e in c.get("env", []))
    ]
    assert sorted(c["name"] for c in containers) == [
        "agw-controller",
        "agw-controller-init",
        "agw-vector",
    ]
    return containers


def _secret_ref(container, name):
    (entry,) = [e for e in container.get("env", []) if e["name"] == name]
    ref = entry["valueFrom"]["secretKeyRef"]
    return ref["name"], ref["key"]


def _has_env(container, name):
    return any(e["name"] == name for e in container.get("env", []))


def test_explicit_credentials_create_the_deployment_secret():
    docs = _template(CREDENTIALS, values_file="auth-mode-password-values.yaml")
    (secret,) = _of_kind(docs, "Secret")
    assert secret["metadata"]["name"] == "hush-agw-deploymentsecret"
    assert sorted(secret["data"]) == ["deployment-password", "deployment-token"]
    for container in _identity_containers(docs):
        assert _secret_ref(container, "DEPLOYMENT_TOKEN") == (
            "hush-agw-deploymentsecret",
            "deployment-token",
        )
        assert _secret_ref(container, "DEPLOYMENT_PASSWORD") == (
            "hush-agw-deploymentsecret",
            "deployment-password",
        )


def test_without_credentials_the_sensor_secret_is_used():
    docs = _template()
    assert _of_kind(docs, "Secret") == []
    for container in _identity_containers(docs):
        assert _secret_ref(container, "DEPLOYMENT_TOKEN") == (
            SENSOR_SECRET,
            "deployment-token",
        )
        assert _secret_ref(container, "DEPLOYMENT_PASSWORD") == (
            SENSOR_SECRET,
            "deployment-password",
        )


def test_token_and_password_fall_back_independently():
    # Only the token is given: it is stored in the chart's Secret and the
    # password keeps coming from the sensor's.
    docs = _template(f"--set hushDeployment.token={DUMMY_TOKEN}")
    (secret,) = _of_kind(docs, "Secret")
    assert list(secret["data"]) == ["deployment-token"]
    for container in _identity_containers(docs):
        assert (
            _secret_ref(container, "DEPLOYMENT_TOKEN")[0] == "hush-agw-deploymentsecret"
        )
        assert _secret_ref(container, "DEPLOYMENT_PASSWORD")[0] == SENSOR_SECRET


def test_without_a_sensor_secret_name_credentials_are_required():
    with pytest.raises(subprocess.CalledProcessError) as e:
        _template("--set hushDeployment.sensorDeploymentSecretName=", trace_err=False)
    assert "'hushDeployment.token' is undefined" in e.value.stderr


def test_pre_existing_secret_wins_over_inline_credentials():
    # A values block carried over with a stale inline token must not win over
    # a pre-created Secret added later, and the stale value must not be stored.
    docs = _template(
        CREDENTIALS, values_file="pre-existing-deployment-secret-values.yaml"
    )
    assert _of_kind(docs, "Secret") == []
    for container in _identity_containers(docs):
        assert _secret_ref(container, "DEPLOYMENT_TOKEN") == (
            "my-deployment-secret",
            "deployment-token",
        )
        assert _secret_ref(container, "DEPLOYMENT_PASSWORD") == (
            "my-deployment-secret",
            "deployment-password",
        )


def test_oidc_stores_no_password():
    docs = _template(
        "--set hushDeployment.password=stale", values_file="auth-mode-oidc-values.yaml"
    )
    (secret,) = _of_kind(docs, "Secret")
    assert list(secret["data"]) == ["deployment-token"]
    for container in _identity_containers(docs):
        assert not _has_env(container, "DEPLOYMENT_PASSWORD")
        assert _has_env(container, "HUSH_K8S_SA_TOKEN_PATH")


def test_the_fallback_survives_an_alias():
    # Under an umbrella chart with 'alias', .Chart.Name is the alias. The
    # fallback is declared by a Chart.yaml annotation, so it still applies.
    with tempfile.TemporaryDirectory() as tmp:
        umbrella = os.path.join(tmp, "umbrella")
        os.makedirs(os.path.join(umbrella, "charts"))
        shutil.copytree(AGW_CHART, os.path.join(umbrella, "charts", "gateway"))
        with open(os.path.join(umbrella, "Chart.yaml"), "w", encoding="utf-8") as f:
            f.write(
                "apiVersion: v2\nname: umbrella\nversion: 0.1.0\n"
                "dependencies:\n  - name: hush-agw\n    version: '*'\n"
                "    alias: gateway\n    repository: file://charts/gateway\n"
            )
        out = bash(
            f"helm template umbrella --set gateway.agw.hostname=gw.example.com {umbrella}"
        )
    docs = [doc for doc in load_all(out, Loader=Loader) if doc]
    for container in _identity_containers(docs):
        assert _secret_ref(container, "DEPLOYMENT_TOKEN")[0] == SENSOR_SECRET


def test_numeric_credentials_from_set_are_stored_as_given():
    docs = _template(
        f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=12345678"
    )
    (secret,) = _of_kind(docs, "Secret")
    assert (
        base64.b64decode(secret["data"]["deployment-password"]).decode() == "12345678"
    )


def test_numeric_credentials_from_a_values_file_fail_the_render():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "values.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"hushDeployment:\n  token: {DUMMY_TOKEN}\n  password: 12345678\n")
        with pytest.raises(subprocess.CalledProcessError) as e:
            _template(f"-f {path}", trace_err=False)
    assert "'hushDeployment.password' must be a string" in e.value.stderr
