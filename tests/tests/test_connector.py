import base64
import copy
import json
import os
import subprocess
import tempfile
import pytest
from yaml import CSafeLoader as Loader
from yaml import load, load_all
from common.chart import CONNECTOR_CHART, DUMMY_TOKEN, SENSOR_CHART
from common.process import bash

CI_DIR = os.path.join(CONNECTOR_CHART, "ci")
CI_FILES = sorted(f for f in os.listdir(CI_DIR) if f.endswith("-values.yaml"))
# The only values this chart has that hush-sensor does not.
CONNECTOR_ONLY_KEYS = {"connector.serviceAccount.annotations", "connector.extraVolumes"}
# Env the connector pod gets from its own release rather than from the values:
# the sensor reads EVENT_REPORTING_CONSOLE from its ConfigMap and this chart
# passes it as a plain value, and the HELM_* identity names the release.
RELEASE_ENV = {
    "EVENT_REPORTING_CONSOLE",
    "HELM_RELEASE",
    "HELM_NAMESPACE",
    "HELM_CHART_VERSION",
}

CREDENTIALS = (
    f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
)
OPENSHIFT_API = "security.openshift.io/v1"
CONTAINERS = [
    "hush-connector-client",
    "hush-connector-forwarder",
    "hush-connector-vector",
]
# Keys every container must agree on, so the three processes present the
# platform with one identity.
IDENTITY_ENV = [
    "HUSH_AUTH_MODE",
    "DEPLOYMENT_TOKEN",
    "DEPLOYMENT_PASSWORD",
    "DEPLOYMENT_KIND",
]


def _template(extra_args="", values_file=None, api_versions=(), trace_err=True):
    args = extra_args
    if values_file:
        args += f" -f {os.path.join(CI_DIR, values_file)}"
    for api_version in api_versions:
        args += f" --api-versions {api_version}"
    out = bash(
        f"helm template hush-connector {args} {CONNECTOR_CHART}", traceErr=trace_err
    )
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return load(f, Loader=Loader)


def _leaves(values, path=""):
    if isinstance(values, dict) and values:
        for key, value in values.items():
            yield from _leaves(value, f"{path}.{key}" if path else key)
    else:
        yield path, values


def _of_kind(docs, kind):
    return [d for d in docs if d.get("kind") == kind]


def _pod(docs):
    (deployment,) = _of_kind(docs, "Deployment")
    return deployment["spec"]["template"]["spec"]


def _containers(docs):
    containers = {c["name"]: c for c in _pod(docs)["containers"]}
    assert sorted(containers) == sorted(CONTAINERS)
    return containers


def _env(container):
    return {e["name"]: e for e in container.get("env", [])}


def _secret_ref(env_entry):
    ref = env_entry["valueFrom"]["secretKeyRef"]
    return ref["name"], ref["key"]


def _sa_token_audiences(docs):
    for volume in _pod(docs)["volumes"]:
        if volume["name"] == "k8s-secrets-projection":
            return [
                s["serviceAccountToken"].get("audience")
                for s in volume["projected"]["sources"]
            ]
    raise AssertionError("projected SA token volume missing")


def test_every_container_carries_the_same_identity():
    for values_file in ("auth-mode-password-values.yaml", "auth-mode-oidc-values.yaml"):
        envs = [
            _env(c) for c in _containers(_template(values_file=values_file)).values()
        ]
        for key in IDENTITY_ENV:
            assert len({str(e.get(key)) for e in envs}) == 1, (values_file, key)
        for env in envs:
            assert env["DEPLOYMENT_KIND"]["value"] == "k8s"


