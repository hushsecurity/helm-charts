"""The service account token the access manager presents to Vault.

A store created through the Hush API is served by whichever deployment it is
attached to, whatever that deployment's own kind or auth method is, so the
token is projected for every kind. It carries a Vault audience rather than the
cluster's default, which would be a token valid against the api server -- and
the login posts it to whatever address the store names.
"""

import pytest
from common.chart import template as _template

ENV = "SILO_HC_VAULT_SA_TOKEN_FILE"
KINDS = {
    "kubesecrets": "",
    "awssm": "--set secretStore.aws.region=eu-west-1",
    "gcpsm": "--set secretStore.gcp.projectId=p",
    "hc_vault": (
        "--set secretStore.hcVault.address=https://v:8200 "
        "--set secretStore.hcVault.auth.role=hush-am"
    ),
    # the chart's own store needs no projected token here, but a platform
    # store attached to this deployment may still log in with one
    "hc_vault-token": (
        "--set secretStore.kind=hc_vault "
        "--set secretStore.hcVault.address=https://v:8200 "
        "--set secretStore.hcVault.auth.method=token "
        "--set secretStore.hcVault.auth.token=t"
    ),
}


def _args(kind):
    extra = KINDS[kind]
    return (
        extra if kind.endswith("-token") else f"--set secretStore.kind={kind} {extra}"
    )


def _audiences(docs):
    found = []
    for doc in docs:
        if doc["kind"] not in ("Deployment", "StatefulSet"):
            continue
        for vol in doc["spec"]["template"]["spec"].get("volumes", []):
            for src in vol.get("projected", {}).get("sources", []):
                token = src.get("serviceAccountToken")
                if token and "vault" in vol["name"]:
                    found.append(token.get("audience"))
    return found


def _has_env(docs):
    for doc in docs:
        if doc["kind"] not in ("Deployment", "StatefulSet"):
            continue
        spec = doc["spec"]["template"]["spec"]
        for c in spec.get("initContainers", []) + spec["containers"]:
            if any(e["name"] == ENV for e in c.get("env", [])):
                return True
    return False


@pytest.mark.parametrize("kind", list(KINDS))
def test_the_token_is_projected_for_every_kind(kind):
    docs = _template(_args(kind))
    assert _has_env(docs), kind
    assert _audiences(docs), kind


@pytest.mark.parametrize("kind", list(KINDS))
def test_the_token_is_scoped_to_vault_not_the_cluster(kind):
    for audience in _audiences(_template(_args(kind))):
        assert audience == "vault", kind


# An operator who has already bound a role to the cluster default can ask for
# it back, which is the only way to get a token the api server accepts.
def test_an_empty_audience_still_requests_the_cluster_default():
    docs = _template(
        "--set secretStore.kind=kubesecrets --set secretStore.hcVault.auth.audience="
    )
    assert _has_env(docs)
    assert _audiences(docs) == [None] * len(_audiences(docs))
