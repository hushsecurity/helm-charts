import json
import pytest
from yaml import dump
from common.chart import template as _template

GCP_BASE = "--set secretStore.kind=gcpsm --set secretStore.gcp.projectId=my-project"
CREDENTIALS = json.dumps({"type": "service_account", "project_id": "my-project"})

# deployments whose own store is not gcpsm
OTHER_KINDS = [
    "--set secretStore.kind=kubesecrets",
    "--set secretStore.kind=awsssm --set secretStore.aws.region=eu-central-1",
    (
        "--set secretStore.kind=hc_vault "
        "--set secretStore.hcVault.address=https://vault.example.com:8200 "
        "--set secretStore.hcVault.auth.role=hush-am"
    ),
]


# a values file: --set reads the JSON's braces and commas as list syntax
def _credentials_values(tmp_path):
    path = tmp_path / "credentials-values.yaml"
    path.write_text(dump({"secretStore": {"gcp": {"credentials_json": CREDENTIALS}}}))
    return f"--values {path}"


def _pod_specs(docs):
    for doc in docs:
        if doc["kind"] in ("Deployment", "StatefulSet"):
            yield doc["spec"]["template"]["spec"]


# asserted by name, so a container losing the include fails rather than narrows
STORE_CONTAINERS = {
    "access-manager-init",
    "spire-server",
    "access-manager",
    "diag",
}


def _store_envs(docs):
    found = []
    for spec in _pod_specs(docs):
        for container in spec.get("initContainers", []) + spec["containers"]:
            env = {var["name"]: var.get("value") for var in container.get("env", [])}
            if "SILO_KIND" in env:
                found.append((container["name"], env))
    names = {name for name, _ in found}
    assert names == STORE_CONTAINERS, (
        f"containers carrying SILO_KIND changed: {sorted(names)}"
    )
    return [env for _, env in found]


def _gcp_env(env):
    return {name for name in env if name.startswith("SILO_GCP_SM_")}


def test_a_gcpsm_store_needs_no_key():
    docs = _template(GCP_BASE)

    for env in _store_envs(docs):
        assert env["SILO_KIND"] == "gcpsm"
        assert env["SILO_GCP_SM_PROJECT"] == "my-project"
        assert _gcp_env(env) == {"SILO_GCP_SM_PROJECT"}


def test_a_gcpsm_store_carries_the_key_when_given(tmp_path):
    docs = _template(f"{GCP_BASE} {_credentials_values(tmp_path)}")

    for env in _store_envs(docs):
        assert env["SILO_GCP_SM_PROJECT"] == "my-project"
        assert env["SILO_GCP_SM_CREDENTIALS_JSON"] == CREDENTIALS


# The access manager reads the key from its environment for every gcpsm store
# it serves, so it must reach the containers whatever the deployment's kind is.
@pytest.mark.parametrize("kind", OTHER_KINDS)
def test_the_key_reaches_the_containers_whatever_the_kind(kind, tmp_path):
    docs = _template(f"{kind} {_credentials_values(tmp_path)}")

    for env in _store_envs(docs):
        assert env["SILO_KIND"] != "gcpsm"
        assert _gcp_env(env) == {"SILO_GCP_SM_CREDENTIALS_JSON"}
        assert env["SILO_GCP_SM_CREDENTIALS_JSON"] == CREDENTIALS


def test_a_project_alone_renders_nothing_for_another_kind():
    docs = _template(
        "--set secretStore.kind=kubesecrets --set secretStore.gcp.projectId=my-project"
    )

    for env in _store_envs(docs):
        assert not _gcp_env(env)


def test_nothing_of_gcp_renders_when_nothing_is_set():
    docs = _template()

    for env in _store_envs(docs):
        assert not _gcp_env(env)
