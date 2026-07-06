import os
import pytest
from yaml import CSafeLoader as Loader
from yaml import load

TOP_DIR = os.environ["TOP_DIR"]
CHARTS_DIR = os.path.join(TOP_DIR, "charts")


def _ci_files():
    params = []
    for chart in sorted(os.listdir(CHARTS_DIR)):
        ci_dir = os.path.join(CHARTS_DIR, chart, "ci")
        if not os.path.isdir(ci_dir):
            continue
        for filename in sorted(os.listdir(ci_dir)):
            if filename.endswith("-values.yaml"):
                params.append((chart, filename))
    return params


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return load(f, Loader=Loader)


def _unknown_paths(values, defaults, path=""):
    # Sections whose default is an empty map/list (nodeSelector,
    # annotations, resources, ...) are free-form and not descended into.
    unknown = []
    for key, value in values.items():
        here = f"{path}.{key}" if path else key
        if key not in defaults:
            unknown.append(here)
            continue
        dflt = defaults[key]
        if isinstance(value, dict) and isinstance(dflt, dict) and dflt:
            unknown.extend(_unknown_paths(value, dflt, here))
    return unknown


@pytest.mark.parametrize("chart,filename", _ci_files())
def test_ci_values_use_known_keys(chart, filename):
    defaults = _load_yaml(os.path.join(CHARTS_DIR, chart, "values.yaml"))
    values = _load_yaml(os.path.join(CHARTS_DIR, chart, "ci", filename)) or {}
    assert _unknown_paths(values, defaults) == []
