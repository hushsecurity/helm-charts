import base64
import os
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.process import bash

TOP_DIR = os.environ["TOP_DIR"]
CHART = os.path.join(TOP_DIR, "charts", "hush-sensor")
CI_DIR = os.path.join(CHART, "ci")

# The OpenShift resources are gated on this API group being advertised as
# available; 'helm template' only reports it when told to via --api-versions.
OPENSHIFT_API = "security.openshift.io/v1"
DUMMY_TOKEN = base64.b64encode(b"d1:zone:realm:org-id:deployment-id").decode()
SCC_PRIVILEGED = "system:openshift:scc:privileged"
SCC_ANYUID = "system:openshift:scc:anyuid"
LABEL_IMAGE_OVERRIDE = "registry.example.com/hush/oc:latest"


def _template(values_file, with_capability=True):
    args = (
        f"--set hushDeployment.token={DUMMY_TOKEN}"
        f" --set hushDeployment.password=dummy"
        f" -f {os.path.join(CI_DIR, values_file)}"
    )
    if with_capability:
        args += f" --api-versions {OPENSHIFT_API}"
    out = bash(f"helm template {args} {CHART}")
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _of_kind(docs, kind):
    return [d for d in docs if d.get("kind") == kind]


def _scc_bindings(docs):
    return [
        rb
        for rb in _of_kind(docs, "RoleBinding")
        if rb.get("roleRef", {}).get("name", "").startswith("system:openshift:scc:")
    ]


def _psa_job(docs):
    jobs = [
        j for j in _of_kind(docs, "Job") if j["metadata"]["name"].endswith("-psa-label")
    ]
    return jobs[0] if jobs else None


def test_openshift_resources_absent_without_capability():
    docs = _template("openshift-values.yaml", with_capability=False)
    assert _scc_bindings(docs) == []
    assert _psa_job(docs) is None


def test_openshift_disabled_gates_resources_off():
    docs = _template("openshift-disabled-values.yaml")
    assert _scc_bindings(docs) == []
    assert _psa_job(docs) is None


def test_scc_rolebindings_grant_expected_sccs():
    bindings = _scc_bindings(_template("openshift-values.yaml"))
    sccs = sorted(rb["roleRef"]["name"] for rb in bindings)
    # sensor DaemonSet SA -> privileged; sentry/vermon/connector SAs -> anyuid.
    assert sccs == [SCC_ANYUID, SCC_ANYUID, SCC_ANYUID, SCC_PRIVILEGED]
    for rb in bindings:
        assert rb["roleRef"]["kind"] == "ClusterRole"
        assert [s["kind"] for s in rb["subjects"]] == ["ServiceAccount"]


def test_psa_label_hook_job_is_restricted_compliant():
    job = _psa_job(_template("openshift-values.yaml"))
    assert job is not None
    pod = job["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    container = pod["containers"][0]
    sc = container["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"]["drop"] == ["ALL"]
    command = " ".join(container["command"])
    for mode in ("enforce", "warn", "audit"):
        assert f"pod-security.kubernetes.io/{mode}=privileged" in command


def test_psa_label_hook_rbac_is_namespace_scoped():
    docs = _template("openshift-values.yaml")
    roles = [
        c for c in _of_kind(docs, "ClusterRole") if "psa-label" in c["metadata"]["name"]
    ]
    assert len(roles) == 1
    rule = roles[0]["rules"][0]
    assert rule["resources"] == ["namespaces"]
    assert sorted(rule["verbs"]) == ["get", "patch"]
    # resourceNames limits the grant to the single install namespace.
    assert len(rule["resourceNames"]) == 1


def test_namespace_label_image_is_overridable():
    job = _psa_job(_template("openshift-custom-label-image-values.yaml"))
    assert (
        job["spec"]["template"]["spec"]["containers"][0]["image"]
        == LABEL_IMAGE_OVERRIDE
    )
