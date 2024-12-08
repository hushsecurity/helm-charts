import logging
import os
import re
import requests

logger = logging.getLogger(__name__)

TIMEOUT = 30
GH_API = "https://api.github.com"
ORG = "hushsecurity"
CHARTS_PFX = "helm-charts"
CHARTS_API_PATH = f"orgs/{ORG}/packages/container"
NEXT_RE = re.compile(r"<(?P<url>\S*)>; rel=\"next\"")
GH_TOKEN = os.environ["GH_TOKEN"]


def get_chart_versions(chart_name):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {GH_TOKEN}",
    }
    params = {"per_page": 100}
    url = f"{GH_API}/{CHARTS_API_PATH}/{CHARTS_PFX}%2F{chart_name}/versions"
    versions = set()
    while True:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=TIMEOUT,
        )
        if response.status_code == 404:
            return versions
        response.raise_for_status()
        versions.update(*(v["metadata"]["container"]["tags"] for v in response.json()))
        if (link := response.headers.get("link")) and 'rel="next"' in link:
            if not (m := NEXT_RE.search(link)):
                raise RuntimeError(f"failed to parse link: {link}")
            url = m.group("url")
            params = None
        else:
            break
    return versions
