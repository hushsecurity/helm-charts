import subprocess
import pytest
from common.chart import template as _template

VAULT_BASE = (
    "--set secretStore.kind=hc_vault "
    "--set secretStore.hcVault.address=https://vault.example.com:8200"
)
SA_TOKEN_PATH = "/var/run/secrets/hush.k8s.hc_vault.projection/sa-token"
SA_TOKEN_VOLUME = "hc-vault-token-projection"


def _template_error(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(extra_args, trace_err=False)
    return excinfo.value.stderr


def _pod_specs(docs):
    for doc in docs:
        if doc["kind"] in ("Deployment", "StatefulSet"):
            yield doc["spec"]["template"]["spec"]


# The containers the secret store config reaches. Asserted by name rather than
# by count alone: every test here iterates over what this returns, so a
# container losing `include "hush-am.siloEnvs"` would otherwise narrow the
# whole suite silently instead of failing it.
STORE_CONTAINERS = {
    "access-manager-init",
    "spire-server",
    "access-manager",
    "diag",
}


def _store_containers(docs):
    found = []
    for spec in _pod_specs(docs):
        for container in spec.get("initContainers", []) + spec["containers"]:
            env = {var["name"]: var for var in container.get("env", [])}
            if "SILO_KIND" in env:
                found.append((spec, container, env))
    names = {container["name"] for _, container, _ in found}
    assert names == STORE_CONTAINERS, (
        f"containers carrying SILO_KIND changed: {sorted(names)}"
    )
    return found


def _values(env):
    return {name: var.get("value") for name, var in env.items()}


def _vault_env(env):
    return {name for name in env if name.startswith("SILO_HC_VAULT_")}


def _assert_mounts_the_token(spec, container):
    mounts = {m["name"]: m for m in container["volumeMounts"]}
    assert SA_TOKEN_VOLUME in mounts, container["name"]
    assert SA_TOKEN_PATH.startswith(mounts[SA_TOKEN_VOLUME]["mountPath"] + "/")
    assert mounts[SA_TOKEN_VOLUME]["readOnly"]
    volumes = {v["name"]: v for v in spec["volumes"]}
    assert SA_TOKEN_VOLUME in volumes
    source = volumes[SA_TOKEN_VOLUME]["projected"]["sources"][0]
    assert source["serviceAccountToken"]["path"] == "sa-token"


@pytest.mark.parametrize("method", ["kubernetes", "jwt"])
def test_jwt_methods_wire_the_role_and_the_projected_token(method):
    docs = _template(
        f"{VAULT_BASE} --set secretStore.hcVault.auth.method={method} "
        "--set secretStore.hcVault.auth.role=hush-am"
    )

    for _, _, env in _store_containers(docs):
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
        f"{VAULT_BASE} --set secretStore.hcVault.auth.method={method} "
        "--set secretStore.hcVault.auth.role=hush-am"
    )

    for spec, container, env in _store_containers(docs):
        assert _values(env)["SILO_HC_VAULT_SA_TOKEN_FILE"] == SA_TOKEN_PATH
        _assert_mounts_the_token(spec, container)


# Projected on its own: the audience Vault accepts is the operator's choice.
def test_the_audience_is_requested_only_when_asked_for():
    role = "--set secretStore.hcVault.auth.role=hush-am"
    unset = _template(f"{VAULT_BASE} {role}")
    named = _template(
        f"{VAULT_BASE} {role} --set secretStore.hcVault.auth.audience=vault"
    )

    for docs, expected in ((unset, None), (named, "vault")):
        for spec, _, _ in _store_containers(docs):
            volumes = {v["name"]: v for v in spec["volumes"]}
            source = volumes[SA_TOKEN_VOLUME]["projected"]["sources"][0]
            assert source["serviceAccountToken"].get("audience") == expected


def test_the_token_method_needs_no_projected_token():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token "
        "--set secretStore.hcVault.auth.token=hvs.example"
    )

    for spec, container, env in _store_containers(docs):
        values = _values(env)
        assert values["SILO_HC_VAULT_AUTH_METHOD"] == "token"
        assert values["SILO_HC_VAULT_TOKEN"] == "hvs.example"
        assert "SILO_HC_VAULT_SA_TOKEN_FILE" not in env
        assert SA_TOKEN_VOLUME not in {m["name"] for m in container["volumeMounts"]}
        assert SA_TOKEN_VOLUME not in {v["name"] for v in spec["volumes"]}


