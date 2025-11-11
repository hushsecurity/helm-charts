import base64
import contextlib
import logging
import os
import subprocess
import tempfile
import pytest
from yaml import CDumper as Dumper
from yaml import dump
from common.process import bash

logger = logging.getLogger(__name__)

TOP_DIR = os.environ["TOP_DIR"]
CHARTS_DIR = os.path.join(TOP_DIR, "charts")
CHARTS = os.listdir(CHARTS_DIR)

SENSOR_MSV = "v0.25.0"
CONNECTOR_MSV = "v0.5.0"
SENSOR_UNSUPPORTED_VERSIONS = [
    "v0.24",
    "rc0.24",
    "v0.24.0-rc1",
    "v0.24.0",
    f"{SENSOR_MSV}-rc1",
]
SENSOR_SUPPORTED_VERSIONS = [
    "v0",
    "rc0",
    "v0.25",
    "rc0.25",
    SENSOR_MSV,
    "v0.25.1",
    "v0.26.0-rc1",
    "v0.26.0",
    "965353344f",  # such tag should be skipped by the version check
]
CONNECTOR_UNSUPPORTED_VERSIONS = [
    "v0.4",
    "v0.4.0-rc1",
    "v0.4.0",
    f"{CONNECTOR_MSV}-rc1",
    "rc0.4",
]
CONNECTOR_SUPPORTED_VERSIONS = [
    "v0",
    "rc0",
    "v0.5",
    "rc0.5",
    CONNECTOR_MSV,
    "v0.6.0-rc1",
    "v0.6.0",
    "965353344f",  # such tag should be skipped by the version check
]

DUMMY_DEPLOYMENT_TOKEN = "d1:zone:realm:org-id:deployment-id"
KUBE_MINORS = [28, 29, 30, 31, 32, 33, 34]
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
    {
        "hushDeployment": {
            "secretKeyRef": {
                "name": "pre-created-deployment-secret-name",
                "key": "pre-created-deployment-secret-key",
            }
        }
    },
]
CHART_VALUES = {"hush-sensor": HUSH_SENSOR_VALUES}


@contextlib.contextmanager
def values_tmp_file(values: dict):
    hushDeployment = values.setdefault("hushDeployment", {})
    hushDeployment.setdefault(
        "token", base64.b64encode(DUMMY_DEPLOYMENT_TOKEN.encode()).decode()
    )
    if "secretKeyRef" not in hushDeployment:
        hushDeployment.setdefault("password", "dummy_password")
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as tmp_file:
        dump(values, tmp_file, Dumper=Dumper)
        tmp_file.flush()
        yield tmp_file.name


@pytest.mark.parametrize("chart", CHARTS)
def test_kubeconform(chart):
    def _test_ver_path(chart_path, kube_version, path):
        args = f"--kube-version {kube_version} -f {path}"
        conform_kube_version = kube_version.split("-")[0]
        conform_args = f"-strict -kubernetes-version {conform_kube_version}"
        bash(f"helm template {args} {chart_path} | kubeconform {conform_args}")

    chart_path = os.path.join(CHARTS_DIR, chart)
    for kube_version in KUBE_VERSION_VALUES:
        for values in CHART_VALUES.get(chart, []) + [{}]:
            with values_tmp_file(values) as path:
                with open(path, "r", encoding="utf-8") as f:
                    logger.info("values:\n%s", f.read())
                    _test_ver_path(chart_path, kube_version, path)

    ci_dir = os.path.join(chart_path, "ci")
    if os.path.isdir(ci_dir):
        for kube_version in KUBE_VERSION_VALUES:
            for filename in os.listdir(ci_dir):
                if not filename.endswith("-values.yaml"):
                    continue
                path = os.path.join(ci_dir, filename)
                _test_ver_path(chart_path, kube_version, path)


def test_hush_sensor_minimum_supported_version():
    values = os.path.join(CHARTS_DIR, "hush-sensor", "ci", "lint-values.yaml")
    chart_path = os.path.join(CHARTS_DIR, "hush-sensor")

    def _test_unsup_ver(ver):
        args = f"-f {values} --set image.{ver}"
        bash(f"helm template {args} {chart_path}", traceErr=False)

    def _test_unsup_vers(valueName, versions, min_version):
        for ver in versions:
            with pytest.raises(subprocess.CalledProcessError) as e:
                _test_unsup_ver(f"{valueName}={ver}")
            assert (
                f"Version {ver} in 'image.{valueName}' is below the minimum supported version {min_version}"
                in e.value.stderr
            )

    def _test_sup_ver(ver):
        args = f"-f {values} --set image.{ver}"
        bash(f"helm template {args} {chart_path} | kubeconform -strict")

    def _test_sup_vers(valueName, versions):
        for ver in versions:
            _test_sup_ver(f"{valueName}={ver}")

    _test_unsup_vers("sensorTag", SENSOR_UNSUPPORTED_VERSIONS, SENSOR_MSV)
    _test_sup_vers("sensorTag", SENSOR_SUPPORTED_VERSIONS)

    _test_unsup_vers("connectorTag", CONNECTOR_UNSUPPORTED_VERSIONS, CONNECTOR_MSV)
    _test_sup_vers("connectorTag", CONNECTOR_SUPPORTED_VERSIONS)
