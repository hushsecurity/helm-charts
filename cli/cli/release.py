import logging
from . import charts, gh_api

logger = logging.getLogger(__name__)


def release_chart(chart_name):
    logger.info("release_chart: %s", chart_name)
    chart_data = charts.load_chart(chart_name)
    chart_version = chart_data["version"]
    existing_versions = gh_api.get_chart_versions(chart_name)
    if chart_version in existing_versions:
        logger.error(
            "chart %s %s is already released: %s",
            chart_name,
            chart_version,
            existing_versions,
        )
        raise RuntimeError(f"{chart_name} v{chart_version} is already released")
    charts.add_release_annotation(chart_name, chart_data)
    charts.package_sign_and_push(chart_name, chart_version)


def release_cmd(args):
    release_chart(args.chart_name)
