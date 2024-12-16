import base64
import contextlib
import logging
import os
import tempfile
import pytest
from yaml import CDumper as Dumper
from yaml import dump
from common.process import bash

logger = logging.getLogger(__name__)

TOP_DIR = os.environ["TOP_DIR"]
CHARTS_DIR = os.path.join(TOP_DIR, "charts")
CHARTS = os.listdir(CHARTS_DIR)

DUMMY_DEPLOYMENT_TOKEN = "d1:zone:realm:org-id:deployment-id:secret"
KUBE_MINORS = [28, 29, 30, 31]
KUBE_VERSION_VALUES = [f"1.{m}.0" for m in KUBE_MINORS] + ["1.29.10-eks-7f9249a"]
HUSH_SENSOR_VALUES = [
    {
        "image": {
            "pullSecret": {"username": "dummy-username", "password": "dummy-password"}
        }
    },
    {
        "daemonSet": {
            "tolerations": [
                {
                    "key": "kubernetes.io/arch",
                    "operator": "Equal",
                    "value": "arm64",
                    "effect": "NoSchedule",
                }
            ]
        }
    },
    {
        "daemonSet": {
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {
                                        "key": "kubernetes.io/os",
                                        "operator": "In",
                                        "values": ["linux"],
                                    },
                                    {
                                        "key": "kubernetes.io/arch",
                                        "operator": "In",
                                        "values": ["arm64", "amd64"],
                                    },
                                ]
                            }
                        ]
                    }
                }
            }
        }
    },
]
CHART_VALUES = {"hush-sensor": HUSH_SENSOR_VALUES}


@contextlib.contextmanager
def values_tmp_file(values: dict):
    values.setdefault(
        "deploymentToken", base64.b64encode(DUMMY_DEPLOYMENT_TOKEN.encode()).decode()
    )
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as tmp_file:
        dump(values, tmp_file, Dumper=Dumper)
        tmp_file.flush()
        yield tmp_file.name


@pytest.mark.parametrize("chart", CHARTS)
def test_kubeconform(chart):
    chart_path = os.path.join(CHARTS_DIR, chart)
    for kube_version in KUBE_VERSION_VALUES:
        for values in CHART_VALUES.get(chart, []) + [{}]:
            with values_tmp_file(values) as path:
                with open(path, "r", encoding="utf-8") as f:
                    logger.info("values:\n%s", f.read())
                args = f"--kube-version {kube_version} -f {path}"
                conform_kube_version = kube_version.split("-")[0]
                conform_args = f"-strict -kubernetes-version {conform_kube_version}"
                bash(f"helm template {args} {chart_path} | kubeconform {conform_args}")
