import subprocess
import pytest
from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"

# asserted by name, so a container losing the include fails rather than narrows
STORE_CONTAINERS = {"agw-controller-init", "agw-controller"}

VAULT_KUBERNETES = (
    "--set agw.secretStore.kind=hc_vault "
    "--set agw.secretStore.hcVault.address=https://vault.example.com:8200 "
    "--set agw.secretStore.hcVault.auth.role=hush-agw"
)

KEY_VAULT = (
    "--set agw.secretStore.kind=az_key_vault "
    "--set agw.secretStore.azKeyVault.vaultUrl=https://acme.vault.azure.net"
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
        "--namespace gw-ns --set agw.secretStore.k8s.namespace=silo-ns",
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
            "--set agw.secretStore.kind=awssm --set agw.secretStore.aws.region=eu-central-1",
            {"SILO_KIND": "awssm", "SILO_AWS_SM_REGION": "eu-central-1"},
        ),
        (
            "--set agw.secretStore.kind=awsssm --set agw.secretStore.aws.region=eu-central-1",
            {"SILO_KIND": "awsssm", "SILO_AWS_SSM_REGION": "eu-central-1"},
        ),
        (
            "--set agw.secretStore.kind=gcpsm --set agw.secretStore.gcp.projectId=my-project",
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
        (
            KEY_VAULT,
            {
                "SILO_KIND": "az_key_vault",
                "SILO_AZ_KEY_VAULT_VAULT_URL": "https://acme.vault.azure.net",
                "SILO_AZ_KEY_VAULT_AUTH_METHOD": "default",
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
        "--set agw.secretStore.kind=hc_vault "
        "--set agw.secretStore.hcVault.address=https://vault.example.com:8200 "
        "--set agw.secretStore.hcVault.auth.method=token "
        "--set agw.secretStore.hcVault.auth.token=dummy"
    )
    volumes = {volume["name"] for volume in _pod_spec(docs)["volumes"]}
    assert "hc-vault-token-projection" not in volumes


# Simulates a service principal whose secret is kept in an existing Secret:
# both containers that reach the vault read it from there, and no other
# container is given it.
def test_key_vault_client_secret_is_read_from_the_secret_named():
    # Render with the client_secret method and a Secret reference.
    docs = template(
        f"{KEY_VAULT} "
        "--set agw.secretStore.azKeyVault.auth.method=client_secret "
        "--set agw.secretStore.azKeyVault.auth.tenantId=tenant "
        "--set agw.secretStore.azKeyVault.auth.clientId=client "
        "--set agw.secretStore.azKeyVault.auth.clientSecretRef.name=azure-sp "
        "--set agw.secretStore.azKeyVault.auth.clientSecretRef.key=client-secret"
    )

    # The store containers name the service principal.
    for env in _store_envs(docs):
        assert env["SILO_AZ_KEY_VAULT_AUTH_METHOD"] == "client_secret"
        assert env["SILO_AZ_KEY_VAULT_TENANT_ID"] == "tenant"
        assert env["SILO_AZ_KEY_VAULT_CLIENT_ID"] == "client"

    # Only they take the secret, and from the Secret named.
    for container in _containers(docs):
        refs = [
            var["valueFrom"]["secretKeyRef"]
            for var in container.get("env", [])
            if var["name"] == "SILO_AZ_KEY_VAULT_CLIENT_SECRET"
        ]
        if container["name"] in STORE_CONTAINERS:
            assert refs == [{"name": "azure-sp", "key": "client-secret"}]
        else:
            assert not refs


# The store's settings are validated as hush-am validates them, so a mistake
# fails the install rather than every write afterwards.
@pytest.mark.parametrize(
    "args,message",
    [
        (
            "--set agw.secretStore.kind=awssm",
            "'agw.secretStore.aws.region' must be defined",
        ),
        (
            "--set agw.secretStore.prefix=hush_gw",
            "'agw.secretStore.prefix' is invalid for kind kubesecrets",
        ),
        (
            (
                "--set agw.secretStore.kind=hc_vault "
                "--set agw.secretStore.hcVault.address=http://vault.example.com"
            ),
            "must be an https URL",
        ),
        (
            "--set agw.secretStore.kind=az_key_vault",
            "'agw.secretStore.azKeyVault.vaultUrl' must be defined",
        ),
        (
            f"{KEY_VAULT} --set agw.secretStore.prefix=hush.gw",
            "'agw.secretStore.prefix' is invalid for kind az_key_vault",
        ),
        (
            f"{KEY_VAULT} --set agw.secretStore.azKeyVault.auth.clientId=client",
            "set 'agw.workloadIdentity.azure.clientId'",
        ),
        (
            "--set agw.secretStore.kind=nosuchkind",
            "invalid secret store kind",
        ),
    ],
)
def test_invalid_store_settings_fail_the_render(args, message):
    # Render with the invalid setting: helm refuses, naming the setting.
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        template(args, trace_err=False)
    assert message in excinfo.value.stderr
