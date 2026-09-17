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
AZURE_BASE = (
    "--set secretStore.kind=azure_kv "
    "--set secretStore.azure.vaultUrl=https://acme.vault.azure.net "
    "--set secretStore.azure.auth.tenantId=tid"
)


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


def _silo_envs(docs):
    found = []
    for spec in _pod_specs(docs):
        for container in spec.get("initContainers", []) + spec["containers"]:
            env = {var["name"]: var for var in container.get("env", [])}
            if "SILO_KIND" in env:
                found.append(env)
    assert found, "no container carries SILO_KIND"
    return found


def test_default_method_needs_no_secret():
    for env in _silo_envs(_template(AZURE_BASE)):
        assert env["SILO_KIND"]["value"] == "azure_kv"
        assert env["SILO_AZURE_KV_AUTH_METHOD"]["value"] == "default"
        assert env["SILO_AZURE_KV_TENANT_ID"]["value"] == "tid"
        assert "SILO_AZURE_KV_CLIENT_ID" not in env
        assert "SILO_AZURE_KV_CLIENT_SECRET" not in env


# The access manager reads the prefix verbatim, so a stray newline from template
# whitespace would reach the backend as part of every secret name.
def test_prefix_reaches_the_env_unchanged():
    for env in _silo_envs(
        _template(f"{AZURE_BASE} --set secretStore.prefix=acme-prod")
    ):
        assert env["SILO_NAMESPACE_PREFIX"]["value"] == "acme-prod"


# Omitted rather than sent as empty strings: the access manager treats an empty
# value as "not set" today, but that is its choice to make, not one to rely on.
def test_optional_settings_are_omitted():
    for env in _silo_envs(_template(AZURE_BASE)):
        assert "SILO_AZURE_KV_CLOUD" not in env
        assert "SILO_AZURE_KV_TIMEOUT" not in env


# Refused here as midgard refuses it: otherwise a typo is the only invalid
# Azure value that installs and then fails at pod start.
@pytest.mark.parametrize("cloud", ["public", "china", "usgov"])
def test_every_cloud_the_access_manager_accepts_renders(cloud):
    args = f"{AZURE_BASE} --set secretStore.azure.cloud={cloud}"
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLOUD"]["value"] == cloud


@pytest.mark.parametrize("cloud", ["germany", "USGOV", "Public"])
def test_an_unknown_cloud_fails_the_install(cloud):
    args = f"{AZURE_BASE} --set secretStore.azure.cloud={cloud}"
    assert "must be one of public, china, usgov" in _template_error(args)


def test_optional_settings_are_carried():
    args = (
        f"{AZURE_BASE} --set secretStore.azure.cloud=usgov "
        "--set secretStore.azure.timeout=45s"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLOUD"]["value"] == "usgov"
        assert env["SILO_AZURE_KV_TIMEOUT"]["value"] == "45s"


def test_client_secret_from_a_secret_ref():
    args = (
        f"{AZURE_BASE} --set secretStore.azure.auth.method=client_secret "
        "--set secretStore.azure.auth.clientId=cid "
        "--set secretStore.azure.auth.clientSecretSecret.name=azure-sp "
        "--set secretStore.azure.auth.clientSecretSecret.key=client-secret"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLIENT_ID"]["value"] == "cid"
        ref = env["SILO_AZURE_KV_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]
        assert ref == {"name": "azure-sp", "key": "client-secret"}
        assert "value" not in env["SILO_AZURE_KV_CLIENT_SECRET"]


def test_client_secret_inline():
    args = (
        f"{AZURE_BASE} --set secretStore.azure.auth.method=client_secret "
        "--set secretStore.azure.auth.clientId=cid "
        "--set secretStore.azure.auth.clientSecret=s3cret"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLIENT_SECRET"]["value"] == "s3cret"


# Every failure branch fails the install, each with its own message.
@pytest.mark.parametrize(
    "extra,expected",
    [
        ("--set secretStore.azure.vaultUrl=", "vaultUrl' must be defined"),
        (
            "--set secretStore.azure.vaultUrl=http://acme.vault.azure.net",
            "must be an https URL",
        ),
        ("--set secretStore.azure.auth.tenantId=", "tenantId' must be defined"),
        ("--set secretStore.azure.auth.method=saml", "method' is invalid"),
        (
            "--set secretStore.azure.auth.clientId=cid",
            "is not used by the default method",
        ),
        (
            "--set secretStore.azure.auth.clientSecret=s3cret",
            "clientSecret' is not used by the default method",
        ),
        (
            "--set secretStore.azure.auth.method=client_secret",
            "clientId' must be defined for the client_secret method",
        ),
        (
            (
                "--set secretStore.azure.auth.method=client_secret "
                "--set secretStore.azure.auth.clientId=cid"
            ),
            "must be defined for the client_secret method",
        ),
        (
            (
                "--set secretStore.azure.auth.method=client_secret "
                "--set secretStore.azure.auth.clientId=cid "
                "--set secretStore.azure.auth.clientSecret=s "
                "--set secretStore.azure.auth.clientSecretSecret.name=n "
                "--set secretStore.azure.auth.clientSecretSecret.key=k"
            ),
            "set only one of",
        ),
        (
            (
                "--set secretStore.azure.auth.method=client_secret "
                "--set secretStore.azure.auth.clientId=cid "
                "--set secretStore.azure.auth.clientSecretSecret.name=n"
            ),
            "clientSecretSecret.key' must be defined",
        ),
    ],
)
def test_invalid_config_fails_the_install(extra, expected):
    assert expected in _template_error(f"{AZURE_BASE} {extra}")


# The cap is 32 for this kind, not the 80 every other kind carries, because a
# Key Vault secret name is 127 characters and the namespace takes the rest.
@pytest.mark.parametrize(
    "prefix,ok",
    [
        ("acme", True),
        ("acme-prod-eu", True),
        ("a" * 32, True),
        ("a" * 33, False),
        ("acme_prod", False),
        ("acme.prod", False),
        ("acme/prod", False),
        ("-acme", False),
        ("acme-", False),
        ("acme--prod", False),
        ("Acme", False),
    ],
)
def test_prefix_rules(prefix, ok):
    args = f"{AZURE_BASE} --set secretStore.prefix={prefix}"
    if ok:
        for env in _silo_envs(_template(args)):
            assert env["SILO_NAMESPACE_PREFIX"]["value"] == prefix
        return
    assert "'secretStore.prefix'" in _template_error(args)
