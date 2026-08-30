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
NAMES_ENV = "ZAZU_WEBHOOK_NAMES"
CONFIG_NAME_ENV = "ZAZU_WEBHOOK_CONFIG_NAME"


def _template(extra_args="", trace_err=True):
    args = (
        f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
    )
    out = bash(f"helm template {args} {extra_args} {CHART}", traceErr=trace_err)
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _webhook_config(docs):
    configs = [doc for doc in docs if doc["kind"] == "MutatingWebhookConfiguration"]
    assert len(configs) == 1
    return configs[0]


def _admission_controller_service_account(docs):
    for doc in docs:
        if doc["kind"] != "Deployment":
            continue
        spec = doc["spec"]["template"]["spec"]
        if any(c["name"] == "admission-controller" for c in spec["containers"]):
            return spec["serviceAccountName"]
    raise AssertionError("no admission-controller container found")


def _admission_controller_container(docs):
    for doc in docs:
        if doc["kind"] != "Deployment":
            continue
        for container in doc["spec"]["template"]["spec"]["containers"]:
            if container["name"] == "admission-controller":
                return container
    raise AssertionError("no admission-controller container found")


def _admission_controller_env(docs):
    for doc in docs:
        if doc["kind"] != "Deployment":
            continue
        for container in doc["spec"]["template"]["spec"]["containers"]:
            if container["name"] == "admission-controller":
                return {
                    var["name"]: var.get("value") for var in container.get("env", [])
                }
    raise AssertionError("no admission-controller container found")


# zazu patches caBundle by entry name. A name it sends that the configuration
# does not have makes the API server reject the whole patch, so nothing is
# published; an entry the configuration has but zazu is not told about silently
# keeps no caBundle. Both are fail-open, so the two lists must agree exactly.
@pytest.mark.parametrize("diagnostics", [True, False])
def test_webhook_names_env_matches_the_rendered_entries(diagnostics):
    docs = _template(f"--set diagnostics.enabled={str(diagnostics).lower()}")
    rendered = [webhook["name"] for webhook in _webhook_config(docs)["webhooks"]]
    env = _admission_controller_env(docs)

    assert env[NAMES_ENV].split(",") == rendered


def test_webhook_config_name_env_matches_the_rendered_object():
    docs = _template()

    assert (
        _admission_controller_env(docs)[CONFIG_NAME_ENV]
        == _webhook_config(docs)["metadata"]["name"]
    )


# The common ClusterRole is also bound to the spire-agent DaemonSet.
def test_webhook_patch_is_granted_only_to_the_access_manager():
    docs = _template()
    granting_roles = {
        doc["metadata"]["name"]
        for doc in docs
        if doc["kind"] in ("ClusterRole", "Role")
        for rule in doc.get("rules") or []
        if "mutatingwebhookconfigurations" in (rule.get("resources") or [])
        and "patch" in rule["verbs"]
    }
    subjects = {
        subject["name"]
        for doc in docs
        if doc["kind"] in ("ClusterRoleBinding", "RoleBinding")
        and doc["roleRef"]["name"] in granting_roles
        for subject in doc["subjects"]
    }

    assert subjects == {_admission_controller_service_account(docs)}


# /livez fails when the served certificate stops verifying, so only liveness may
# use it: this pod also backs the Service's REST and spire ports, and readiness
# failing would remove all of them from the endpoints.
def test_only_liveness_probes_the_certificate():
    container = _admission_controller_container(_template())

    assert container["livenessProbe"]["httpGet"]["path"] == "/livez"
    assert container["readinessProbe"]["httpGet"]["path"] == "/health"
    assert container["startupProbe"]["httpGet"]["path"] == "/health"


# The controller resolves the namespace of its CA secret from this variable and
# requires it, so a hardcoded value would send it looking in a namespace it does
# not run in, where every read is denied by RBAC. Both names carry it while
# consumers move to the generic one.
@pytest.mark.parametrize("name", ["MUFASA_K8S_NAMESPACE", "HUSH_K8S_NAMESPACE"])
def test_namespace_env_comes_from_the_downward_api(name):
    container = _admission_controller_container(_template())
    env = {var["name"]: var for var in container["env"]}

    field_ref = env[name]["valueFrom"]["fieldRef"]

    assert field_ref["fieldPath"] == "metadata.namespace"


def _publisher_binding(docs):
    for doc in docs:
        if doc["kind"] != "ClusterRoleBinding":
            continue
        if doc["roleRef"]["name"].endswith("-webhook-publisher-cluster-role"):
            return doc["metadata"]["name"]
    raise AssertionError("no webhook-publisher ClusterRoleBinding found")


# ClusterRoleBindings are cluster-scoped, so two releases sharing one name
# collide: whichever applies last owns it, and its roleRef grants patch to only
# one release's ServiceAccount. The other loses it silently.
def test_webhook_publisher_binding_is_release_qualified():
    assert _publisher_binding(_template("rel-a")) != _publisher_binding(
        _template("rel-b")
    )


