"""The pod label that makes the Azure workload identity webhook act.

The webhook reads the client id from the service account annotation, but only
mutates a Pod carrying azure.workload.identity/use. Without it
DefaultAzureCredential falls through to IMDS and the node's identity, which is
a different principal, shared by every pod on the node, and usually succeeds --
so a pod missing the label works as the wrong identity rather than failing.
"""

import pytest
from common.chart import template as _template

LABEL = "azure.workload.identity/use"
CLIENT_ID = "00000000-0000-0000-0000-000000000000"
# the label is decided by the client id alone, not by the secret store kind
BASE = "--set secretStore.kind=kubesecrets"

# both spellings annotate the same service account, the second deprecated, so
# the label has to follow whichever one is set
SETTINGS = [
    "accessManager.workloadIdentity.azure.clientId",
    "containerRegistry.azure.clientId",
]


def _pod_labels(docs):
    return {
        doc["metadata"]["name"]: doc["spec"]["template"]["metadata"]["labels"]
        for doc in docs
        if doc["kind"] in ("Deployment", "StatefulSet")
    }


def _component(labels):
    return labels.get("app.kubernetes.io/component")


@pytest.mark.parametrize("setting", SETTINGS)
def test_every_pod_that_reaches_azure_is_labelled(setting):
    labelled = _pod_labels(_template(f"{BASE} --set {setting}={CLIENT_ID}"))
    # the access manager serves the silo and diag runs the secret-store check,
    # so both build one; the api controller does not
    wanted = {
        n for n, l in labelled.items() if _component(l) in ("access-manager", "diag")
    }
    assert wanted, "no access-manager or diag workload rendered"
    for name in wanted:
        assert labelled[name].get(LABEL) == "true", name


@pytest.mark.parametrize("setting", SETTINGS)
def test_the_annotation_and_the_label_agree(setting):
    docs = _template(f"{BASE} --set {setting}={CLIENT_ID}")
    annotated = [
        doc
        for doc in docs
        if doc["kind"] == "ServiceAccount"
        and doc["metadata"]
        .get("annotations", {})
        .get("azure.workload.identity/client-id")
    ]
    assert annotated, "the service account carries no client id"
    assert any(l.get(LABEL) == "true" for l in _pod_labels(docs).values())


def test_no_label_without_a_client_id():
    for labels in _pod_labels(_template(BASE)).values():
        assert LABEL not in labels


# the diag pod keeps its own component label rather than the access manager's,
# which the webhook failurePolicy guard reads back
def test_diag_keeps_its_component_label():
    labelled = _pod_labels(_template(f"{BASE} --set {SETTINGS[0]}={CLIENT_ID}"))
    assert any(_component(l) == "diag" for l in labelled.values())
