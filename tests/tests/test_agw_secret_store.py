import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

# asserted by name, so a container losing the include fails rather than narrows
STORE_CONTAINERS = {"agw-controller-init", "agw-controller"}

VAULT_KUBERNETES = (
    "--set secretStore.kind=hc_vault "
    "--set secretStore.hcVault.address=https://vault.example.com:8200 "
    "--set secretStore.hcVault.auth.role=hush-agw"
)


def template(extra_args="", trace_err=True):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART, trace_err=trace_err)


def _pod_spec(docs):
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    return deployment["spec"]["template"]["spec"]


def _containers(docs):
    spec = _pod_spec(docs)
    return spec["initContainers"] + spec["containers"]


def _store_envs(docs):
    found = {}
    for container in _containers(docs):
        env = {var["name"]: var.get("value") for var in container.get("env", [])}
        if "SILO_KIND" in env:
            found[container["name"]] = env
    assert set(found) == STORE_CONTAINERS, (
        f"containers carrying SILO_KIND changed: {sorted(found)}"
    )
    return list(found.values())


def _rbac(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


# The default store keeps the keys as Secrets in the install namespace: both
# agent-warden containers are told so, and the gateway may manage Secrets there,
# with the verbs the store uses and no more.
def test_default_store_is_kubesecrets_in_the_install_namespace():
    # Render the chart with its defaults.
    docs = template("--namespace gw-ns")

    # Both agent-warden containers name the store and its namespace.
    for env in _store_envs(docs):
        assert env["SILO_KIND"] == "kubesecrets"
        assert env["SILO_NAMESPACE_PREFIX"] == "hush"
        assert env["SILO_K8S_NAMESPACE"] == "gw-ns"

    # A Role in the install namespace grants the store's verbs on Secrets.
    (role,) = _rbac(docs, "Role")
    assert role["metadata"]["namespace"] == "gw-ns"
    assert role["rules"] == [
        {
            "apiGroups": [""],
            "resources": ["secrets"],
            "verbs": ["get", "create", "update", "delete"],
        }
    ]

    # The binding hands that Role to the gateway's service account.
    (binding,) = _rbac(docs, "RoleBinding")
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    (subject,) = binding["subjects"]
    assert subject["namespace"] == "gw-ns"


# Simulates a store placed in a namespace of its own: the grant moves there, and
# the binding still names the service account in the install namespace.
def test_kubesecrets_in_another_namespace_is_granted_there():
    # Render with the store in another namespace.
    docs = template(
        "--namespace gw-ns --set secretStore.k8s.namespace=silo-ns",
    )

    # The containers write there.
    for env in _store_envs(docs):
        assert env["SILO_K8S_NAMESPACE"] == "silo-ns"

    # The Role and its binding live there, bound to the install namespace's
    # service account.
    (role,) = _rbac(docs, "Role")
    (binding,) = _rbac(docs, "RoleBinding")
    assert role["metadata"]["namespace"] == "silo-ns"
    assert binding["metadata"]["namespace"] == "silo-ns"
    assert binding["subjects"][0]["namespace"] == "gw-ns"


# A store outside the cluster needs no access to Secrets, so the chart grants
# none, and the containers are pointed at the store instead.
@pytest.mark.parametrize(
    "args,expected",
    [
        (
            "--set secretStore.kind=awssm --set secretStore.aws.region=eu-central-1",
            {"SILO_KIND": "awssm", "SILO_AWS_SM_REGION": "eu-central-1"},
        ),
        (
            "--set secretStore.kind=awsssm --set secretStore.aws.region=eu-central-1",
            {"SILO_KIND": "awsssm", "SILO_AWS_SSM_REGION": "eu-central-1"},
        ),
        (
            "--set secretStore.kind=gcpsm --set secretStore.gcp.projectId=my-project",
            {"SILO_KIND": "gcpsm", "SILO_GCP_SM_PROJECT": "my-project"},
        ),
        (
            VAULT_KUBERNETES,
            {
                "SILO_KIND": "hc_vault",
                "SILO_HC_VAULT_ADDRESS": "https://vault.example.com:8200",
                "SILO_HC_VAULT_AUTH_METHOD": "kubernetes",
                "SILO_HC_VAULT_ROLE": "hush-agw",
            },
        ),
    ],
)
def test_store_outside_the_cluster_gets_no_secret_access(args, expected):
    # Render with the store.
    docs = template(args)

    # Both containers carry its settings.
    for env in _store_envs(docs):
        assert expected.items() <= env.items()

    # No Role or RoleBinding is rendered.
    assert not _rbac(docs, "Role")
    assert not _rbac(docs, "RoleBinding")


# A Vault login presents a projected service account token: both containers
# that log in mount it, and are told where it is. A token login projects none.
def test_vault_login_token_is_projected_into_both_containers():
    # Render with a kubernetes login.
    docs = template(VAULT_KUBERNETES)

    # The pod projects the token, and both containers mount it and point at it.
    volumes = {volume["name"] for volume in _pod_spec(docs)["volumes"]}
    assert "hc-vault-token-projection" in volumes
    for container in _containers(docs):
        mounts = {mount["name"] for mount in container.get("volumeMounts", [])}
        projected = "hc-vault-token-projection" in mounts
        assert projected == (container["name"] in STORE_CONTAINERS)
    for env in _store_envs(docs):
        assert env["SILO_HC_VAULT_SA_TOKEN_FILE"].endswith("/sa-token")

    # Render with a token login instead: nothing is projected.
    docs = template(
        "--set secretStore.kind=hc_vault "
        "--set secretStore.hcVault.address=https://vault.example.com:8200 "
        "--set secretStore.hcVault.auth.method=token "
        "--set secretStore.hcVault.auth.token=dummy"
    )
    volumes = {volume["name"] for volume in _pod_spec(docs)["volumes"]}
    assert "hc-vault-token-projection" not in volumes


# The store's settings are validated as hush-am validates them, so a mistake
# fails the install rather than every write afterwards.
@pytest.mark.parametrize(
    "args,message",
    [
        (
            "--set secretStore.kind=awssm",
            "'secretStore.aws.region' must be defined",
        ),
        (
            "--set secretStore.prefix=hush_gw",
            "'secretStore.prefix' is invalid for kind kubesecrets",
        ),
        (
            (
                "--set secretStore.kind=hc_vault "
                "--set secretStore.hcVault.address=http://vault.example.com"
            ),
            "must be an https URL",
        ),
        (
            "--set secretStore.kind=nosuchkind",
            "invalid secret store kind",
        ),
    ],
)
def test_invalid_store_settings_fail_the_render(args, message):
    # Render with the invalid setting: helm refuses, naming the setting.
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        template(args, trace_err=False)
    assert message in excinfo.value.stderr
