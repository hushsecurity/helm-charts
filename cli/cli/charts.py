import logging
import os
import tempfile
from yaml import CLoader, load
from .gh_api import CHARTS_PFX, ORG
from .process import bash

logger = logging.getLogger(__name__)

REGISTRY = "ghcr.io"
TOP_DIR = os.environ["TOP_DIR"]
RELEASE = os.environ["RELEASE"]
CHARTS_DIR = os.path.join(TOP_DIR, "charts")
SIGN_PARAMS = '--sign --key "hush.security" --keyring /home/runner/.gnupg/secring.gpg'
OCI_BASE_PATH = f"oci://{REGISTRY}/{ORG}/{CHARTS_PFX}"


def chart_dir(chart_name):
    return os.path.join(CHARTS_DIR, chart_name)


def chart_path(chart_name):
    return os.path.join(chart_dir(chart_name), "Chart.yaml")


def load_chart(chart_name):
    with open(chart_path(chart_name), "r", encoding="utf-8") as f:
        return load(f, Loader=CLoader)


def add_release_annotation(chart_name, chart_data):
    if ants := chart_data.get("annotations"):
        raise RuntimeError(
            f"cannot add release annotation: annotations already exist {ants}"
        )
    with open(chart_path(chart_name), "a", encoding="utf-8") as f:
        lines = ["annotations:\n", f'  security.hush/release: "{RELEASE}"\n']
        f.writelines(lines)
        f.flush()
    bash("git diff")


def package_sign_and_push(chart_name, chart_version):
    path = chart_dir(chart_name)
    package_filename = f"{chart_name}-{chart_version}.tgz"
    with tempfile.TemporaryDirectory(prefix="helm-charts-releaser") as tmpDir:
        bash(f"helm package {path} {SIGN_PARAMS}", cwd=tmpDir)
        bash(f"helm verify {package_filename}", cwd=tmpDir)
        bash(f"helm push {package_filename} {OCI_BASE_PATH}", cwd=tmpDir)
        bash(f"helm sigstore upload {package_filename}", cwd=tmpDir)