@pytest.mark.parametrize(
    "extra_args,missing",
    [
        ("", "token"),
        ("--set hushDeployment.password=dummy", "token"),
        (f"--set hushDeployment.token={DUMMY_TOKEN}", "password"),
        # secretKeyRef names only the token; the password still has no source
        (
            (
                "--set hushDeployment.secretKeyRef.name=my-deployment-secret"
                " --set hushDeployment.secretKeyRef.tokenKey=deployment-token"
            ),
            "password",
        ),
        ("--set hushDeployment.authMode=oidc", "token"),
    ],
)
def test_missing_credentials_fail_the_render(extra_args, missing):
    # The chart takes no credentials from a sensor release in its namespace:
    # what hush-sensor requires, this chart requires, with the same message.
    with pytest.raises(subprocess.CalledProcessError) as e:
        _template(extra_args, trace_err=False)
    assert f"'hushDeployment.{missing}' is undefined" in e.value.stderr


def test_disabled_renders_only_the_secrets():
    # As in hush-sensor, 'connector.enabled: false' drops the workload and
    # its RBAC; the Secrets stay, like the sensor's shared ones.
    docs = _template(f"{CREDENTIALS} --set connector.enabled=false")
    assert sorted({d["kind"] for d in docs}) == ["Secret"]


def test_a_stray_sensor_fallback_name_is_ignored():
    # The chart takes nothing from a sensor release; a 'sensorDeploymentSecretName'
    # carried over from a hush-am values file must not change that.
    with pytest.raises(subprocess.CalledProcessError) as e:
        _template(
            "--set hushDeployment.sensorDeploymentSecretName=hush-sensor-deploymentsecret",
            trace_err=False,
        )
    assert "'hushDeployment.token' is undefined" in e.value.stderr


def test_without_a_pull_secret_the_pod_names_none():
    assert "imagePullSecrets" not in _pod(_template(CREDENTIALS))


def test_explicit_credentials_create_the_deployment_secret():
    docs = _template(CREDENTIALS)
    (secret,) = _of_kind(docs, "Secret")
    assert secret["metadata"]["name"] == "hush-connector-deploymentsecret"
    assert base64.b64decode(secret["data"]["deployment-token"]).decode() == DUMMY_TOKEN
    assert base64.b64decode(secret["data"]["deployment-password"]).decode() == "dummy"
    for container in _containers(docs).values():
        env = _env(container)
        assert _secret_ref(env["DEPLOYMENT_TOKEN"]) == (
            "hush-connector-deploymentsecret",
            "deployment-token",
        )
        assert _secret_ref(env["DEPLOYMENT_PASSWORD"]) == (
            "hush-connector-deploymentsecret",
            "deployment-password",
        )


def test_pre_existing_secret_is_referenced_and_none_is_created():
    docs = _template(values_file="pre-existing-deployment-secret-values.yaml")
    assert _of_kind(docs, "Secret") == []
    for container in _containers(docs).values():
        env = _env(container)
        assert _secret_ref(env["DEPLOYMENT_TOKEN"]) == (
            "my-deployment-secret",
            "deployment-token",
        )
        assert _secret_ref(env["DEPLOYMENT_PASSWORD"]) == (
            "my-deployment-secret",
            "deployment-password",
        )


def test_pre_existing_secret_wins_over_inline_credentials():
    # A values block carried over from the UI's install command keeps the
    # inline token; a pre-created Secret added later must still be the one
    # used, as it is for hush-sensor, and the stale value must not be stored.
    docs = _template(
        CREDENTIALS, values_file="pre-existing-deployment-secret-values.yaml"
    )
    assert _of_kind(docs, "Secret") == []
    for container in _containers(docs).values():
        env = _env(container)
        assert _secret_ref(env["DEPLOYMENT_TOKEN"])[0] == "my-deployment-secret"
        assert _secret_ref(env["DEPLOYMENT_PASSWORD"])[0] == "my-deployment-secret"


