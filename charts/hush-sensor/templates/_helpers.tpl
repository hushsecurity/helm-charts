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
{{- $parts := .Values.deploymentToken | b64dec | split ":" -}}
{{- $zone := trimPrefix "m" $parts._0 | trimSuffix "prd" -}}
{{- $zone = ternary "" (printf "%s." $zone) (not $zone) -}}
{{- $uri := printf "https://events.%s.%shush-security.com/v1/runtime-events" $parts._1 $zone -}}
{{- $result := dict
    "orgId" $parts._2
    "deploymentId" $parts._3
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
Should we create the image pull secret?
*/}}
{{- define "hush-sensor.shouldCreateImagePullSecret" -}}
{{- $hasPullSecret := (and .Values.image .Values.image.pullSecret) -}}
{{- $hasUsername := (and $hasPullSecret .Values.image.pullSecret.username) -}}
{{- if and $hasUsername .Values.image.pullSecret.password -}}
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
{{- $msg := "'image.registry' must be provided for image pull secret creation" -}}
{{- $registry := required $msg .Values.image.registry -}}
{{- $userPass := printf "%s:%s"
    .Values.image.pullSecret.username
    .Values.image.pullSecret.password -}}
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
    "registry" .Values.image.registry
    "repository" .Values.image.sensorRepository
    "tag" .Values.image.tag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}

{{/*
Vector image path
*/}}
{{- define "hush-sensor.vectorImagePath" -}}
{{- $ctx := dict
    "registry" .Values.image.registry
    "repository" .Values.image.vectorRepository
    "tag" .Values.image.tag
-}}
{{- include "hush-sensor.buildImagePath" $ctx -}}
{{- end }}
