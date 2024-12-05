import logging
import os
from .gh_api import get_published_versions

logger = logging.getLogger(__name__)


class Releaser:
    def __init__(self, args):
        self.args = args
        self._charts = os.listdir(args.charts_dir)

    def run(self):
        deployments_cnt = 0
        for name in self._charts:
            if self.release_chart(name):
                deployments_cnt += 1

    def release_chart(self, chart_name):
        logger.info("release_chart: %s", chart_name)
        if version := self.is_deployed(chart_name):
            logger.info("chart %s v%s is already deployed", chart_name, version)
            return False
        return True

    def is_deployed(self, chart_name):
        raise NotImplementedError

    def get_chart_version(self, chart_name):
        raise NotImplementedError


def release_cmd(args):
    charts = os.listdir(args.charts_dir)
    for name in charts:
        release_chart(args, name)


def release_chart(args, chart_name):
    _ = args
    pvs = get_published_versions(chart_name)
    print(f"published_versions: {pvs}")