def test_token_and_password_sources_resolve_independently():
    # secretKeyRef names only the token; the inline password is stored in the
    # chart's own Secret, which then carries no token key.
    docs = _template(
        f"{CREDENTIALS} --set hushDeployment.secretKeyRef.name=my-deployment-secret"
        " --set hushDeployment.secretKeyRef.tokenKey=deployment-token"
    )
    (secret,) = _of_kind(docs, "Secret")
    assert list(secret["data"]) == ["deployment-password"]
    for container in _containers(docs).values():
        env = _env(container)
        assert _secret_ref(env["DEPLOYMENT_TOKEN"]) == (
            "my-deployment-secret",
            "deployment-token",
        )
        assert _secret_ref(env["DEPLOYMENT_PASSWORD"]) == (
            "hush-connector-deploymentsecret",
            "deployment-password",
        )


def test_oidc_drops_the_password_and_requests_the_audience():
    # The password is left in, as happens when a password install is switched
    # to oidc by editing values; it must neither be stored nor referenced.
    docs = _template(
        "--set hushDeployment.password=stale", values_file="auth-mode-oidc-values.yaml"
    )
    (secret,) = _of_kind(docs, "Secret")
    assert list(secret["data"]) == ["deployment-token"]
    for container in _containers(docs).values():
        env = _env(container)
        assert env["HUSH_AUTH_MODE"]["value"] == "oidc"
        assert "DEPLOYMENT_PASSWORD" not in env
        assert env["HUSH_K8S_SA_TOKEN_PATH"]["value"] == (
            "/var/run/secrets/hush.k8s.projection/sa-token"
        )
        mounts = {m["name"]: m for m in container["volumeMounts"]}
        assert mounts["k8s-secrets-projection"]["readOnly"] is True
    assert _sa_token_audiences(docs) == ["https://kubernetes.default.svc"]


def test_password_mode_is_the_default():
    for container in _containers(_template(CREDENTIALS)).values():
        assert _env(container)["HUSH_AUTH_MODE"]["value"] == "password"


def test_unknown_auth_mode_is_rejected():
    with pytest.raises(subprocess.CalledProcessError) as e:
        _template(f"{CREDENTIALS} --set hushDeployment.authMode=bogus", trace_err=False)
    assert "'hushDeployment.authMode' must be one of" in e.value.stderr


def test_pull_token_creates_the_pull_secret_and_sets_the_registry():
    docs = _template(values_file="pull-token-values.yaml")
    pull_secrets = [
        s
        for s in _of_kind(docs, "Secret")
        if s["type"] == "kubernetes.io/dockerconfigjson"
    ]
    (pull_secret,) = pull_secrets
    assert pull_secret["metadata"]["name"] == "hush-connector-imagepullsecret"
    assert _pod(docs)["imagePullSecrets"] == [
        {"name": "hush-connector-imagepullsecret"}
    ]
    images = {name: c["image"] for name, c in _containers(docs).items()}
    assert images == {
        "hush-connector-client": "reg.example.com/connector-client:v0",
        "hush-connector-forwarder": "reg.example.com/connector-forwarder:v0",
        "hush-connector-vector": "reg.example.com/sensor-vector:v0",
    }


def test_pull_secret_list_is_used_as_is():
    docs = _template(values_file="pull-secret-list-values.yaml")
    assert [s["type"] for s in _of_kind(docs, "Secret")] == ["Opaque"]
    assert _pod(docs)["imagePullSecrets"] == [{"name": "pre-created-pull-secret"}]


def test_image_tags_are_separate_for_connector_and_vector():
    docs = _template(
        f"{CREDENTIALS} --set image.connectorTag=v0.7 --set image.sensorTag=v0.31"
    )
    images = {name: c["image"] for name, c in _containers(docs).items()}
    assert images["hush-connector-client"].endswith("/connector-client:v0.7")
    assert images["hush-connector-forwarder"].endswith("/connector-forwarder:v0.7")
    assert images["hush-connector-vector"].endswith("/sensor-vector:v0.31")


