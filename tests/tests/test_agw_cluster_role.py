from common.chart import AGW_CHART
from common.chart import template as _template

AGW_BASE = "--set agw.hostname=gw.example.com"


def template(extra_args=""):
    return _template(f"{AGW_BASE} {extra_args}", chart=AGW_CHART)


# Before it revokes a credential version, the gateway checks that no pod in any
# namespace still uses it: the cluster role lets it list pods, and nothing more
# on them.
def test_gateway_may_list_pods_in_every_namespace():
    # Render the chart with its defaults.
    docs = template()

    # The cluster role grants listing pods, with no other verb.
    (role,) = [doc for doc in docs if doc["kind"] == "ClusterRole"]
    pod_rules = [rule for rule in role["rules"] if "pods" in rule["resources"]]
    assert pod_rules == [{"apiGroups": [""], "resources": ["pods"], "verbs": ["list"]}]

    # It is bound to the gateway's service account.
    (binding,) = [doc for doc in docs if doc["kind"] == "ClusterRoleBinding"]
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    (account,) = [doc for doc in docs if doc["kind"] == "ServiceAccount"]
    (subject,) = binding["subjects"]
    assert subject["kind"] == "ServiceAccount"
    assert subject["name"] == account["metadata"]["name"]