def test_a_named_secret_keeps_the_token_out_of_the_manifest():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token "
        "--set secretStore.hcVault.auth.tokenSecretRef.name=vault-token "
        "--set secretStore.hcVault.auth.tokenSecretRef.key=token"
    )

    for _, _, env in _store_containers(docs):
        secret_ref = env["SILO_HC_VAULT_TOKEN"]["valueFrom"]["secretKeyRef"]
        assert secret_ref == {"name": "vault-token", "key": "token"}
        assert "value" not in env["SILO_HC_VAULT_TOKEN"]


def test_the_optional_settings_are_omitted_rather_than_sent_empty():
    docs = _template(f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am")

    for _, _, env in _store_containers(docs):
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
        f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
        "--set secretStore.hcVault.mount=hush-kv "
        "--set secretStore.hcVault.namespace=admin/team-a "
        "--set secretStore.hcVault.caCert=PEM "
        "--set secretStore.hcVault.timeout=10s "
        "--set secretStore.hcVault.auth.mount=kubernetes-hush"
    )

    for _, _, env in _store_containers(docs):
        values = _values(env)
        assert values["SILO_HC_VAULT_MOUNT"] == "hush-kv"
        assert values["SILO_HC_VAULT_ENTERPRISE_NAMESPACE"] == "admin/team-a"
        assert values["SILO_HC_VAULT_CA_CERT"] == "PEM"
        assert values["SILO_HC_VAULT_TIMEOUT"] == "10s"
        assert values["SILO_HC_VAULT_AUTH_MOUNT"] == "kubernetes-hush"


# The access manager builds a platform-created hc_vault store from the store's
# config plus its own environment. Simulates a deployment whose default store
# is not hc_vault and checks that each process-wide setting still reaches the
# four containers on its own, with nothing of the default hc_vault store.
@pytest.mark.parametrize(
    "extra_args,expected",
    [
        (
            "--set secretStore.hcVault.auth.token=hvs.example",
            {"SILO_HC_VAULT_TOKEN": "hvs.example"},
        ),
        (
            "--set secretStore.hcVault.caCert=PEM",
            {"SILO_HC_VAULT_CA_CERT": "PEM"},
        ),
        (
            "--set secretStore.hcVault.timeout=10s",
            {"SILO_HC_VAULT_TIMEOUT": "10s"},
        ),
        (
            "--set secretStore.hcVault.auth.audience=vault",
            {"SILO_HC_VAULT_SA_TOKEN_FILE": SA_TOKEN_PATH},
        ),
    ],
)
@pytest.mark.parametrize(
    "kind",
    [
        "--set secretStore.kind=kubesecrets",
        "--set secretStore.kind=awsssm --set secretStore.aws.region=eu-central-1",
    ],
)
def test_platform_store_settings_reach_the_containers_whatever_the_kind(
    kind, extra_args, expected
):
    docs = _template(f"{kind} {extra_args}")

    for _, _, env in _store_containers(docs):
        # only the setting given renders, and none of the default store's
        assert _vault_env(env) == set(expected)
        for name, value in expected.items():
            assert _values(env)[name] == value


# A token kept in a Secret takes the same form for a platform-created store as
# for the default one.
def test_a_platform_store_token_can_come_from_a_secret_whatever_the_kind():
    docs = _template(
        "--set secretStore.hcVault.auth.tokenSecretRef.name=vault-token "
        "--set secretStore.hcVault.auth.tokenSecretRef.key=token"
    )

    for _, _, env in _store_containers(docs):
        secret_ref = env["SILO_HC_VAULT_TOKEN"]["valueFrom"]["secretKeyRef"]
        assert secret_ref == {"name": "vault-token", "key": "token"}


# A platform-created kubernetes or jwt store presents the projected token, so
# an audience given on a deployment of another kind must bring the volume and
# the mounts with the variable, exactly as for a default hc_vault store.
def test_an_audience_projects_the_token_whatever_the_kind():
    docs = _template("--set secretStore.hcVault.auth.audience=vault")

    for spec, container, env in _store_containers(docs):
        assert _values(env)["SILO_HC_VAULT_SA_TOKEN_FILE"] == SA_TOKEN_PATH
        _assert_mounts_the_token(spec, container)
        volumes = {v["name"]: v for v in spec["volumes"]}
        source = volumes[SA_TOKEN_VOLUME]["projected"]["sources"][0]
        assert source["serviceAccountToken"]["audience"] == "vault"