@pytest.mark.parametrize(
    "value,version,minimum",
    [
        ("connectorTag", "v0.4", "v0.5.0"),
        ("connectorTag", "v0.4.0", "v0.5.0"),
        ("connectorTag", "rc0.4", "v0.5.0"),
        ("connectorTag", "v0.5.0-rc1", "v0.5.0"),
        ("sensorTag", "v0.24", "v0.25.0"),
        ("sensorTag", "v0.24.0", "v0.25.0"),
    ],
)
def test_tags_below_the_minimum_are_rejected(value, version, minimum):
    with pytest.raises(subprocess.CalledProcessError) as e:
        _template(f"{CREDENTIALS} --set image.{value}={version}", trace_err=False)
    assert (
        f"Version {version} in 'image.{value}' is below the minimum supported version {minimum}"
        in e.value.stderr
    )


@pytest.mark.parametrize(
    "value,version",
    [
        ("connectorTag", "v0"),
        ("connectorTag", "rc0"),
        ("connectorTag", "v0.5"),
        ("connectorTag", "v0.5.0"),
        ("connectorTag", "v0.6.0-rc1"),
        ("connectorTag", "v1.0"),
        ("connectorTag", "965353344f"),
        ("sensorTag", "v0.25"),
        ("sensorTag", "rc1.0"),
        ("sensorTag", "965353344f"),
    ],
)
def test_tags_at_or_above_the_minimum_render(value, version):
    _containers(_template(f"{CREDENTIALS} --set image.{value}={version}"))


def test_connector_options_reach_the_right_container():
    docs = _template(values_file="connector-options-values.yaml")
    containers = _containers(docs)
    client, forwarder, vector = (containers[name] for name in CONTAINERS)
    assert _env(client)["RETRY_MAX_BACKOFF"]["value"] == "3m"
    assert "RETRY_MAX_BACKOFF" not in _env(forwarder)
    assert _env(forwarder)["FORWARDER_TIMEOUT"]["value"] == "777"
    assert "FORWARDER_TIMEOUT" not in _env(client)
    assert _env(vector)["EVENT_REPORTING_CONSOLE"]["value"] == "no"
    assert "EVENT_REPORTING_CONSOLE" not in _env(client)

    pod = _pod(docs)
    assert pod["priorityClassName"] == "system-cluster-critical"
    assert pod["nodeSelector"] == {"kubernetes.io/os": "linux"}
    assert {v["name"] for v in pod["volumes"]} >= {
        "ca-bundle",
        "vector-socket",
        "tokengen-state",
    }
    for container in (client, forwarder):
        assert "ca-bundle" in {m["name"] for m in container["volumeMounts"]}
    assert "ca-bundle" not in {m["name"] for m in vector["volumeMounts"]}

    (deployment,) = _of_kind(docs, "Deployment")
    assert deployment["spec"]["template"]["metadata"]["annotations"] == {
        "example.com/owner": "platform"
    }
    (sa,) = _of_kind(docs, "ServiceAccount")
    assert sa["metadata"]["annotations"] == {
        "eks.amazonaws.com/role-arn": "arn:aws:iam::000000000000:role/connector"
    }


def test_event_reporting_console_unset_drops_the_env():
    docs = _template(f"{CREDENTIALS} --set eventReportingConsole=")
    assert "EVENT_REPORTING_CONSOLE" not in _env(
        _containers(docs)["hush-connector-vector"]
    )


def test_vector_reports_the_release():
    docs = _template(f"{CREDENTIALS} --namespace hush")
    env = _env(_containers(docs)["hush-connector-vector"])
    assert env["HELM_RELEASE"]["value"] == "hush-connector"
    assert env["HELM_NAMESPACE"]["value"] == "hush"
    assert env["HELM_CHART_VERSION"]["value"]


