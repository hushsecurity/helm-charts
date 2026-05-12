{{/*
Create a default fully qualified app name for Sentry.
*/}}
{{- define "hush-sensor.sentryFullName" -}}
{{- printf "%s-sentry" (include "hush-common.fullName" .) | trunc 63 }}
{{- end }}

{{/*
Create a default fully qualified app name for Vermon.
*/}}
{{- define "hush-sensor.vermonFullName" -}}
{{- printf "%s-vermon" (include "hush-common.fullName" .) | trunc 63 }}
{{- end }}

{{/*
Create a default fully qualified app name for Connector.
*/}}
{{- define "hush-sensor.connectorFullName" -}}
{{- printf "%s-connector" (include "hush-common.fullName" .) | trunc 63 }}
{{- end }}

{{/*
Sensor config map name
*/}}
{{- define "hush-sensor.sensorConfigMapName" -}}
{{- printf "%s-%s" (include "hush-common.buildChartFullName" .) "sensorconfigmap" }}
{{- end }}

{{/*
Sentry AWS integrations configuration
*/}}
{{- define "hush-sensor.sentryAwsIntegrations" -}}
{{- if and .Values.sentry.integrations .Values.sentry.integrations.aws -}}
    {{- $hasIrsa := .Values.sentry.integrations.aws.irsa -}}
    {{- $hasRoles := and .Values.sentry.integrations.aws.assume_roles (gt (len .Values.sentry.integrations.aws.assume_roles) 0) -}}
    {{- if or $hasIrsa $hasRoles -}}
aws:
  enabled: true
        {{- if $hasRoles }}
  assume_roles:
            {{- range .Values.sentry.integrations.aws.assume_roles }}
                {{- if .role_arn }}
    - role_arn: {{ .role_arn | quote }}
                    {{- if .external_id }}
      external_id: {{ .external_id | quote }}
                    {{- end }}
                {{- end }}
            {{- end }}
        {{- end }}
    {{- end }}
{{- end }}
{{- end }}

{{/*
Sentry K8S integrations configuration
*/}}
{{- define "hush-sensor.sentryK8SIntegrations" -}}
{{- if and .Values.sentry.integrations .Values.sentry.integrations.k8s -}}
k8s:
  enabled: {{ .Values.sentry.integrations.k8s.enabled }}
  eso_enabled: {{ .Values.sentry.integrations.k8s.eso_enabled }}
{{- end }}
{{- end }}

{{/*
HC Vault JWT token mount path
*/}}
{{- define "hush-sensor.sentryHcVaultJwtMountPath" -}}
/tmp/vault-sa
{{- end }}

{{/*
HC Vault CACert mount path
*/}}
{{- define "hush-sensor.sentryHcVaultCACertMountPath" -}}
/tmp/vault-cacert
{{- end }}

{{/*
Check if Sentry HC Vault integration is enabled
*/}}
{{- define "hush-sensor.sentryHcVaultEnabled" -}}
{{- if and .Values.sentry.integrations .Values.sentry.integrations.hc_vault .Values.sentry.integrations.hc_vault.server -}}
true
{{- end -}}
{{- end }}


{{/*
Check if Sentry HC Vault JWT integration is enabled
*/}}
{{- define "hush-sensor.sentryHcvMountJwtToken" -}}
{{- if and (include "hush-sensor.sentryHcVaultEnabled" .) .Values.sentry.integrations.hc_vault.auth -}}
{{- if or .Values.sentry.integrations.hc_vault.auth.jwt.role .Values.sentry.integrations.hc_vault.auth.k8s.role -}}
true
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Check if Sentry HC Vault Token auth is enabled
*/}}
{{- define "hush-sensor.sentryHcVaultTokenEnabled" -}}
{{- if and (include "hush-sensor.sentryHcVaultEnabled" .) .Values.sentry.integrations.hc_vault.auth .Values.sentry.integrations.hc_vault.auth.vault_token .Values.sentry.integrations.hc_vault.auth.vault_token.secretKeyRef .Values.sentry.integrations.hc_vault.auth.vault_token.secretKeyRef.name .Values.sentry.integrations.hc_vault.auth.vault_token.secretKeyRef.key -}}
true
{{- end -}}
{{- end }}

