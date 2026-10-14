from common.chart import AGW_CHART, template

MASK_VOLUME = "sa-token-mask"
TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount"

# the containers that call the Kubernetes API: agent-warden for the secret
# store, and hdc in agent-warden and vector for the kube-system uid
API_CONTAINERS = {"agw-controller-init", "agw-controller", "agw-vector"}


def _pod_spec():
    docs = template("--set agw.hostname=gw.example.com", chart=AGW_CHART)
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    return deployment["spec"]["template"]["spec"]


# Kubernetes mounts the service account token into every container that has
# nothing mounted at the token's path. Every container but the ones that call
# the API masks that path, so the client-facing container and the toolbox hold
# no API credential, and a container added later fails here until it is put
# on one side or the other.
def test_api_token_is_masked_in_the_containers_that_do_not_call_the_api():
    # Render the chart with its defaults.
    spec = _pod_spec()

    # Kubernetes is left to mount the token.
    assert spec.get("automountServiceAccountToken") is not False

    # The mask is an empty volume.
    (volume,) = [v for v in spec["volumes"] if v["name"] == MASK_VOLUME]
    assert volume["emptyDir"] == {}

    # The containers that call the API mount nothing at the token's path, and
    # every other container mounts the mask there.
    for container in spec["initContainers"] + spec["containers"]:
        at_path = [
            mount["name"]
            for mount in container.get("volumeMounts", [])
            if mount["mountPath"] == TOKEN_PATH
        ]
        if container["name"] in API_CONTAINERS:
            assert at_path == [], container["name"]
        else:
            assert at_path == [MASK_VOLUME], container["name"]