def test_cluster_role_reads_only_kube_system():
    docs = _template(CREDENTIALS)
    (role,) = _of_kind(docs, "ClusterRole")
    assert role["rules"] == [
        {
            "apiGroups": [""],
            "resources": ["namespaces"],
            "resourceNames": ["kube-system"],
            "verbs": ["get"],
        }
    ]
    (binding,) = _of_kind(docs, "ClusterRoleBinding")
    (sa,) = _of_kind(docs, "ServiceAccount")
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": sa["metadata"]["name"],
            "namespace": "default",
        }
    ]
    assert _pod(docs)["serviceAccountName"] == sa["metadata"]["name"]


def _scc_bindings(docs):
    return [
        rb
        for rb in _of_kind(docs, "RoleBinding")
        if rb["roleRef"]["name"].startswith("system:openshift:scc:")
    ]


def test_scc_binding_absent_without_the_openshift_api():
    assert _scc_bindings(_template(values_file="openshift-values.yaml")) == []


def test_scc_binding_disabled_by_value():
    docs = _template(
        values_file="openshift-disabled-values.yaml", api_versions=[OPENSHIFT_API]
    )
    assert _scc_bindings(docs) == []


def test_scc_binding_grants_anyuid_to_the_service_account():
    docs = _template(values_file="openshift-values.yaml", api_versions=[OPENSHIFT_API])
    (binding,) = _scc_bindings(docs)
    (sa,) = _of_kind(docs, "ServiceAccount")
    assert binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "system:openshift:scc:anyuid",
    }
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": sa["metadata"]["name"],
            "namespace": "default",
        }
    ]


def test_values_are_a_subset_of_the_sensors():
    # A sensor's 'connector.*' block and credentials carry over unchanged only
    # while every key this chart reads exists in hush-sensor under the same
    # path with the same default.
    connector = dict(_leaves(_load_yaml(os.path.join(CONNECTOR_CHART, "values.yaml"))))
    sensor = dict(_leaves(_load_yaml(os.path.join(SENSOR_CHART, "values.yaml"))))
    assert {k for k in connector if k not in sensor} == CONNECTOR_ONLY_KEYS
    assert {
        k: (v, sensor[k])
        for k, v in connector.items()
        if k in sensor and sensor[k] != v
    } == {}


def _comparable_pod(deployment, release):
    # The pod spec with the differences this chart declares against the
    # sensor's connector pod taken out: the service account and the
    # release-named Secrets, and the env the release itself supplies.
    template = deployment["spec"]["template"]
    assert template["metadata"]["labels"]["app.kubernetes.io/component"] == "connector"
    spec = copy.deepcopy(template["spec"])
    spec.pop("serviceAccountName")
    for container in spec["containers"]:
        container["env"] = [
            e for e in container.get("env", []) if e["name"] not in RELEASE_ENV
        ]
    text = json.dumps(spec, sort_keys=True)
    for secret in ("deploymentsecret", "imagepullsecret"):
        text = text.replace(f'"{release}-{secret}"', f'"<release>-{secret}"')
    return json.loads(text), template["metadata"].get("annotations")


@pytest.mark.parametrize("values_file", CI_FILES)
def test_pod_matches_the_sensors_connector(values_file):
    # The chart deploys the pod hush-sensor deploys under 'connector.*'. Render
    # both from the same values, without the two connector-only keys, and
    # compare the pod specs.
    values = _load_yaml(os.path.join(CI_DIR, values_file)) or {}
    for key in CONNECTOR_ONLY_KEYS:
        section, name = key.rsplit(".", 1)
        node = values
        for part in section.split("."):
            node = node.get(part, {})
        node.pop(name, None)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "values.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(values, f)
        (connector,) = _of_kind(_template(f"-f {path}"), "Deployment")
        out = bash(
            "helm template hush-sensor --set daemonSet.enabled=false"
            " --set sentry.enabled=false --set vermon.enabled=false"
            f" -f {path} {SENSOR_CHART}"
        )
        (sensor,) = _of_kind(
            [d for d in load_all(out, Loader=Loader) if d], "Deployment"
        )
    assert _comparable_pod(connector, "hush-connector") == _comparable_pod(
        sensor, "hush-sensor"
    )
