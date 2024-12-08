# helm-charts

Hush Security Ltd. helm charts.

## Download

Hush helm charts are stored in OCI repository `ghcr.io` under
`/hushsecurity/helm-charts/` prefix.

Download the latest version of a chart:

```shell
helm pull oci://ghcr.io/hushsecurity/helm-charts/hush-sensor
```

Download a specific version of a chart:

```shell
helm pull oci://ghcr.io/hushsecurity/helm-charts/hush-sensor --version 1.1.0
```

## Verification

Hush helm charts are signed with a PGP key.

Download and import Hush [public key](./pgp/public.key):

```shell
wget -O hush.public.key https://raw.githubusercontent.com/hushsecurity/helm-charts/refs/heads/main/pgp/public.key
gpg --import hush.public.key
```

If your keyring is stored in `kbx` format (GnuPG v2) export the key to legacy format:

```shell
gpg --export > ~/.gnupg/pubring.gpg
```

Download and verify the latest version of a chart:

```shell
helm pull oci://ghcr.io/hushsecurity/helm-charts/hush-sensor --verify
```

### Immutable transparency log

Hush helm charts' provenance is published in [sigstore](https://www.sigstore.dev/)
immutable transparency log.

Ensure `helm-sigstore` plugin is installed:

```shell
helm plugin install https://github.com/sigstore/helm-sigstore
```

Assuming chart package and provenance files were downloaded using `helm pull --verify`
verify the transparency log record:

```shell
helm sigstore verify hush-sensor-1.1.0.tgz
```
