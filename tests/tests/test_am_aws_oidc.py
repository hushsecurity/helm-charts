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
ROLE = "arn:aws:iam::000000000000:role/access-manager"
OIDC_ROLE = f"--set accessManager.workloadIdentity.aws.oidc.role={ROLE}"
AWS_SILO = "--set secretStore.kind=awssm --set secretStore.aws.region=eu-central-1"
TOKEN_FILE = "/var/run/secrets/hush.k8s.aws.projection/sa-token"
TOKEN_VOLUME = "aws-token-projection"
DEFAULT_AUDIENCE = "sts.amazonaws.com"


def _template(extra_args="", trace_err=True):
    args = (
        f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
    )
    out = bash(f"helm template {args} {extra_args} {CHART}", traceErr=trace_err)
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _pod_specs(docs):
    for doc in docs:
        if doc.get("kind") in ("Deployment", "StatefulSet", "DaemonSet"):
            yield doc["metadata"]["name"], doc["spec"]["template"]["spec"]


def _containers(spec):
    return spec.get("initContainers", []) + spec["containers"]


def _env(container):
    return {e["name"]: e.get("value") for e in container.get("env", [])}


def _reaches_aws(env):
    return any(k.startswith("SILO_AWS_") for k in env) or "ZAZU_AWS_ECR_CFG_MODE" in env


def _audiences(docs):
    found = set()
    for _, spec in _pod_specs(docs):
        for volume in spec.get("volumes", []):
            if volume["name"] != TOKEN_VOLUME:
                continue
            for source in volume["projected"]["sources"]:
                found.add(source["serviceAccountToken"]["audience"])
    return found


# A container that reaches AWS without the role and the token falls back to the
# node instance role, which a cluster outside EC2 has not got. Guards against a
# container gaining AWS configuration later without gaining the credentials.
def test_every_aws_facing_container_carries_the_role_and_the_token():
    docs = _template(f"{AWS_SILO} {OIDC_ROLE}")

    checked = []
    for name, spec in _pod_specs(docs):
        for container in _containers(spec):
            env = _env(container)
            if not _reaches_aws(env):
                continue
            where = f"{name}/{container['name']}"
            checked.append(where)
            assert env.get("AWS_ROLE_ARN") == ROLE, where
            assert env.get("AWS_WEB_IDENTITY_TOKEN_FILE") == TOKEN_FILE, where
            mounts = {m["name"] for m in container.get("volumeMounts", [])}
            assert TOKEN_VOLUME in mounts, where

    # The silo containers plus the admission controller reaching ECR.
    assert len(checked) >= 5, checked


# The audience is what an IAM OIDC identity provider is registered with, so an
# unset value must not reach AWS as the cluster default audience.
def test_audience_defaults_to_sts():
    assert _audiences(_template(f"{AWS_SILO} {OIDC_ROLE}")) == {DEFAULT_AUDIENCE}


def test_cleared_audience_falls_back_to_the_default():
    docs = _template(
        f"{AWS_SILO} {OIDC_ROLE} --set accessManager.workloadIdentity.aws.oidc.audience="
    )

    assert _audiences(docs) == {DEFAULT_AUDIENCE}


def test_audience_is_taken_from_the_value():
    docs = _template(
        f"{AWS_SILO} {OIDC_ROLE}"
        " --set accessManager.workloadIdentity.aws.oidc.audience=hush.security/am"
    )

    assert _audiences(docs) == {"hush.security/am"}


# Two AWS credentials on one pod cannot both be right, and the SDK resolves a
# static access key ahead of the token file, so the wrong one would win unseen.
@pytest.mark.parametrize(
    "conflicting",
    [
        f"--set accessManager.workloadIdentity.aws.irsa={ROLE}",
        f"--set secretStore.aws.irsa={ROLE}",
        f"--set containerRegistry.aws.irsa={ROLE}",
        (
            "--set secretStore.aws.access_key.access_key_id=AKIAEXAMPLE"
            " --set secretStore.aws.access_key.secret_access_key=secret"
        ),
    ],
)
def test_oidc_role_rejects_another_aws_credential(conflicting):
    with pytest.raises(subprocess.CalledProcessError) as err:
        _template(f"{AWS_SILO} {OIDC_ROLE} {conflicting}", trace_err=False)

    assert "must not be combined with" in err.value.stderr


# On AKS or GKE the access manager needs the role for the silo and the cluster's
# own cloud identity for its container registry, so the two must not interfere:
# each cloud keeps its own annotation, and the AWS token still reaches the pod.
def test_role_coexists_with_the_cluster_own_cloud_identity():
    azure = "--set accessManager.workloadIdentity.azure.clientId=00000000-0000-0000-0000-000000000000"
    gcp = "--set accessManager.workloadIdentity.gcp.sa=am@my-project.iam.gserviceaccount.com"
    docs = _template(f"{AWS_SILO} {OIDC_ROLE} {azure} {gcp}")

    # Each cloud annotates the shared service account with its own key, and the
    # EKS one stays absent because the role is assumed from a projected token.
    accounts = [
        d
        for d in docs
        if d["kind"] == "ServiceAccount" and "access-manager" in d["metadata"]["name"]
    ]
    assert len(accounts) == 1
    annotations = accounts[0]["metadata"].get("annotations", {})
    assert annotations.get("azure.workload.identity/client-id")
    assert annotations.get("iam.gke.io/gcp-service-account")
    assert "eks.amazonaws.com/role-arn" not in annotations

    # The Azure webhook only mutates a pod carrying its label, so the label must
    # survive beside the AWS wiring.
    managers = [
        d
        for d in docs
        if d["kind"] in ("Deployment", "StatefulSet")
        and "access-manager" in d["metadata"]["name"]
    ]
    assert len(managers) == 1
    labels = managers[0]["spec"]["template"]["metadata"]["labels"]
    assert labels.get("azure.workload.identity/use") == "true"

    # The AWS token is still projected, and still reaches every AWS-facing
    # container, beside whatever that webhook injects later.
    assert _audiences(docs) == {DEFAULT_AUDIENCE}
    for name, spec in _pod_specs(docs):
        for container in _containers(spec):
            env = _env(container)
            if _reaches_aws(env):
                assert env.get("AWS_ROLE_ARN") == ROLE, f"{name}/{container['name']}"


# Without a role the chart keeps the pod on the host network for the node
# instance role, and projects no AWS token at all.
def test_no_role_projects_no_token():
    docs = _template(AWS_SILO)

    assert _audiences(docs) == set()
    for name, spec in _pod_specs(docs):
        for container in _containers(spec):
            assert "AWS_ROLE_ARN" not in _env(container), f"{name}/{container['name']}"