# The default install sets none of the hc_vault values, so it must render
# nothing of Vault at all.
def test_nothing_of_vault_renders_when_nothing_is_set():
    docs = _template()

    for spec, container, env in _store_containers(docs):
        assert not _vault_env(env)
        assert SA_TOKEN_VOLUME not in {m["name"] for m in container["volumeMounts"]}
        assert SA_TOKEN_VOLUME not in {v["name"] for v in spec.get("volumes", [])}


# A default store on kubernetes still leaves the token to the platform-created
# token stores, rather than dropping it.
def test_a_token_rides_beside_a_kubernetes_default_store():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
        "--set secretStore.hcVault.auth.token=hvs.example"
    )

    for spec, container, env in _store_containers(docs):
        values = _values(env)
        assert values["SILO_HC_VAULT_AUTH_METHOD"] == "kubernetes"
        assert values["SILO_HC_VAULT_TOKEN"] == "hvs.example"
        assert values["SILO_HC_VAULT_SA_TOKEN_FILE"] == SA_TOKEN_PATH
        _assert_mounts_the_token(spec, container)


# A default store on token still serves platform-created kubernetes and jwt
# stores, so an audience beside it is accepted and projects the token.
def test_an_audience_is_accepted_beside_a_token_default_store():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token "
        "--set secretStore.hcVault.auth.token=hvs.example "
        "--set secretStore.hcVault.auth.audience=vault"
    )

    for spec, container, env in _store_containers(docs):
        values = _values(env)
        assert values["SILO_HC_VAULT_AUTH_METHOD"] == "token"
        assert values["SILO_HC_VAULT_SA_TOKEN_FILE"] == SA_TOKEN_PATH
        _assert_mounts_the_token(spec, container)


def test_a_capitalised_scheme_is_accepted():
    docs = _template(
        "--set secretStore.kind=hc_vault "
        "--set secretStore.hcVault.address=HTTPS://vault.example.com "
        "--set secretStore.hcVault.auth.role=hush-am"
    )

    for _, _, env in _store_containers(docs):
        assert _values(env)["SILO_HC_VAULT_ADDRESS"] == "HTTPS://vault.example.com"


def test_valid_mounts_reach_the_containers():
    docs = _template(
        f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
        "--set secretStore.hcVault.mount=team-a/hush_kv "
        "--set secretStore.hcVault.auth.mount=jwt/cluster-1"
    )

    for _, _, env in _store_containers(docs):
        values = _values(env)
        assert values["SILO_HC_VAULT_MOUNT"] == "team-a/hush_kv"
        assert values["SILO_HC_VAULT_AUTH_MOUNT"] == "jwt/cluster-1"