{{/*
Sentry HC Vault Token secret ref
*/}}
{{- define "hush-sensor.sentryHcVaultTokenSecretRef" -}}
{{- if (include "hush-sensor.sentryHcVaultTokenEnabled" .) -}}
    {{- dict
        "name" .Values.sentry.integrations.hc_vault.auth.vault_token.secretKeyRef.name
        "key" .Values.sentry.integrations.hc_vault.auth.vault_token.secretKeyRef.key
        | toYaml
    -}}
{{- end -}}
{{- end }}

{{/*
Validate that only one HC Vault auth method is configured.
Fails if more than one of jwt, k8s, or token is defined.
*/}}
{{- define "hush-sensor.validateHcVaultAuthMethod" -}}
{{- $hasJwt := and .Values.sentry.integrations.hc_vault.auth .Values.sentry.integrations.hc_vault.auth.jwt .Values.sentry.integrations.hc_vault.auth.jwt.role -}}
{{- $hasK8s := and .Values.sentry.integrations.hc_vault.auth .Values.sentry.integrations.hc_vault.auth.k8s .Values.sentry.integrations.hc_vault.auth.k8s.role -}}
{{- $hasToken := (include "hush-sensor.sentryHcVaultTokenEnabled" .) -}}
{{- $count := 0 -}}
{{- if $hasJwt }}{{- $count = add $count 1 -}}{{- end -}}
{{- if $hasK8s }}{{- $count = add $count 1 -}}{{- end -}}
{{- if $hasToken }}{{- $count = add $count 1 -}}{{- end -}}
{{- if gt (int $count) 1 -}}
    {{- fail "sentry.integrations.hc_vault.auth: only one auth method (jwt, k8s, or vault_token) can be configured at a time" -}}
{{- end -}}
{{- end }}

{{/*
Sentry HC Vault integration configuration
*/}}
{{- define "hush-sensor.sentryHcVaultIntegration" -}}
{{- if (include "hush-sensor.sentryHcVaultEnabled" .) -}}
  {{- include "hush-sensor.validateHcVaultAuthMethod" . -}}
  {{- $hasJwt := and .Values.sentry.integrations.hc_vault.auth .Values.sentry.integrations.hc_vault.auth.jwt .Values.sentry.integrations.hc_vault.auth.jwt.role -}}
  {{- $hasK8s := and .Values.sentry.integrations.hc_vault.auth .Values.sentry.integrations.hc_vault.auth.k8s .Values.sentry.integrations.hc_vault.auth.k8s.role -}}
  {{- $hasToken := (include "hush-sensor.sentryHcVaultTokenEnabled" .) -}}
  {{- $hasCACert := (include "hush-sensor.hasSentryHcVaultCACert" .) -}}
hcv:
  enabled: true
  vault_addr: {{ .Values.sentry.integrations.hc_vault.server | quote }}
    {{- if $hasCACert }}
  vault_cacert: "{{ include "hush-sensor.sentryHcVaultCACertMountPath" . }}/{{ .Values.sentry.integrations.hc_vault.vaultCACert.secretKeyRef.key }}"
    {{- end }}
    {{- if or $hasJwt $hasK8s $hasToken }}
  auth:
    {{- if $hasJwt }}
    jwt:
      vault_role: {{ .Values.sentry.integrations.hc_vault.auth.jwt.role | quote }}
      token_path: "{{ include "hush-sensor.sentryHcVaultJwtMountPath" . }}/token"
    {{- end }}
    {{- if $hasK8s }}
    k8s:
      vault_role: {{ .Values.sentry.integrations.hc_vault.auth.k8s.role | quote }}
      token_path: "{{ include "hush-sensor.sentryHcVaultJwtMountPath" . }}/token"
    {{- end }}
    {{- if $hasToken }}
    token:
      token_env_name: "SENTRY_VAULT_TOKEN"
    {{- end }}
    {{- end -}}
{{- end -}}
{{- end }}

