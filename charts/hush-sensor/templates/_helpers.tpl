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
Create chart name and version as used by the chart label.
*/}}
{{- define "hush-sensor.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version
    | replace "+" "_" | trunc 63 | trimSuffix "-" }}
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
Hush deployment info
*/}}
{{- define "hush-sensor.deploymentInfo" -}}
{{- $ctx := dict "name" "deploymentToken" "value" .Values.deploymentToken -}}
{{- $deploymentToken := (include "hush-sensor.b64decode" $ctx) -}}
{{- $parts := split ":" $deploymentToken -}}
{{- if ne $parts._0 "d1" -}}
    {{- fail (printf "deploymentToken version '%s' isn't supported" $parts._0) -}}
{{- end -}}
{{- $zone := trimPrefix "m" $parts._1 | trimSuffix "prd" -}}
{{- $zone = ternary "" (printf "%s." $zone) (not $zone) -}}
{{- $uri := printf "https://events.%s.%shush-security.com/v1/runtime-events" $parts._2 $zone -}}
{{- $result := dict
    "orgId" $parts._3
    "deploymentId" $parts._4
    "eventReportingUri" $uri
-}}
{{- $result | toYaml -}}
{{- end }}

{{/*
Deployment secret name
*/}}
{{- define "hush-sensor.deploymentSecretName" -}}
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
Get image pull secret username
*/}}
{{- define "hush-sensor.imagePullSecretUsername" -}}
{{- $token := (include "hush-sensor.parsePullToken" . | fromYaml) -}}
{{- $hasPullSecret := (and .Values.image .Values.image.pullSecret) -}}
{{- $username := and $hasPullSecret .Values.image.pullSecret.username -}}
{{- default $username (get $token "username") -}}
{{- end }}

{{/*
Get image pull secret password
*/}}
{{- define "hush-sensor.imagePullSecretPassword" -}}
{{- $token := (include "hush-sensor.parsePullToken" . | fromYaml) -}}
{{- $hasPullSecret := (and .Values.image .Values.image.pullSecret) -}}
{{- $password := and $hasPullSecret .Values.image.pullSecret.password -}}
{{- default $password (get $token "password") -}}
{{- end }}

{{/*
Parse image.pullToken
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
Should we create the image pull secret?
*/}}
{{- define "hush-sensor.shouldCreateImagePullSecret" -}}
{{- $username := (include "hush-sensor.imagePullSecretUsername" .) -}}
{{- $password := (include "hush-sensor.imagePullSecretPassword" .) -}}
{{- if and $username $password -}}
true
{{- end }}
{{- end }}

{{/*
PullSecret name
*/}}
{{- define "hush-sensor.imagePullSecretName" -}}
{{- $defaultPullSecretName :=
    (printf "%s-%s" (include "hush-sensor.fullName" .) "imagepullsecret") }}
{{- default $defaultPullSecretName .Values.image.pullSecret.name }}
{{- end }}

{{/*
PullSecret value
*/}}
{{- define "hush-sensor.imagePullSecretValue" -}}
{{- $msg := "couldn't find image registry definition. 'image.registry' or 'image.pullToken' must be defined." -}}
{{- $registry := required $msg (include "hush-sensor.imageRegistry" .) -}}
{{- $username := (include "hush-sensor.imagePullSecretUsername" .) -}}
{{- $password := (include "hush-sensor.imagePullSecretPassword" .) -}}
{{- $userPass := printf "%s:%s" $username $password -}}
{{- $value := printf "{\"auths\": {\"%s\": {\"auth\": \"%s\"}}}"
    $registry ($userPass | b64enc) -}}
{{- $value | b64enc }}
{{- end }}

{{/*
PullSecret effective list
*/}}
{{- define "hush-sensor.imagePullSecretEffectiveList" -}}
    {{- if and .Values.image .Values.image.pullSecretList -}}
        {{- .Values.image.pullSecretList | toYaml }}
    {{- else -}}
        {{- if (include "hush-sensor.shouldCreateImagePullSecret" .) -}}
- name: {{ include "hush-sensor.imagePullSecretName" . | quote }}
        {{- end }}
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
{{- $ctx := dict
    "registry" (include "hush-sensor.imageRegistry" .)
    "repository" .Values.image.sensorVectorRepository
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
{{- define "hush-sensor.containerdMountPath" -}}
{{- $path := (include "hush-sensor.criSocketPath" .) -}}
{{- if $path -}}
    {{- dir $path -}}
{{- else -}}
    {{- printf "%s" "/run/containerd" -}}
{{- end -}}
{{- end }}
