"""Templating a chart, shared by the chart test modules.

Each module had its own copy of this, so a change to how a chart is templated
had to be made in every one of them.
"""

import base64
import os
from yaml import CSafeLoader as Loader
from yaml import load_all
from common.process import bash

TOP_DIR = os.environ["TOP_DIR"]
AM_CHART = os.path.join(TOP_DIR, "charts", "hush-am")

DUMMY_TOKEN = base64.b64encode(b"d1:zone:realm:org-id:deployment-id").decode()


def template(extra_args="", chart=AM_CHART, trace_err=True):
    """Render a chart and return its documents, dropping the empty ones."""
    args = (
        f"--set hushDeployment.token={DUMMY_TOKEN} --set hushDeployment.password=dummy"
    )
    out = bash(f"helm template {args} {extra_args} {chart}", traceErr=trace_err)
    return [doc for doc in load_all(out, Loader=Loader) if doc]
