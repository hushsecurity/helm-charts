import base64
import os
import subprocess
import pytest
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.process import bash

TOP_DIR = os.environ["TOP_DIR"]
CHART = os.path.join(TOP_DIR, "charts", "hush-am")

DUMMY_TOKEN = base64.b64encode(b"d1:zone:realm:org-id:deployment-id").decode()
VAULT_BASE = (
    "--set secretStore.kind=hc_vault "
    "--set secretStore.vault.address=https://vault.example.com:8200"
)
SA_TOKEN_PATH = "/var/run/secrets/hush.vault.projection/sa-token"
SA_TOKEN_VOLUME = "vault-sa-token"


def _template(extra_args="", trace_err=True):
    args = (
        f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
    )
    out = bash(f"helm template {args} {extra_args} {CHART}", traceErr=trace_err)
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(extra_args, trace_err=False)
    return excinfo.value.stderr


def _pod_specs(docs):
    for doc in docs:
        if doc["kind"] in ("Deployment", "StatefulSet"):
            yield doc["spec"]["template"]["spec"]


# SILO_KIND reaches four containers across two workloads, so find them by the
# variable rather than by name.
def _silo_containers(docs):
    found = []
    for spec in _pod_specs(docs):
        for container in spec.get("initContainers", []) + spec["containers"]:
            env = {var["name"]: var for var in container.get("env", [])}
            if "SILO_KIND" in env:
                found.append((spec, container, env))
    assert found, "no container carries SILO_KIND"
    return found


def _values(env):
    return {name: var.get("value") for name, var in env.items()}


@pytest.mark.parametrize("method", ["kubernetes", "jwt"])
def test_jwt_methods_wire_the_role_and_the_projected_token(method):
    docs = _template(
        f"{VAULT_BASE} --set secretStore.vault.auth.method={method} "
        "--set secretStore.vault.auth.role=hush-am"
    )

    for _, _, env in _silo_containers(docs):
        values = _values(env)
        assert values["SILO_KIND"] == "hc_vault"
        assert values["SILO_HC_VAULT_AUTH_METHOD"] == method
        assert values["SILO_HC_VAULT_ROLE"] == "hush-am"
        assert values["SILO_HC_VAULT_SA_TOKEN_FILE"] == SA_TOKEN_PATH
        assert "SILO_HC_VAULT_TOKEN" not in env


# Nothing ties the variable to the volume, so a container with one and not the
# other fails at runtime rather than at install.
@pytest.mark.parametrize("method", ["kubernetes", "jwt"])
def test_every_container_told_of_the_token_mounts_it(method):
    docs = _template(
        f"{VAULT_BASE} --set secretStore.vault.auth.method={method} "
        "--set secretStore.vault.auth.role=hush-am"
    )

    for spec, container, env in _silo_containers(docs):
        assert _values(env)["SILO_HC_VAULT_SA_TOKEN_FILE"] == SA_TOKEN_PATH
        mounts = {m["name"]: m for m in container["volumeMounts"]}
        assert SA_TOKEN_VOLUME in mounts, container["name"]
        assert SA_TOKEN_PATH.startswith(mounts[SA_TOKEN_VOLUME]["mountPath"] + "/")
        assert mounts[SA_TOKEN_VOLUME]["readOnly"]
        volumes = {v["name"]: v for v in spec["volumes"]}
        assert SA_TOKEN_VOLUME in volumes
        source = volumes[SA_TOKEN_VOLUME]["projected"]["sources"][0]
        assert source["serviceAccountToken"]["path"] == "sa-token"


# Projected on its own: the audience Vault accepts is the operator's choice.
def test_the_audience_is_requested_only_when_asked_for():
    role = "--set secretStore.vault.auth.role=hush-am"
    unset = _template(f"{VAULT_BASE} {role}")
    named = _template(
        f"{VAULT_BASE} {role} --set secretStore.vault.auth.audience=vault"
    )

    for docs, expected in ((unset, None), (named, "vault")):
        for spec, _, _ in _silo_containers(docs):
            volumes = {v["name"]: v for v in spec["volumes"]}
            source = volumes[SA_TOKEN_VOLUME]["projected"]["sources"][0]
            assert source["serviceAccountToken"].get("audience") == expected


def test_the_token_method_needs_no_projected_token():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.vault.auth.method=token "
        "--set secretStore.vault.auth.token=hvs.example"
    )

    for spec, container, env in _silo_containers(docs):
        values = _values(env)
        assert values["SILO_HC_VAULT_AUTH_METHOD"] == "token"
        assert values["SILO_HC_VAULT_TOKEN"] == "hvs.example"
        assert "SILO_HC_VAULT_SA_TOKEN_FILE" not in env
        assert SA_TOKEN_VOLUME not in {m["name"] for m in container["volumeMounts"]}
        assert SA_TOKEN_VOLUME not in {v["name"] for v in spec["volumes"]}


