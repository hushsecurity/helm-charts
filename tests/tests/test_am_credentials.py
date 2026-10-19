import os
import subprocess
import pytest
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.chart import AM_CHART, DUMMY_TOKEN
from common.process import bash

CI_DIR = os.path.join(AM_CHART, "ci")
CREDENTIALS = (
    f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
)
# The Secret a sensor release called 'hush-sensor' creates, the chart's default.
SENSOR_SECRET = "hush-sensor-deploymentsecret"
# Containers that authenticate without the deployment password.
WITHOUT_PASSWORD = {"spire-agent", "spire-server", "admission-controller"}


def _template(extra_args="", values_file=None, trace_err=True):
    args = extra_args
    if values_file:
        args += f" -f {os.path.join(CI_DIR, values_file)}"
    out = bash(f"helm template hush-am {args} {AM_CHART}", traceErr=trace_err)
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _of_kind(docs, kind):
    return [d for d in docs if d.get("kind") == kind]


def _identity_containers(docs):
    # Every container carrying the deployment identity, keyed by workload and
    # container, since three workloads run a sidecar called 'vector'.
    found = {}
    for doc in docs:
        if doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        spec = doc["spec"]["template"]["spec"]
        for c in spec.get("initContainers", []) + spec["containers"]:
            if any(e["name"] == "DEPLOYMENT_TOKEN" for e in c.get("env", [])):
                found[f"{doc['metadata']['name']}/{c['name']}"] = c
    assert len(found) == 10, sorted(found)
    assert WITHOUT_PASSWORD < {k.rsplit("/", 1)[1] for k in found}
    return found


def _secret_ref(container, name):
    (entry,) = [e for e in container.get("env", []) if e["name"] == name]
    ref = entry["valueFrom"]["secretKeyRef"]
    return ref["name"], ref["key"]


def _has_env(container, name):
    return any(e["name"] == name for e in container.get("env", []))


def _assert_refs(docs, token_secret, password_secret):
    for name, container in _identity_containers(docs).items():
        assert _secret_ref(container, "DEPLOYMENT_TOKEN") == (
            token_secret,
            "deployment-token",
        ), name
        if name.rsplit("/", 1)[1] in WITHOUT_PASSWORD:
            assert not _has_env(container, "DEPLOYMENT_PASSWORD"), name
        else:
            assert _secret_ref(container, "DEPLOYMENT_PASSWORD") == (
                password_secret,
                "deployment-password",
            ), name


def test_explicit_credentials_create_the_deployment_secret():
    docs = _template(CREDENTIALS, values_file="auth-mode-password-values.yaml")
    (secret,) = [
        s
        for s in _of_kind(docs, "Secret")
        if s["metadata"]["name"].endswith("deploymentsecret")
    ]
    assert sorted(secret["data"]) == ["deployment-password", "deployment-token"]
    _assert_refs(docs, "hush-am-deploymentsecret", "hush-am-deploymentsecret")


def test_without_credentials_the_sensor_secret_is_used():
    docs = _template()
    assert not [
        s
        for s in _of_kind(docs, "Secret")
        if s["metadata"]["name"].endswith("deploymentsecret")
    ]
    _assert_refs(docs, SENSOR_SECRET, SENSOR_SECRET)


def test_token_and_password_fall_back_independently():
    docs = _template(f"--set hushDeployment.token={DUMMY_TOKEN}")
    (secret,) = [
        s
        for s in _of_kind(docs, "Secret")
        if s["metadata"]["name"].endswith("deploymentsecret")
    ]
    assert list(secret["data"]) == ["deployment-token"]
    _assert_refs(docs, "hush-am-deploymentsecret", SENSOR_SECRET)


def test_without_a_sensor_secret_name_credentials_are_required():
    with pytest.raises(subprocess.CalledProcessError) as e:
        _template("--set hushDeployment.sensorDeploymentSecretName=", trace_err=False)
    assert "'hushDeployment.token' is undefined" in e.value.stderr


def test_pre_existing_secret_wins_over_inline_credentials():
    docs = _template(
        CREDENTIALS, values_file="pre-existing-deployment-secret-values.yaml"
    )
    assert not [
        s
        for s in _of_kind(docs, "Secret")
        if s["metadata"]["name"].endswith("deploymentsecret")
    ]
    for name, container in _identity_containers(docs).items():
        assert _secret_ref(container, "DEPLOYMENT_TOKEN") == (
            "pre-existing-secret-name",
            "token-key-name",
        ), name
        if name.rsplit("/", 1)[1] not in WITHOUT_PASSWORD:
            assert _secret_ref(container, "DEPLOYMENT_PASSWORD") == (
                "pre-existing-secret-name",
                "password-key-name",
            ), name


def test_oidc_stores_no_password():
    docs = _template(
        "--set hushDeployment.password=stale", values_file="auth-mode-oidc-values.yaml"
    )
    (secret,) = [
        s
        for s in _of_kind(docs, "Secret")
        if s["metadata"]["name"].endswith("deploymentsecret")
    ]
    assert list(secret["data"]) == ["deployment-token"]
    for container in _identity_containers(docs).values():
        assert not _has_env(container, "DEPLOYMENT_PASSWORD")