{{/*
Check if Sentry HC Vault CA Cert is configured
*/}}
{{- define "hush-sensor.hasSentryHcVaultCACert" -}}
{{- if and (include "hush-sensor.sentryHcVaultEnabled" .) .Values.sentry.integrations.hc_vault.vaultCACert .Values.sentry.integrations.hc_vault.vaultCACert.secretKeyRef .Values.sentry.integrations.hc_vault.vaultCACert.secretKeyRef.name .Values.sentry.integrations.hc_vault.vaultCACert.secretKeyRef.key -}}
true
{{- end -}}
{{- end }}

{{/*
Sentry HC Vault CA Cert volume
*/}}
{{- define "hush-sensor.sentryHcVaultCACertVolume" -}}
{{- if (include "hush-sensor.hasSentryHcVaultCACert" .) -}}
- name: vault-ca
  secret:
    secretName: {{ .Values.sentry.integrations.hc_vault.vaultCACert.secretKeyRef.name }}
    items:
      - key: {{ .Values.sentry.integrations.hc_vault.vaultCACert.secretKeyRef.key }}
        path: {{ .Values.sentry.integrations.hc_vault.vaultCACert.secretKeyRef.key }}
{{- end -}}
{{- end }}

{{/*
Sentry HC Vault CA Cert volume mount
*/}}
{{- define "hush-sensor.sentryHcVaultCACertVolumeMount" -}}
{{- if (include "hush-sensor.hasSentryHcVaultCACert" .) -}}
- name: vault-ca
  mountPath: {{ include "hush-sensor.sentryHcVaultCACertMountPath" . }}
  readOnly: true
{{- end -}}
{{- end }}

{{/*
Sentry deployment mount for hc vault integration with JWT Auth
*/}}
{{- define "hush-sensor.sentryHcVaultJwtVolumeMount" -}}
{{- if (include "hush-sensor.sentryHcvMountJwtToken" .) -}}
- name: k8s-vault-sa
  mountPath: {{ include "hush-sensor.sentryHcVaultJwtMountPath" . }}
  readOnly: true
{{- end -}}
{{- end }}

{{/*
Sentry deployment projected volume for hc vault integration with JWT Auth
*/}}
{{- define "hush-sensor.sentryHcVaultJwtProjectedVolume" -}}
{{- if (include "hush-sensor.sentryHcvMountJwtToken" .) -}}
- name: k8s-vault-sa
  projected:
    sources:
      - serviceAccountToken:
          path: token
          expirationSeconds: 3600
          audience: hush-security
{{- end -}}
{{- end }}


{{/*
Check if Sentry Azure KV integration is enabled.
Enabled when tenant_id is set. Auth method is validated separately.
*/}}
{{- define "hush-sensor.sentryAzureKvEnabled" -}}
{{- if dig "integrations" "azure" "tenant_id" "" .Values.sentry -}}
true
{{- end -}}
{{- end }}

{{/*
Check if Sentry Azure KV Service Principal auth is enabled.
True when all SP fields are populated: client_id + clientSecret.secretKeyRef.{name,key}.
*/}}
{{- define "hush-sensor.sentryAzureKvSPEnabled" -}}
{{- $akv := .Values.sentry.integrations.azure -}}
{{- $clientId := dig "auth" "service_principal" "client_id" "" $akv -}}
{{- $secretName := dig "auth" "service_principal" "clientSecret" "secretKeyRef" "name" "" $akv -}}
{{- $secretKey := dig "auth" "service_principal" "clientSecret" "secretKeyRef" "key" "" $akv -}}
{{- if and (include "hush-sensor.sentryAzureKvEnabled" .) $clientId $secretName $secretKey -}}
true
{{- end -}}
{{- end }}

{{/*
Sentry Azure KV Client Secret secret ref
*/}}
{{- define "hush-sensor.sentryAzureKvClientSecretSecretRef" -}}
{{- if (include "hush-sensor.sentryAzureKvSPEnabled" .) -}}
    {{- dict
        "name" .Values.sentry.integrations.azure.auth.service_principal.clientSecret.secretKeyRef.name
        "key" .Values.sentry.integrations.azure.auth.service_principal.clientSecret.secretKeyRef.key
        | toYaml
    -}}
{{- end -}}
{{- end }}