# A store that renders and then cannot authenticate leaves the access manager
# retrying against a config that cannot be edited, so each of these must fail
# the install.
@pytest.mark.parametrize(
    "extra_args,message",
    [
        (
            (
                "--set secretStore.kind=hc_vault "
                "--set secretStore.hcVault.auth.role=hush-am"
            ),
            "'secretStore.hcVault.address' must be defined",
        ),
        (
            (
                "--set secretStore.kind=hc_vault "
                "--set secretStore.hcVault.auth.role=hush-am "
                "--set secretStore.hcVault.address=http://vault.example.com"
            ),
            "'secretStore.hcVault.address' must be an https URL",
        ),
        # url.Parse on the access manager's side refuses an empty host
        (
            (
                "--set secretStore.kind=hc_vault "
                "--set secretStore.hcVault.auth.role=hush-am "
                "--set secretStore.hcVault.address=https://"
            ),
            "'secretStore.hcVault.address' must be an https URL with a host",
        ),
        (
            f"{VAULT_BASE} --set secretStore.hcVault.auth.method=approle",
            "'secretStore.hcVault.auth.method' must be one of",
        ),
        (
            VAULT_BASE,
            "'secretStore.hcVault.auth.role' must be defined for the kubernetes",
        ),
        (
            f"{VAULT_BASE} --set secretStore.hcVault.auth.method=jwt",
            "'secretStore.hcVault.auth.role' must be defined for the jwt",
        ),
        (
            f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token",
            (
                "'secretStore.hcVault.auth.token' or "
                "'secretStore.hcVault.auth.tokenSecretRef' must be defined"
            ),
        ),
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token "
                "--set secretStore.hcVault.auth.token=hvs.example "
                "--set secretStore.hcVault.auth.tokenSecretRef.name=vault-token "
                "--set secretStore.hcVault.auth.tokenSecretRef.key=token"
            ),
            "are mutually exclusive",
        ),
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token "
                "--set secretStore.hcVault.auth.tokenSecretRef.name=vault-token"
            ),
            "'secretStore.hcVault.auth.tokenSecretRef.key' must be defined",
        ),
        # a field belonging to another method is refused, not ignored: it
        # usually means the wrong method was named
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token "
                "--set secretStore.hcVault.auth.token=hvs.example "
                "--set secretStore.hcVault.auth.role=hush-am"
            ),
            "'secretStore.hcVault.auth.role' does not apply to the token auth method",
        ),
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.method=token "
                "--set secretStore.hcVault.auth.token=hvs.example "
                "--set secretStore.hcVault.auth.mount=kubernetes"
            ),
            "'secretStore.hcVault.auth.mount' does not apply to the token auth method",
        ),
        # time.ParseDuration on the access manager's side refuses a bare number
        # and the access manager refuses a non-positive duration
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
                "--set secretStore.hcVault.timeout=30"
            ),
            "'secretStore.hcVault.timeout' must be a duration with a unit",
        ),
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
                "--set secretStore.hcVault.timeout=0s"
            ),
            "'secretStore.hcVault.timeout' must be positive",
        ),
        # midgard holds both mounts to the same rule, so a mount it would
        # refuse for a store must not reach the default one either
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
                "--set secretStore.hcVault.mount=secret/"
            ),
            "'secretStore.hcVault.mount' must be letters, digits",
        ),
        (
            (
                f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
                "--set secretStore.hcVault.auth.mount=../kubernetes"
            ),
            "'secretStore.hcVault.auth.mount' must be letters, digits",
        ),
    ],
)
def test_a_misconfigured_vault_store_fails_the_install(extra_args, message):
    assert message in _template_error(extra_args)


# The process-wide settings are checked whatever the kind, since they render
# whatever the kind. Simulates a deployment whose default store is not hc_vault.
@pytest.mark.parametrize(
    "extra_args,message",
    [
        (
            (
                "--set secretStore.hcVault.auth.token=hvs.example "
                "--set secretStore.hcVault.auth.tokenSecretRef.name=vault-token "
                "--set secretStore.hcVault.auth.tokenSecretRef.key=token"
            ),
            "are mutually exclusive",
        ),
        (
            "--set secretStore.hcVault.auth.tokenSecretRef.name=vault-token",
            "'secretStore.hcVault.auth.tokenSecretRef.key' must be defined",
        ),
        (
            "--set secretStore.hcVault.timeout=30",
            "'secretStore.hcVault.timeout' must be a duration with a unit",
        ),
    ],
)
def test_misconfigured_platform_store_settings_fail_the_install(extra_args, message):
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
        # the "dot" rule mirrors midgard's _validate_segment; without a case
        # here, dropping `"dot" true` from the kind's rules leaves this suite
        # green while the chart starts accepting a prefix the API refuses
        ("acme..prod", "must not repeat '.'"),
        ("a" * 81, "exceeds 80 characters"),
    ],
)
def test_an_invalid_vault_prefix_fails_the_install(prefix, message):
    extra_args = (
        f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
        f"--set-string secretStore.prefix={prefix}"
    )

    assert message in _template_error(extra_args)


@pytest.mark.parametrize(
    "prefix", ["acme/prod/eu", "acme__prod", "acme.prod-eu", "a" * 80]
)
def test_a_valid_vault_prefix_reaches_the_containers(prefix):
    docs = _template(
        f"{VAULT_BASE} --set secretStore.hcVault.auth.role=hush-am "
        f"--set-string secretStore.prefix={prefix}"
    )

    for _, _, env in _store_containers(docs):
        assert _values(env)["SILO_NAMESPACE_PREFIX"] == prefix
