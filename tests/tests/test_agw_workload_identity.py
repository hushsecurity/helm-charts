import subprocess
import pytest
from yaml import dump
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = (
    "--set agw.hostname=gw.example.com "
    "--set secretStore.kind=awssm --set secretStore.aws.region=eu-central-1"
)
ROLE = "arn:aws:iam::123456789012:role/hush-agw"
TOKEN_PATH = "/var/run/secrets/hush.k8s.aws.projection/sa-token"
TOKEN_VOLUME = "aws-token-projection"

# the containers that reach the secret store
STORE_CONTAINERS = {"agw-controller-init", "agw-controller"}


def template(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=False)
    return excinfo.value.stderr


def _service_account_annotations(docs):
    (account,) = [doc for doc in docs if doc["kind"] == "ServiceAccount"]
    return account["metadata"].get("annotations", {})


def _pod_spec(docs):
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    return deployment["spec"]["template"]["spec"]


# On EKS and GKE the identity rides on the service account: irsa and the GCP
# service account become its annotations, and the ones set by hand stay beside
# them.
def test_irsa_and_gcp_sa_annotate_the_service_account():
    # Render with both identities and an annotation of the operator's own.
    docs = template(
        f"--set agw.workloadIdentity.aws.irsa={ROLE} "
        "--set agw.workloadIdentity.gcp.sa=gw@my-project.iam.gserviceaccount.com "
        "--set agw.serviceAccount.annotations.team=gateway"
    )

    # All three are on the service account.
    assert _service_account_annotations(docs) == {
        "eks.amazonaws.com/role-arn": ROLE,
        "iam.gke.io/gcp-service-account": "gw@my-project.iam.gserviceaccount.com",
        "team": "gateway",
    }


# With irsa the EKS webhook would give the role to every container; the pod
# keeps it to the containers that reach the secret store.
def test_irsa_reaches_only_the_store_containers():
    # Render with irsa.
    docs = template(f"--set agw.workloadIdentity.aws.irsa={ROLE}")
    spec = _pod_spec(docs)
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    annotations = deployment["spec"]["template"]["metadata"]["annotations"]

    # Every container but the store ones is skipped by the webhook.
    skipped = set(annotations["eks.amazonaws.com/skip-containers"].split(","))
    names = {c["name"] for c in spec["initContainers"] + spec["containers"]}
    assert skipped == names - STORE_CONTAINERS

    # Without irsa the pod carries no such annotation.
    docs = template()
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    annotations = deployment["spec"]["template"]["metadata"].get("annotations", {})
    assert "eks.amazonaws.com/skip-containers" not in annotations


# An annotation set by hand wins over the one an identity value sets, so a
# release that bound its role by hand keeps that binding.
def test_a_hand_set_annotation_wins(tmp_path):
    # Annotate a different role by hand, in a values file: --set splits the
    # annotation's dots into keys.
    values = tmp_path / "annotations-values.yaml"
    values.write_text(
        dump(
            {
                "agw": {
                    "serviceAccount": {
                        "annotations": {"eks.amazonaws.com/role-arn": "manual"}
                    }
                }
            }
        )
    )

    # Render it beside irsa.
    docs = template(f"--set agw.workloadIdentity.aws.irsa={ROLE} --values {values}")

    # The hand-set role is the one on the service account.
    annotations = _service_account_annotations(docs)
    assert annotations["eks.amazonaws.com/role-arn"] == "manual"


# Outside EKS the gateway assumes the role with a projected token: both
# containers that reach the store mount it and are told where it is, and no
# other container sees it.
def test_oidc_role_projects_a_token_into_the_store_containers():
    # Render with an OIDC role.
    docs = template(f"--set agw.workloadIdentity.aws.oidc.role={ROLE}")
    spec = _pod_spec(docs)

    # The token is projected for STS's default audience.
    (volume,) = [v for v in spec["volumes"] if v["name"] == TOKEN_VOLUME]
    (source,) = volume["projected"]["sources"]
    assert source["serviceAccountToken"]["audience"] == "sts.amazonaws.com"

    # Only the store containers mount it, and they point the SDK at it.
    for container in spec["initContainers"] + spec["containers"]:
        mounts = {m["name"] for m in container.get("volumeMounts", [])}
        env = {e["name"]: e.get("value") for e in container.get("env", [])}
        if container["name"] in STORE_CONTAINERS:
            assert TOKEN_VOLUME in mounts
            assert env["AWS_ROLE_ARN"] == ROLE
            assert env["AWS_WEB_IDENTITY_TOKEN_FILE"] == TOKEN_PATH
        else:
            assert TOKEN_VOLUME not in mounts
            assert "AWS_ROLE_ARN" not in env


# Without an OIDC role nothing is projected, and the audience setting is inert.
def test_no_oidc_role_projects_nothing():
    # Render with an audience but no role.
    docs = template("--set agw.workloadIdentity.aws.oidc.audience=custom")

    # No token volume is rendered.
    volumes = {v["name"] for v in _pod_spec(docs)["volumes"]}
    assert TOKEN_VOLUME not in volumes


# The AWS SDK takes a static key or IRSA ahead of the web identity token, so an
# OIDC role beside either would silently go unused: the chart refuses it.
@pytest.mark.parametrize(
    "extra_args,message",
    [
        (
            f"--set agw.workloadIdentity.aws.irsa={ROLE}",
            "must not be combined with 'agw.workloadIdentity.aws.irsa'",
        ),
        (
            (
                "--set secretStore.aws.access_key.access_key_id=AKIA "
                "--set secretStore.aws.access_key.secret_access_key=secret"
            ),
            "must not be combined with 'secretStore.aws.access_key'",
        ),
    ],
)
def test_oidc_role_beside_another_aws_credential_fails(extra_args, message):
    # Render the OIDC role beside the other credential: helm refuses.
    stderr = _template_error(
        f"--set agw.workloadIdentity.aws.oidc.role={ROLE} {extra_args}"
    )
    assert message in stderr