def test_healthcheck_entry_is_only_rendered_with_diagnostics():
    with_diag = _template("--set diagnostics.enabled=true")
    without_diag = _template("--set diagnostics.enabled=false")

    assert len(_webhook_config(with_diag)["webhooks"]) == 2
    assert len(_webhook_config(without_diag)["webhooks"]) == 1


def _pods_entry(docs):
    for hook in _webhook_config(docs)["webhooks"]:
        if any("pods" in rule["resources"] for rule in hook["rules"]):
            return hook
    raise AssertionError("no pods webhook entry found")


def _healthcheck_entry(docs):
    for hook in _webhook_config(docs)["webhooks"]:
        if any("leases" in rule["resources"] for rule in hook["rules"]):
            return hook
    raise AssertionError("no healthcheck webhook entry found")


# A "helm upgrade --reuse-values" carries no value for a key the new chart adds,
# so the key arrives unset rather than empty and must still render.
def test_failure_policy_defaults_to_ignore_when_unset():
    docs = _template("--set admissionController.failurePolicy=null")

    assert _pods_entry(docs)["failurePolicy"] == "Ignore"


# The healthcheck entry carries diag's lease probe. Failing it closed would
# block diag whenever the access manager is down, so it stays Ignore.
def test_failure_policy_fail_reaches_the_pods_entry_alone():
    docs = _template("--set admissionController.failurePolicy=Fail")

    assert _pods_entry(docs)["failurePolicy"] == "Fail"
    assert _healthcheck_entry(docs)["failurePolicy"] == "Ignore"


def test_failure_policy_rejects_an_unknown_value():
    with pytest.raises(subprocess.CalledProcessError) as err:
        _template("--set admissionController.failurePolicy=fail", trace_err=False)

    assert "must be one of [Ignore Fail]" in err.value.stderr


# Fail with the release namespace in the webhook's scope rejects the CREATE of
# the access-manager pod that serves that webhook, so the release never starts
# and no retry recovers it.
def test_failure_policy_fail_requires_the_release_namespace_out_of_scope():
    with pytest.raises(subprocess.CalledProcessError) as err:
        _template(
            "--set admissionController.failurePolicy=Fail"
            " --set admissionController.namespaceSelector.type=none",
            trace_err=False,
        )

    assert "would let the webhook be invoked" in err.value.stderr


# An objectSelector on a label the access manager's own pod does not carry keeps
# it out of scope just as well, so it is accepted in place of the namespace one.
def test_failure_policy_fail_accepts_an_object_selector_instead():
    docs = _template(
        "--set admissionController.failurePolicy=Fail"
        " --set admissionController.namespaceSelector.type=none"
        " --set admissionController.objectSelector.type=labels"
        " --set admissionController.objectSelector.labels."
        "am\\\\.hush\\\\.security/admission=true"
    )

    assert _pods_entry(docs)["failurePolicy"] == "Fail"


# The objectSelector escape only works on a label the access manager's own pod
# does not carry: it lives in the release namespace, so selecting it puts the
# deadlock back.
def test_failure_policy_fail_rejects_a_selector_the_manager_pod_matches():
    with pytest.raises(subprocess.CalledProcessError) as err:
        _template(
            "--set admissionController.failurePolicy=Fail"
            " --set admissionController.namespaceSelector.type=none"
            " --set admissionController.objectSelector.type=labels"
            " --set admissionController.objectSelector.labels."
            "app\\\\.kubernetes\\\\.io/managed-by=Helm",
            trace_err=False,
        )

    assert "would let the webhook be invoked" in err.value.stderr


# not_labels renders DoesNotExist, which selects the access manager's pod
# precisely because it does not carry the key, so it is no escape at all.
def test_failure_policy_fail_rejects_a_not_labels_selector():
    with pytest.raises(subprocess.CalledProcessError) as err:
        _template(
            "--set admissionController.failurePolicy=Fail"
            " --set admissionController.namespaceSelector.type=none"
            " --set admissionController.objectSelector.type=not_labels"
            " --set admissionController.objectSelector.labels.skip=",
            trace_err=False,
        )

    assert "would let the webhook be invoked" in err.value.stderr


# A custom selector cannot be read from a template, so it is taken as deliberate.
def test_failure_policy_fail_accepts_a_custom_selector():
    docs = _template(
        "--set admissionController.failurePolicy=Fail"
        " --set admissionController.namespaceSelector.type=custom"
        " --set admissionController.namespaceSelector.custom.matchLabels.x=y"
    )

    assert _pods_entry(docs)["failurePolicy"] == "Fail"


# A label the access manager's Pod does not carry at all keeps it out of scope,
# whatever value the selector asks for -- an empty one included, which compares
# equal to an absent label unless the key itself is checked.
def test_failure_policy_fail_accepts_an_empty_valued_label():
    docs = _template(
        "--set admissionController.failurePolicy=Fail"
        " --set admissionController.namespaceSelector.type=none"
        " --set admissionController.objectSelector.type=labels"
        " --set admissionController.objectSelector.labels."
        "am\\.hush\\.security/admission="
    )

    assert _pods_entry(docs)["failurePolicy"] == "Fail"
