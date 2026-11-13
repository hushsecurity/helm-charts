import os
import shutil
import subprocess
import tempfile
import pytest
from common.chart import AGW_CHART, template

HOST = "--set agw.hostname=gw.example.com"
SEVERAL = f"{HOST} --set agw.replicas=3 --set agw.persistence.enabled=false"


def _of_kind(docs, kind):
    return [d for d in docs if d.get("kind") == kind]


def _deployment(docs):
    (deployment,) = _of_kind(docs, "Deployment")
    return deployment


def test_one_replica_renders_as_before():
    docs = template(HOST, chart=AGW_CHART)
    spec = _deployment(docs)["spec"]
    assert spec["replicas"] == 1
    assert spec["strategy"] == {"type": "Recreate"}
    assert "topologySpreadConstraints" not in spec["template"]["spec"]
    assert not _of_kind(docs, "PodDisruptionBudget")


def test_one_replica_without_persistence_still_recreates():
    # Rolling one pod over would run two side by side on separate state.
    args = f"{HOST} --set agw.persistence.enabled=false"
    spec = _deployment(template(args, chart=AGW_CHART))["spec"]
    assert spec["strategy"] == {"type": "Recreate"}


def test_several_replicas_roll_one_at_a_time_and_spread():
    docs = template(SEVERAL, chart=AGW_CHART)
    spec = _deployment(docs)["spec"]
    assert spec["replicas"] == 3
    assert spec["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
    }
    spread = spec["template"]["spec"]["topologySpreadConstraints"]
    keys = [c["topologyKey"] for c in spread]
    assert keys == ["topology.kubernetes.io/zone", "kubernetes.io/hostname"]
    (pdb,) = _of_kind(docs, "PodDisruptionBudget")
    assert pdb["spec"]["maxUnavailable"] == 1
    assert pdb["spec"]["selector"] == spec["selector"]


def test_several_replicas_require_persistence_off():
    with pytest.raises(subprocess.CalledProcessError) as e:
        template(f"{HOST} --set agw.replicas=2", chart=AGW_CHART, trace_err=False)
    assert "requires 'agw.persistence.enabled: false'" in e.value.stderr


def test_zero_replicas_fail():
    with pytest.raises(subprocess.CalledProcessError) as e:
        template(f"{HOST} --set agw.replicas=0", chart=AGW_CHART, trace_err=False)
    assert "'agw.replicas' must be at least 1" in e.value.stderr


def test_values_from_before_replicas_render_one_pod():
    # 'helm upgrade --reuse-values' renders the chart with the previous
    # release's values in place of its defaults, so 'agw.replicas' is missing.
    with tempfile.TemporaryDirectory() as tmp:
        chart = os.path.join(tmp, "hush-agw")
        shutil.copytree(AGW_CHART, chart)
        path = os.path.join(chart, "values.yaml")
        with open(path, encoding="utf-8") as f:
            values = f.read()
        assert "\n  replicas: 1\n" in values
        with open(path, "w", encoding="utf-8") as f:
            f.write(values.replace("\n  replicas: 1\n", "\n"))
        spec = _deployment(template(HOST, chart=chart))["spec"]
    assert spec["replicas"] == 1
    assert spec["strategy"] == {"type": "Recreate"}