{{/*
Validate that only one Azure KV auth method is configured.
Fails if both service_principal and workload_identity are configured simultaneously.
*/}}
{{- define "hush-sensor.validateAzureKvAuthMethod" -}}
{{- if not .Values.sentry.integrations.azure.tenant_id -}}
    {{- fail "sentry.integrations.azure: tenant_id is required" -}}
{{- end -}}
{{- $akv := .Values.sentry.integrations.azure -}}
{{- $hasSP := (include "hush-sensor.sentryAzureKvSPEnabled" .) -}}
{{- $hasWI := dig "auth" "workload_identity" "client_id" "" $akv -}}
{{- $spClientId := dig "auth" "service_principal" "client_id" "" $akv -}}
{{- if and $spClientId (not $hasSP) -}}
    {{- fail "sentry.integrations.azure.auth.service_principal: client_id is set but clientSecret.secretKeyRef.name and key are also required" -}}
{{- end -}}
{{- if and (not $hasSP) (not $hasWI) -}}
    {{- fail "sentry.integrations.azure: at least one auth method (service_principal or workload_identity) must be configured" -}}
{{- end -}}
{{- if and $hasSP $hasWI -}}
    {{- fail "sentry.integrations.azure: only one auth method (service_principal or workload_identity) can be configured at a time" -}}
{{- end -}}
{{- if and $akv.management_group_id $akv.subscription_ids (kindIs "slice" $akv.subscription_ids) (gt (len $akv.subscription_ids) 0) -}}
    {{- fail "sentry.integrations.azure: management_group_id and subscription_ids are mutually exclusive" -}}
{{- end -}}
{{- end }}

{{/*
Sentry Azure KV integration configuration.
Produces the azure: block matching the Go config struct.
When using Workload Identity (no SP), the auth block is omitted — Go falls back to defaultAuth.
*/}}
{{- define "hush-sensor.sentryAzureKvIntegration" -}}
{{- if (include "hush-sensor.sentryAzureKvEnabled" .) -}}
  {{- include "hush-sensor.validateAzureKvAuthMethod" . -}}
  {{- $akv := .Values.sentry.integrations.azure -}}
  {{- $hasSP := (include "hush-sensor.sentryAzureKvSPEnabled" .) -}}
azure:
  enabled: true
  tenant_id: {{ $akv.tenant_id | quote }}
  {{- if $akv.management_group_id }}
  management_group_id: {{ $akv.management_group_id | quote }}
  {{- end }}
  {{- if and $akv.subscription_ids (kindIs "slice" $akv.subscription_ids) (gt (len $akv.subscription_ids) 0) }}
  subscription_ids:
    {{- range $akv.subscription_ids }}
    - {{ . | quote }}
    {{- end }}
  {{- end }}
  {{- if $hasSP }}
  auth:
    service_principal:
      client_id: {{ $akv.auth.service_principal.client_id | quote }}
      client_secret_env: "AZURE_CLIENT_SECRET"
  {{- end -}}
{{- end -}}
{{- end }}

{{/*
Kubernetes version
*/}}
{{- define "hush-sensor.kubeVersion" -}}
{{- .Capabilities.KubeVersion.Version }}
{{- end }}

{{/*
DaemonSet Annotations
*/}}
{{- define "hush-sensor.daemonSetAnnotations" -}}
{{- $hasAppArmorAnnotation :=
    semverCompare "<1.31" (include "hush-sensor.kubeVersion" .) -}}
{{- if $hasAppArmorAnnotation -}}
container.apparmor.security.beta.kubernetes.io/hush-sensor: unconfined
{{- end }}
{{- with .Values.daemonSet.annotations -}}
    {{- if $hasAppArmorAnnotation -}}
        {{- toYaml . | nindent 0 }}
    {{- else -}}
        {{- toYaml . }}
    {{- end }}
{{- end }}
{{- end }}

