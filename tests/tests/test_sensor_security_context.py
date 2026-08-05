import base64
import os
import subprocess
import pytest
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.process import bash

TOP_DIR = os.environ["TOP_DIR"]
CHART = os.path.join(TOP_DIR, "charts", "hush-sensor")
CI_DIR = os.path.join(CHART, "ci")

DUMMY_TOKEN = base64.b64encode(b"d1:zone:realm:org-id:deployment-id").decode()
DEFAULT_CAPABILITIES = [
    "SYS_ADMIN",
    "BPF",
    "PERFMON",
    "SYS_PTRACE",
    "SYS_RESOURCE",
    "DAC_READ_SEARCH",
    "DAC_OVERRIDE",
    "SETUID",
    "SETGID",
]
UNCONFINED = "Unconfined"
SPC_T = "spc_t"


def _template(values_file=None, extra_args="", kube_version=None, trace_err=True):
    args = (
        f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
    )
    if values_file:
        args += f" -f {os.path.join(CI_DIR, values_file)}"
    if kube_version:
        args += f" --kube-version {kube_version}"
    out = bash(f"helm template {args} {extra_args} {CHART}", traceErr=trace_err)
    return [doc for doc in load_all(out, Loader=Loader) if doc]


def _daemonset(docs):
    daemonsets = [d for d in docs if d.get("kind") == "DaemonSet"]
    assert len(daemonsets) == 1
    return daemonsets[0]


def _security_context(docs, container_name):
    containers = _daemonset(docs)["spec"]["template"]["spec"]["containers"]
    container = next(c for c in containers if c["name"] == container_name)
    return container.get("securityContext")


def _sensor_security_context(docs):
    return _security_context(docs, "hush-sensor")


def test_privileged_by_default():
    sc = _sensor_security_context(_template())
    assert sc["privileged"] is True
    assert "capabilities" not in sc


def test_privileged_mode_off_uses_the_capability_set():
    sc = _sensor_security_context(_template("sensor-capabilities-values.yaml"))
    assert "privileged" not in sc
    assert sc["capabilities"]["add"] == DEFAULT_CAPABILITIES
    # The set is additive: the runtime's default capabilities are kept.
    assert "drop" not in sc["capabilities"]


def test_capabilities_are_overridable():
    sc = _sensor_security_context(_template("sensor-custom-capabilities-values.yaml"))
    assert sc["capabilities"]["add"] == ["SYS_ADMIN", "SYS_PTRACE", "DAC_READ_SEARCH"]
    # The SELinux type is not part of the values: it stays spc_t.
    assert sc["seLinuxOptions"]["type"] == SPC_T


@pytest.mark.parametrize("values_file", [None, "sensor-capabilities-values.yaml"])
def test_seccomp_and_apparmor_are_unconfined_in_both_modes(values_file):
    sc = _sensor_security_context(_template(values_file))
    assert sc["seccompProfile"]["type"] == UNCONFINED
    assert sc["appArmorProfile"]["type"] == UNCONFINED


def test_selinux_type_is_set_only_in_capability_mode():
    # A privileged container is given spc_t by the runtime anyway; only a
    # capability-scoped one would otherwise run as container_t.
    privileged = _template()
    assert "seLinuxOptions" not in _sensor_security_context(privileged)
    capability = _template("sensor-capabilities-values.yaml")
    assert _sensor_security_context(capability)["seLinuxOptions"]["type"] == SPC_T


@pytest.mark.parametrize("kube_version", ["1.30.0", "1.31.0"])
def test_apparmor_unconfined_on_both_kube_paths(kube_version):
    # Pre-1.31 AppArmor is expressed as a pod annotation, 1.31+ as a field.
    docs = _template(kube_version=kube_version)
    annotations = _daemonset(docs)["spec"]["template"]["metadata"].get(
        "annotations", {}
    )
    profile = _sensor_security_context(docs).get("appArmorProfile")
    if kube_version == "1.30.0":
        assert (
            annotations["container.apparmor.security.beta.kubernetes.io/hush-sensor"]
            == "unconfined"
        )
        assert profile is None
    else:
        assert profile == {"type": UNCONFINED}
        assert not any("apparmor" in key for key in annotations)


def test_java_probing_does_not_change_the_capability_set():
    # The set is flat: disabling Java probing must not alter it.
    base = _sensor_security_context(_template("sensor-capabilities-values.yaml"))
    docs = _template(
        "sensor-capabilities-values.yaml",
        extra_args="--set daemonSet.disableJavaProbing=true",
    )
    assert _sensor_security_context(docs)["capabilities"] == base["capabilities"]


@pytest.mark.parametrize(
    "capabilities,expected",
    [
        # '--set x=[]' assigns the string '[]', and '--set x={}' the list [""],
        # so neither reaches the template as an empty list - both are still
        # unusable and must be refused rather than rendered.
        ("[]", "must be a list"),
        ("{}", "must not contain empty entries"),
        ("SYS_ADMIN", "must be a list"),
        # A falsy scalar is the wrong kind, not an empty list - reporting it as
        # empty would point at the wrong fix.
        ("0", "must be a list"),
        ("false", "must be a list"),
        ("null", "must not be empty"),
        # Kubernetes prepends 'CAP_' itself; passing it through would silently
        # request the non-existent CAP_CAP_SYS_ADMIN.
        ("{CAP_SYS_ADMIN}", "drop the 'CAP_' prefix"),
    ],
)
def test_unusable_capabilities_fail_the_render(capabilities, expected):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(
            "sensor-capabilities-values.yaml",
            extra_args=f"--set 'daemonSet.capabilities={capabilities}'",
            trace_err=False,
        )
    assert expected in excinfo.value.stderr


def test_empty_capability_list_fails_the_render(tmp_path):
    values = tmp_path / "empty-caps.yaml"
    values.write_text("daemonSet:\n  privilegedMode: false\n  capabilities: []\n")
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(extra_args=f"-f {values}", trace_err=False)
    assert "must not be empty" in excinfo.value.stderr


def test_capabilities_are_not_validated_in_privileged_mode(tmp_path):
    # privilegedMode renders no 'add:', so an unusable list must not fail it.
    values = tmp_path / "priv-bad-caps.yaml"
    values.write_text("daemonSet:\n  privilegedMode: true\n  capabilities: []\n")
    sc = _sensor_security_context(_template(extra_args=f"-f {values}"))
    assert sc["privileged"] is True


@pytest.mark.parametrize(
    "extra_args",
    [
        # A quoted value is truthy in a template, so refusing it is what keeps
        # 'privilegedMode: "false"' from rendering a privileged container.
        "--set-string daemonSet.privilegedMode=false",
        "--set-string daemonSet.privilegedMode=true",
        "--set daemonSet.privilegedMode=0",
        "--set daemonSet.privilegedMode=null",
    ],
)
def test_non_boolean_privileged_mode_fails_the_render(extra_args):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _template(extra_args=extra_args, trace_err=False)
    assert "must be a boolean" in excinfo.value.stderr


def test_selinux_type_is_hardcoded():
    # Not a value: a stray 'daemonSet.seLinuxType' must not change the domain.
    sc = _sensor_security_context(
        _template(
            "sensor-capabilities-values.yaml",
            extra_args="--set-string daemonSet.seLinuxType=container_t",
        )
    )
    assert sc["seLinuxOptions"]["type"] == SPC_T
