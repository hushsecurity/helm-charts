{{/*
Expand the name of the chart.
*/}}
{{- define "hush-sensor.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Build chart full name
*/}}
{{- define "hush-sensor.buildChartFullName" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name }}
    {{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
    {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this
(by the DNS naming spec). If release name contains chart name it will be used as a
full name.
*/}}
{{- define "hush-sensor.fullName" -}}
{{- if .Values.fullnameOverride }}
    {{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
    {{- include "hush-sensor.buildChartFullName" . }}
{{- end }}
{{- end }}

{{/*
Create a default fully qualified app name for Sentry.
*/}}
{{- define "hush-sensor.sentryFullName" -}}
{{- printf "%s-sentry" (include "hush-sensor.fullName" .) | trunc 63 }}
{{- end }}

{{/*
Create a default fully qualified app name for Vermon.
*/}}
{{- define "hush-sensor.vermonFullName" -}}
{{- printf "%s-vermon" (include "hush-sensor.fullName" .) | trunc 63 }}
{{- end }}

{{/*
Create a default fully qualified app name for Connector.
*/}}
{{- define "hush-sensor.connectorFullName" -}}
{{- printf "%s-connector" (include "hush-sensor.fullName" .) | trunc 63 }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "hush-sensor.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version
    | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Calculate the namespace to use.
*/}}
{{- define "hush-sensor.namespace" -}}
{{- default .Release.Namespace .Values.namespaceOverride }}
{{- end }}

{{/*
Sensor config map name
*/}}
{{- define "hush-sensor.sensorConfigMapName" -}}
{{- printf "%s-%s" (include "hush-sensor.buildChartFullName" .) "sensorconfigmap" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "hush-sensor.labels" -}}
helm.sh/chart: {{ include "hush-sensor.chart" . }}
{{ include "hush-sensor.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels -}}
    {{- toYaml . | nindent 0 }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "hush-sensor.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hush-sensor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
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
Deployment K8S Secret name
*/}}
{{- define "hush-sensor.deploymentKubeSecretName" -}}
{{- printf "%s-deploymentsecret" (include "hush-sensor.fullName" .) }}
{{- end }}

{{/*
Get image registry
*/}}
{{- define "hush-sensor.imageRegistry" -}}
{{- $token := (include "hush-sensor.parsePullToken" . | fromYaml) -}}
{{- $registry := and .Values.image .Values.image.registry -}}
{{- default $registry (get $token "registry") -}}
{{- end }}

{{/*
Get image.pullSecret.username
*/}}
{{- define "hush-sensor.kubeImagePullSecretUsername" -}}
{{- $token := (include "hush-sensor.parsePullToken" . | fromYaml) -}}
{{- $hasPullSecret := (and .Values.image .Values.image.pullSecret) -}}
{{- $username := and $hasPullSecret .Values.image.pullSecret.username -}}
{{- default $username (get $token "username") -}}
{{- end }}

{{/*
Get image.pullSecret.password
*/}}
{{- define "hush-sensor.kubeImagePullSecretPassword" -}}
{{- $token := (include "hush-sensor.parsePullToken" . | fromYaml) -}}
{{- $hasPullSecret := (and .Values.image .Values.image.pullSecret) -}}
{{- $password := and $hasPullSecret .Values.image.pullSecret.password -}}
{{- default $password (get $token "password") -}}
{{- end }}

{{/*
Parse Hush image.pullToken
*/}}
{{- define "hush-sensor.parsePullToken" -}}
{{- $pullToken := and .Values.image .Values.image.pullToken -}}
{{- if $pullToken -}}
    {{- $ctx := dict "name" "image.pullToken" "value" $pullToken -}}
    {{- $token := (include "hush-sensor.b64decode" $ctx) -}}
    {{- $version := splitn ":" 2 $token -}}
    {{- if ne $version._0 "p1" -}}
        {{- fail (printf "image.pullToken version '%s' isn't supported" $version._0) -}}
    {{- end -}}
    {{- $registry := splitn ":" 2 $version._1 -}}
    {{- if not $registry._0 -}}
        {{- fail "invalid image.pullToken: registry is empty" -}}
    {{- end -}}
    {{- $username := splitn ":" 2 $registry._1 -}}
    {{- if not $username._0 -}}
        {{- fail "invalid image.pullToken: username is empty" -}}
    {{- end -}}
    {{- $password := splitn ":" 2 $username._1 -}}
    {{- if not $password._0 -}}
        {{- fail "invalid image.pullToken: password is empty" -}}
    {{- end -}}
    {{- dict
        "registry" $registry._0
        "username" $username._0
        "password" $password._0
        | toYaml
    -}}
{{- end -}}
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
Should we create the K8S image pull secret?
*/}}
{{- define "hush-sensor.shouldCreateKubeImagePullSecret" -}}
{{- $username := (include "hush-sensor.kubeImagePullSecretUsername" .) -}}
{{- $password := (include "hush-sensor.kubeImagePullSecretPassword" .) -}}
{{- if and $username $password -}}
true
{{- end }}
{{- end }}

{{/*
K8S image pull secret name
*/}}
{{- define "hush-sensor.kubeImagePullSecretName" -}}
{{- $defaultPullSecretName :=
    (printf "%s-%s" (include "hush-sensor.fullName" .) "imagepullsecret") }}
{{- default $defaultPullSecretName .Values.image.pullSecret.name }}
{{- end }}

{{/*
The data to put in K8S image pull Secret
*/}}
{{- define "hush-sensor.kubeImagePullSecretData" -}}
{{- $msg := "couldn't find image registry definition. 'image.registry' or 'image.pullToken' must be defined." -}}
{{- $registry := required $msg (include "hush-sensor.imageRegistry" .) -}}
{{- $username := (include "hush-sensor.kubeImagePullSecretUsername" .) -}}
{{- $password := (include "hush-sensor.kubeImagePullSecretPassword" .) -}}
{{- $userPass := printf "%s:%s" $username $password -}}
{{- $value := printf "{\"auths\": {\"%s\": {\"auth\": \"%s\"}}}"
    $registry ($userPass | b64enc) -}}
{{- $value | b64enc }}
{{- end }}

{{/*
PullSecret effective list
*/}}
{{- define "hush-sensor.kubeImagePullSecretEffectiveList" -}}
    {{- if and .Values.image .Values.image.pullSecretList -}}
        {{- .Values.image.pullSecretList | toYaml }}
    {{- else -}}
        {{- if (include "hush-sensor.shouldCreateKubeImagePullSecret" .) -}}
- name: {{ include "hush-sensor.kubeImagePullSecretName" . | quote }}
        {{- end }}
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
{{- $keyRef := and .Values.hushDeployment .Values.hushDeployment.secretKeyRef -}}
{{- $name := and $keyRef $keyRef.name -}}
{{- $key := and $keyRef $keyRef.key -}}
{{- if not (and $name $key) -}}
true
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
        "name" (include "hush-sensor.deploymentKubeSecretName" .)
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
{{- if (include "hush-sensor.shouldCreateDeploymentKubeSecret" .) -}}
    {{- dict
        "name" (include "hush-sensor.deploymentKubeSecretName" .)
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

{{/*
Build image path from components
*/}}
{{- define "hush-sensor.buildImagePath" -}}
{{- if .registry -}}
    {{- printf "%s/%s:%s" .registry .repository .tag -}}
{{- else }}
    {{- printf "%s:%s" .repository .tag -}}
{{- end }}
{{- end }}

{{/*
Sensor image path
*/}}
{{- define "hush-sensor.sensorImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-sensor.imageRegistry" .)
    "repository" .Values.image.sensorRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}

{{/*
Vector image path
*/}}
{{- define "hush-sensor.sensorVectorImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-sensor.imageRegistry" .)
    "repository" .Values.image.sensorVectorRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}

{{/*
Sentry image path
*/}}
{{- define "hush-sensor.sentryImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-sensor.imageRegistry" .)
    "repository" .Values.image.sentryRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}

{{/*
Connector Client image path
*/}}
{{- define "hush-sensor.connectorClientImagePath" -}}
{{- include "hush-sensor.verifyConnectorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-sensor.imageRegistry" .)
    "repository" .Values.image.connectorClientRepository
    "tag" .Values.image.connectorTag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}

{{/*
Connector Forwarder image path
*/}}
{{- define "hush-sensor.connectorForwarderImagePath" -}}
{{- include "hush-sensor.verifyConnectorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-sensor.imageRegistry" .)
    "repository" .Values.image.connectorForwarderRepository
    "tag" .Values.image.connectorTag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}

{{/*
Vermon image path
*/}}
{{- define "hush-sensor.vermonImagePath" -}}
{{- include "hush-sensor.verifySensorMinimumSupportedVersion" . -}}
{{- $ctx := dict
    "registry" (include "hush-sensor.imageRegistry" .)
    "repository" .Values.image.vermonRepository
    "tag" .Values.image.sensorTag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}

{{/*
b64dec with error check
*/}}
{{- define "hush-sensor.b64decode" -}}
{{- $decoded := b64dec .value -}}
{{- if contains "illegal base64" $decoded -}}
    {{- fail (printf "failed to base64 decode %s: %s" .name $decoded) -}}
{{- end -}}
{{- printf "%s" $decoded -}}
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