{{/*
AppArmorProfile
*/}}
{{- define "hush-sensor.appArmorProfile" -}}
    {{- if semverCompare ">=1.31" (include "hush-sensor.kubeVersion" .) -}}
type: Unconfined
    {{- end -}}
{{- end }}

{{/*
Verify hushDeployment.token was defined
*/}}
{{- define "hush-sensor.getDeploymentTokenValue" -}}
{{- $token := and .Values.hushDeployment .Values.hushDeployment.token -}}
{{- if not $token -}}
    {{- fail "'hushDeployment.token' is undefined" -}}
{{- end -}}
{{- printf "%s" $token -}}
{{- end }}

{{/*
Verify hushDeployment.password was defined
*/}}
{{- define "hush-sensor.getDeploymentPasswordValue" -}}
{{- $password := and .Values.hushDeployment .Values.hushDeployment.password -}}
{{- if not $password -}}
    {{- fail "'hushDeployment.password' is undefined" -}}
{{- end -}}
{{- printf "%s" $password -}}
{{- end }}

{{/*
Should we create the daemon set?
*/}}
{{- define "hush-sensor.shouldCreateDaemonSet" -}}
{{- $argIsMissing := and .Values.daemonSet (not (hasKey .Values.daemonSet "enabled")) -}}
{{- if and .Values.daemonSet (or .Values.daemonSet.enabled $argIsMissing) -}}
true
{{- end }}
{{- end }}

{{/*
Should we create the deployment token K8S Secret?
*/}}
{{- define "hush-sensor.shouldCreateDeploymentTokenKubeSecret" -}}
{{- $keyRef := and .Values.hushDeployment .Values.hushDeployment.secretKeyRef -}}
{{- $name := and $keyRef $keyRef.name -}}
{{- $tokenKey := and $keyRef $keyRef.tokenKey -}}
{{- if not (and $name $tokenKey) -}}
true
{{- end }}
{{- end }}

{{/*
Should we create the deployment password K8S Secret?
*/}}
{{- define "hush-sensor.shouldCreateDeploymentPasswordKubeSecret" -}}
{{- if include "hush-common.isPasswordAuthMode" . -}}
{{- $keyRef := and .Values.hushDeployment .Values.hushDeployment.secretKeyRef -}}
{{- $name := and $keyRef $keyRef.name -}}
{{- $key := and $keyRef $keyRef.key -}}
{{- if not (and $name $key) -}}
true
{{- end }}
{{- end }}
{{- end }}

{{/*
Should we create deployment K8S Secret?
*/}}
{{- define "hush-sensor.shouldCreateDeploymentKubeSecret" -}}
{{- if or
    (include "hush-sensor.shouldCreateDeploymentTokenKubeSecret" .)
    (include "hush-sensor.shouldCreateDeploymentPasswordKubeSecret" .) -}}
true
{{- end -}}
{{- end }}

{{/*
Effective deployment token secret ref
*/}}
{{- define "hush-sensor.effectiveDeploymentTokenKubeSecretRef" -}}
{{- if (include "hush-sensor.shouldCreateDeploymentTokenKubeSecret" .) -}}
    {{- dict
        "name" (include "hush-common.deploymentKubeSecretName" .)
        "key" "deployment-token"
        | toYaml
    -}}
{{- else -}}
    {{- dict
        "name" .Values.hushDeployment.secretKeyRef.name
        "key" .Values.hushDeployment.secretKeyRef.tokenKey
        | toYaml
    -}}
{{- end }}
{{- end }}

{{/*
Effective deployment password secret ref
*/}}
{{- define "hush-sensor.effectiveDeploymentPasswordKubeSecretRef" -}}
{{- if include "hush-common.isPasswordAuthMode" . -}}
  {{- if (include "hush-sensor.shouldCreateDeploymentPasswordKubeSecret" .) -}}
      {{- dict
          "name" (include "hush-common.deploymentKubeSecretName" .)
          "key" "deployment-password"
          | toYaml
      -}}
  {{- else -}}
      {{- dict
          "name" .Values.hushDeployment.secretKeyRef.name
          "key" .Values.hushDeployment.secretKeyRef.key
          | toYaml
      -}}
  {{- end }}
{{- end }}
{{- end }}

