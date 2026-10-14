from common.chart import AGW_CHART, template

TOKEN_VOLUME = "kube-api-access"
TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount"

# the containers that call the Kubernetes API: agent-warden for the secret
# store, and hdc in agent-warden and vector for the kube-system uid
API_CONTAINERS = {"agw-controller-init", "agw-controller", "agw-vector"}


def _pod_spec():
    docs = template("--set agw.hostname=gw.example.com", chart=AGW_CHART)
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    return deployment["spec"]["template"]["spec"]


# The service account token reaches only the containers that call the API, so
# the gateway's client-facing container and the toolbox hold no API
# credential.
def test_api_token_reaches_only_the_containers_that_call_the_api():
    # Render the chart with its defaults.
    spec = _pod_spec()

    # The token is not mounted into every container.
    assert spec["automountServiceAccountToken"] is False

    # It is projected with the cluster CA and the namespace, where the
    # Kubernetes clients look for them.
    (volume,) = [v for v in spec["volumes"] if v["name"] == TOKEN_VOLUME]
    sources = volume["projected"]["sources"]
    assert {"serviceAccountToken", "configMap", "downwardAPI"} == {
        key for source in sources for key in source
    }

    # Only the containers that call the API mount it, at the usual path.
    for container in spec["initContainers"] + spec["containers"]:
        mounts = {m["name"]: m for m in container.get("volumeMounts", [])}
        if container["name"] in API_CONTAINERS:
            assert mounts[TOKEN_VOLUME]["mountPath"] == TOKEN_PATH
        else:
            assert TOKEN_VOLUME not in mounts