def test_a_named_secret_keeps_the_token_out_of_the_manifest():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.vault.auth.method=token "
        "--set secretStore.vault.auth.tokenSecret.name=vault-token "
        "--set secretStore.vault.auth.tokenSecret.key=token"
    )

    for _, _, env in _silo_containers(docs):
        secret_ref = env["SILO_HC_VAULT_TOKEN"]["valueFrom"]["secretKeyRef"]
        assert secret_ref == {"name": "vault-token", "key": "token"}
        assert "value" not in env["SILO_HC_VAULT_TOKEN"]


def test_the_optional_settings_are_omitted_rather_than_sent_empty():
    docs = _template(f"{VAULT_BASE} --set secretStore.vault.auth.role=hush-am")

    for _, _, env in _silo_containers(docs):
        for name in (
            "SILO_HC_VAULT_MOUNT",
            "SILO_HC_VAULT_ENTERPRISE_NAMESPACE",
            "SILO_HC_VAULT_CA_CERT",
            "SILO_HC_VAULT_TIMEOUT",
            "SILO_HC_VAULT_AUTH_MOUNT",
        ):
            assert name not in env


def test_the_optional_settings_are_passed_when_given():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.vault.auth.role=hush-am "
        "--set secretStore.vault.mount=hush-kv "
        "--set secretStore.vault.namespace=admin/team-a "
        "--set secretStore.vault.caCert=PEM "
        "--set secretStore.vault.timeout=10s "
        "--set secretStore.vault.auth.mount=kubernetes-hush"
    )

    for _, _, env in _silo_containers(docs):
        values = _values(env)
        assert values["SILO_HC_VAULT_MOUNT"] == "hush-kv"
        assert values["SILO_HC_VAULT_ENTERPRISE_NAMESPACE"] == "admin/team-a"
        assert values["SILO_HC_VAULT_CA_CERT"] == "PEM"
        assert values["SILO_HC_VAULT_TIMEOUT"] == "10s"
        assert values["SILO_HC_VAULT_AUTH_MOUNT"] == "kubernetes-hush"


# A store that renders and then cannot authenticate leaves the access manager
# retrying against a config that cannot be edited, so each of these must fail
# the install.
@pytest.mark.parametrize(
    "extra_args,message",
    [
        (
            (
                "--set secretStore.kind=hc_vault "
                "--set secretStore.vault.auth.role=hush-am"
            ),
            "'secretStore.vault.address' must be defined",
        ),
        (
            (
                "--set secretStore.kind=hc_vault "
                "--set secretStore.vault.auth.role=hush-am "
                "--set secretStore.vault.address=http://vault.example.com"
            ),
            "'secretStore.vault.address' must be an https URL",
        ),
        (
            f"{VAULT_BASE} --set secretStore.vault.auth.method=approle",
            "'secretStore.vault.auth.method' must be one of",
        ),
        (
            VAULT_BASE,
            "'secretStore.vault.auth.role' must be defined for the kubernetes",
        ),
        (
            f"{VAULT_BASE} --set secretStore.vault.auth.method=jwt",
            "'secretStore.vault.auth.role' must be defined for the jwt",
        ),
        (
            f"{VAULT_BASE} --set secretStore.vault.auth.method=token",
            (
                "'secretStore.vault.auth.token' or "
                "'secretStore.vault.auth.tokenSecret' must be defined"
            ),
        ),
        (
            (
                f"{VAULT_BASE} --set secretStore.vault.auth.method=token "
                "--set secretStore.vault.auth.token=hvs.example "
                "--set secretStore.vault.auth.tokenSecret.name=vault-token "
                "--set secretStore.vault.auth.tokenSecret.key=token"
            ),
            "are mutually exclusive",
        ),
        (
            (
                f"{VAULT_BASE} --set secretStore.vault.auth.method=token "
                "--set secretStore.vault.auth.tokenSecret.name=vault-token"
            ),
            "'secretStore.vault.auth.tokenSecret.key' must be defined",
        ),
    ],
)
def test_a_misconfigured_vault_store_fails_the_install(extra_args, message):
    assert message in _template_error(extra_args)


# A prefix this chart accepts and the API refuses installs, then fails every
# write.
@pytest.mark.parametrize(
    "prefix,message",
    [
        ("/acme", "must not start with '/'"),
        ("acme/", "must not end with '/'"),
        ("acme//prod", "must not repeat '/'"),
        ("acme+prod", "is invalid for kind hc_vault"),
        ("a" * 81, "exceeds 80 characters"),
    ],
)
def test_an_invalid_vault_prefix_fails_the_install(prefix, message):
    extra_args = (
        f"{VAULT_BASE} --set secretStore.vault.auth.role=hush-am "
        f"--set-string secretStore.prefix={prefix}"
    )

    assert message in _template_error(extra_args)


@pytest.mark.parametrize(
    "prefix", ["acme/prod/eu", "acme__prod", "acme.prod-eu", "a" * 80]
)
def test_a_valid_vault_prefix_reaches_the_silo(prefix):
    docs = _template(
        f"{VAULT_BASE} --set secretStore.vault.auth.role=hush-am "
        f"--set-string secretStore.prefix={prefix}"
    )

    for _, _, env in _silo_containers(docs):
        assert _values(env)["SILO_NAMESPACE_PREFIX"] == prefix