{{/*
Sensor image path
*/}}
{{- define "hush-sensor.sensorImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-common.imageRegistry" .)
    "repository" .Values.image.sensorRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-common.buildImagePath" $ctx -}}
{{- end }}

{{/*
Vector image path
*/}}
{{- define "hush-sensor.sensorVectorImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-common.imageRegistry" .)
    "repository" .Values.image.sensorVectorRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-common.buildImagePath" $ctx -}}
{{- end }}

{{/*
Sentry image path
*/}}
{{- define "hush-sensor.sentryImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-common.imageRegistry" .)
    "repository" .Values.image.sentryRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-common.buildImagePath" $ctx -}}
{{- end }}

{{/*
Connector Client image path
*/}}
{{- define "hush-sensor.connectorClientImagePath" -}}
{{- include "hush-sensor.verifyConnectorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-common.imageRegistry" .)
    "repository" .Values.image.connectorClientRepository
    "tag" .Values.image.connectorTag
-}}
{{- include "hush-common.buildImagePath" $ctx -}}
{{- end }}

{{/*
Connector Forwarder image path
*/}}
{{- define "hush-sensor.connectorForwarderImagePath" -}}
{{- include "hush-sensor.verifyConnectorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-common.imageRegistry" .)
    "repository" .Values.image.connectorForwarderRepository
    "tag" .Values.image.connectorTag
-}}
{{- include "hush-common.buildImagePath" $ctx -}}
{{- end }}

{{/*
Vermon image path
*/}}
{{- define "hush-sensor.vermonImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-common.imageRegistry" .)
    "repository" .Values.image.vermonRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-common.buildImagePath" $ctx -}}
{{- end }}

{{/*
Validate criSocketPath
*/}}
{{- define "hush-sensor.criSocketPath" -}}
{{- $path := and .Values.daemonSet .Values.daemonSet.criSocketPath -}}
{{- if $path -}}
    {{- if not (isAbs $path) -}}
        {{- fail (printf "'criSocketPath' must be an absolute path: %s" $path) -}}
    {{- end -}}
    {{- if eq (dir $path) "/" -}}
        {{- fail (printf "'criSocketPath' base directory cannot be root: %s" $path) -}}
    {{- end -}}
    {{- printf "%s" $path -}}
{{- end -}}
{{- end }}

{{/*
Containerd mount path
*/}}
{{- define "hush-sensor.criMountPath" -}}
{{- $path := (include "hush-sensor.criSocketPath" .) -}}
{{- if $path -}}
    {{- dir $path -}}
{{- else -}}
    {{- printf "%s" "/run/containerd" -}}
{{- end -}}
{{- end }}

{{/*
Sentry service account annotations with AWS IAM role handling
*/}}
{{- define "hush-sensor.sentryServiceAccountAnnotations" -}}
{{- $annotations := deepCopy (default dict .Values.sentry.serviceAccount.annotations) -}}
{{- $roleArnKey := "eks.amazonaws.com/role-arn" -}}
{{- if and .Values.sentry.integrations .Values.sentry.integrations.aws .Values.sentry.integrations.aws.irsa -}}
  {{- if hasKey $annotations $roleArnKey -}}
    {{- $existingRole := get $annotations $roleArnKey -}}
    {{- if ne $existingRole .Values.sentry.integrations.aws.irsa -}}
      {{- fail (printf "Error: inconsistent sentry service account annotation for %s. Expected %s" $roleArnKey .Values.sentry.integrations.aws.irsa) -}}
    {{- end -}}
  {{- else -}}
    {{- $_ := set $annotations $roleArnKey .Values.sentry.integrations.aws.irsa -}}
  {{- end -}}
{{- end -}}
{{- $wiClientIdKey := "azure.workload.identity/client-id" -}}
{{- if dig "integrations" "azure" "auth" "workload_identity" "client_id" "" .Values.sentry -}}
  {{- if hasKey $annotations $wiClientIdKey -}}
    {{- $existingId := get $annotations $wiClientIdKey -}}
    {{- if ne $existingId .Values.sentry.integrations.azure.auth.workload_identity.client_id -}}
      {{- fail (printf "Error: inconsistent sentry service account annotation for %s. Expected %s" $wiClientIdKey .Values.sentry.integrations.azure.auth.workload_identity.client_id) -}}
    {{- end -}}
  {{- else -}}
    {{- $_ := set $annotations $wiClientIdKey .Values.sentry.integrations.azure.auth.workload_identity.client_id -}}
  {{- end -}}
{{- end -}}
{{- $wiTenantIdKey := "azure.workload.identity/tenant-id" -}}
{{- if and (dig "integrations" "azure" "auth" "workload_identity" "client_id" "" .Values.sentry) (dig "integrations" "azure" "tenant_id" "" .Values.sentry) -}}
  {{- if hasKey $annotations $wiTenantIdKey -}}
    {{- $existingId := get $annotations $wiTenantIdKey -}}
    {{- if ne $existingId .Values.sentry.integrations.azure.tenant_id -}}
      {{- fail (printf "Error: inconsistent sentry service account annotation for %s. Expected %s" $wiTenantIdKey .Values.sentry.integrations.azure.tenant_id) -}}
    {{- end -}}
  {{- else -}}
    {{- $_ := set $annotations $wiTenantIdKey .Values.sentry.integrations.azure.tenant_id -}}
  {{- end -}}
{{- end -}}
{{- if $annotations -}}
  {{- toYaml $annotations -}}
{{- end -}}
{{- end -}}

{{/*
Verify that minimum supported version holds for a Hush version tag.
Exit with an error message if version constraint doesn't hold.
Don't verify versions that look unofficial (do not start with "v" or "rc").
Input: {
  .version = <the version to check>,
  .valueName = <the name of the checked value>,
  .minVersion = <the minimum allowed version>,
}
*/}}
{{- define "hush-sensor.verifyMinimumSupportedVersion" -}}
{{- $msg := printf "Version %s in %s is below the minimum supported version %s" .version .valueName .minVersion -}}
{{- $versionParts := splitList "." .version -}}
{{- $version := trimPrefix "v" .version -}}
{{- $version = trimPrefix "rc" $version -}}
{{- $minVersionAtoms := semver .minVersion -}}
{{- if not (or (hasPrefix "v" .version) (hasPrefix "rc" .version)) -}}
    {{/* looks like unofficial version - skip verification */}}
{{- else if eq (len $versionParts) 1 -}}
    {{- $major := atoi (index $versionParts 0) -}}
    {{- if lt $major $minVersionAtoms.Major -}}
        {{- fail $msg -}}
    {{- end -}}
{{- else if eq (len $versionParts) 2 -}}
    {{- $major := atoi (index $versionParts 0) -}}
    {{- $minor := atoi (index $versionParts 1) -}}
    {{- if lt $major $minVersionAtoms.Major -}}
        {{- fail $msg -}}
    {{- else if and (eq $major $minVersionAtoms.Major) (lt $minor $minVersionAtoms.Minor) -}}
        {{- fail $msg -}}
    {{- end -}}
{{- else -}}
    {{- $minVer := semver .minVersion -}}
    {{- $ver := semver $version -}}
    {{- if eq ($ver | $minVer.Compare) 1 -}}
        {{- fail $msg -}}
    {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Verify sensor minimum supported version.
*/}}
{{- define "hush-sensor.verifySensorMinimumSupportedVersion" -}}
{{- $ctx := dict
    "valueName" "'image.sensorTag'"
    "version" .Values.image.sensorTag
    "minVersion" "v0.25.0"
-}}
{{- include "hush-sensor.verifyMinimumSupportedVersion" $ctx -}}
{{- end -}}

{{/*
Verify connector minimum supported version.
*/}}
{{- define "hush-sensor.verifyConnectorMinimumSupportedVersion" -}}
{{- $ctx := dict
    "valueName" "'image.connectorTag'"
    "version" .Values.image.connectorTag
    "minVersion" "v0.5.0"
-}}
{{- include "hush-sensor.verifyMinimumSupportedVersion" $ctx -}}
{{- end -}}
