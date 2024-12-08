# helm-charts

Hush Security Ltd. Helm charts.

## Installation

Hush Security Ltd. Helm charts are stored in OCI repository under
`ghcr.io/hushsecurity/helm-charts/` prefix.

Download the latest version of `hush-sensor`:

```shell
helm pull oci://ghcr.io/hushsecurity/helm-charts/hush-sensor
```

or alternatively download a specific version:

```shell
helm pull oci://ghcr.io/hushsecurity/helm-charts/hush-sensor --version 1.1.0
```

## Verification

Hush Security Ltd. Helm charts are signed with a PGP key.
The following steps describe a way to verify the signature.

Download and install Hush Security Ltd. public [key](./pgp/public.key):

```shell
wget https://github.com/hushsecurity/helm-charts/blob/main/pgp/public.key
gpg --import public.key
```

Download and verify `hush-sensor v1.1.0`:

```shell
helm pull oci://ghcr.io/hushsecurity/helm-charts/hush-sensor --version 1.1.0 --verify
```

### `sigstore` immutable transparency log

Ensure `sigstore` Helm plugin is installed:

```shell
helm plugin install https://github.com/sigstore/helm-sigstore
```

Assuming previous `helm pull --verify ...`  command succeeded:

```shell
helm sigstore verify hush-sensor-1.1.0.tgz
```
