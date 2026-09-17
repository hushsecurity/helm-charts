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
    "--set secretStore.azureKv.vaultUrl=https://acme.vault.azure.net "
    "--set secretStore.azureKv.auth.tenantId=tid"
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
    args = f"{AZURE_BASE} --set secretStore.azureKv.cloud={cloud}"
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLOUD"]["value"] == cloud


@pytest.mark.parametrize("cloud", ["germany", "USGOV", "Public"])
def test_an_unknown_cloud_fails_the_install(cloud):
    args = f"{AZURE_BASE} --set secretStore.azureKv.cloud={cloud}"
    assert "must be one of public, china, usgov" in _template_error(args)


def test_optional_settings_are_carried():
    args = (
        f"{AZURE_BASE} --set secretStore.azureKv.cloud=usgov "
        "--set secretStore.azureKv.timeout=45s"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLOUD"]["value"] == "usgov"
        assert env["SILO_AZURE_KV_TIMEOUT"]["value"] == "45s"


def test_client_secret_from_a_secret_ref():
    args = (
        f"{AZURE_BASE} --set secretStore.azureKv.auth.method=client_secret "
        "--set secretStore.azureKv.auth.clientId=cid "
        "--set secretStore.azureKv.auth.clientSecretRef.name=azure-sp "
        "--set secretStore.azureKv.auth.clientSecretRef.key=client-secret"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLIENT_ID"]["value"] == "cid"
        ref = env["SILO_AZURE_KV_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]
        assert ref == {"name": "azure-sp", "key": "client-secret"}
        assert "value" not in env["SILO_AZURE_KV_CLIENT_SECRET"]


def test_client_secret_inline():
    args = (
        f"{AZURE_BASE} --set secretStore.azureKv.auth.method=client_secret "
        "--set secretStore.azureKv.auth.clientId=cid "
        "--set secretStore.azureKv.auth.clientSecret=s3cret"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLIENT_SECRET"]["value"] == "s3cret"


# Every failure branch fails the install, each with its own message.
@pytest.mark.parametrize(
    "extra,expected",
    [
        ("--set secretStore.azureKv.vaultUrl=", "vaultUrl' must be defined"),
        (
            "--set secretStore.azureKv.vaultUrl=http://acme.vault.azure.net",
            "must be an https URL",
        ),
        ("--set secretStore.azureKv.auth.tenantId=", "tenantId' must be defined"),
        ("--set secretStore.azureKv.auth.method=saml", "method' is invalid"),
        (
            "--set secretStore.azureKv.auth.clientId=cid",
            "is not used by the default method",
        ),
        (
            "--set secretStore.azureKv.auth.method=client_secret",
            "clientId' must be defined for the client_secret method",
        ),
        (
            (
                "--set secretStore.azureKv.auth.method=client_secret "
                "--set secretStore.azureKv.auth.clientId=cid"
            ),
            "must be defined for the client_secret method",
        ),
        (
            (
                "--set secretStore.azureKv.auth.method=client_secret "
                "--set secretStore.azureKv.auth.clientId=cid "
                "--set secretStore.azureKv.auth.clientSecret=s "
                "--set secretStore.azureKv.auth.clientSecretRef.name=n "
                "--set secretStore.azureKv.auth.clientSecretRef.key=k"
            ),
            "set only one of",
        ),
        (
            (
                "--set secretStore.azureKv.auth.method=client_secret "
                "--set secretStore.azureKv.auth.clientId=cid "
                "--set secretStore.azureKv.auth.clientSecretRef.name=n"
            ),
            "clientSecretRef.key' must be defined",
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


# The access manager reads the client secret and the timeout for every azure
# store it serves, including ones created through the Hush API, so they are
# carried whatever the deployment's own kind is.
@pytest.mark.parametrize("kind", ["kubesecrets", "awssm", "hc_vault"])
def test_client_secret_and_timeout_are_carried_for_any_kind(kind):
    args = (
        f"--set secretStore.kind={kind} "
        "--set secretStore.azureKv.auth.clientSecret=s3cret "
        "--set secretStore.azureKv.timeout=45s "
        "--set secretStore.aws.region=eu-west-1 "
        "--set secretStore.hcVault.address=https://v:8200 "
        "--set secretStore.hcVault.auth.role=hush-am"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_CLIENT_SECRET"]["value"] == "s3cret"
        assert env["SILO_AZURE_KV_TIMEOUT"]["value"] == "45s"


def test_client_secret_from_a_secret_ref_is_carried_for_any_kind():
    args = (
        "--set secretStore.kind=kubesecrets "
        "--set secretStore.azureKv.auth.clientSecretRef.name=azure-sp "
        "--set secretStore.azureKv.auth.clientSecretRef.key=client-secret"
    )
    for env in _silo_envs(_template(args)):
        ref = env["SILO_AZURE_KV_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]
        assert ref == {"name": "azure-sp", "key": "client-secret"}


# The secret is process-wide, read for every azure store the deployment serves,
# so the default method carries one without using it itself. clientId stays
# refused: the SDK has no field for one and would ignore it.
def test_the_default_method_still_carries_a_client_secret():
    args = f"{AZURE_BASE} --set secretStore.azureKv.auth.clientSecret=s3cret"
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_AUTH_METHOD"]["value"] == "default"
        assert env["SILO_AZURE_KV_CLIENT_SECRET"]["value"] == "s3cret"


# Matching midgard and the provider, which both lower the scheme; the old
# hasPrefix check refused this and accepted a URL with no host at all.
@pytest.mark.parametrize(
    "url", ["HTTPS://acme.vault.azure.net", "Https://acme.vault.azure.net"]
)
def test_the_vault_url_scheme_is_case_insensitive(url):
    args = (
        "--set secretStore.kind=azure_kv "
        f"--set secretStore.azureKv.vaultUrl={url} "
        "--set secretStore.azureKv.auth.tenantId=tid"
    )
    for env in _silo_envs(_template(args)):
        assert env["SILO_AZURE_KV_VAULT_URL"]["value"] == url


def test_a_vault_url_with_no_host_is_refused():
    args = (
        "--set secretStore.kind=azure_kv "
        "--set secretStore.azureKv.vaultUrl=https:// "
        "--set secretStore.azureKv.auth.tenantId=tid"
    )
    assert "must be an https URL" in _template_error(args)
