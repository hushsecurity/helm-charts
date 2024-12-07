import os
import re
import requests

TIMEOUT = 30
GH_API = "https://api.github.com"
ORG = "hushsecurity"
CHARTS_PFX = "helm-charts"
CHARTS_API_PATH = f"orgs/{ORG}/packages/container/{CHARTS_PFX}"
NEXT_RE = re.compile(r"<(?P<url>\S*)>; rel=\"next\"")
GH_TOKEN = os.environ["GH_TOKEN"]


def get_chart_versions(chart_name):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {GH_TOKEN}",
    }
    params = {"per_page": 1}
    url = f"{GH_API}/{CHARTS_API_PATH}/{chart_name}/versions"
    versions = []
    while True:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=TIMEOUT,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        versions.extend(v["name"] for v in response.json())
        if (link := response.headers.get("link")) and 'rel="next"' in link:
            if not (m := NEXT_RE.search(link)):
                raise RuntimeError(f"failed to parse link: {link}")
            url = m.group("url")
            params = None
        else:
            break
    return versions
