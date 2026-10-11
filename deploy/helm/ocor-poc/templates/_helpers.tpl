{{- define "ocor-poc.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "ocor-poc.compose" -}}
{{- .Files.Get "compose.profiles.yaml" | fromYaml | toJson -}}
{{- end -}}

{{- define "ocor-poc.secret" -}}
{{- required "operational.secretName is required (OpenBao token, operator token, PGPASSWORD created out of band)" .Values.operational.secretName -}}
{{- end -}}

{{- define "ocor-poc.vault" -}}
{{- required "operational.vault.existingClaim is required: the backup vault must live outside the workload fault domain" .Values.operational.vault.existingClaim -}}
{{- end -}}

{{- define "ocor-poc.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .Values.operational.runAsUser }}
  runAsGroup: {{ .Values.operational.runAsUser }}
  fsGroup: {{ .Values.operational.runAsUser }}
  seccompProfile: {type: RuntimeDefault}
{{- with .Values.operational.hostAliases }}
hostAliases:
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "ocor-poc.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: {drop: [ALL]}
{{- end -}}

{{- define "ocor-poc.opsEnv" -}}
- name: OCOR_OPENBAO_TOKEN
  valueFrom: {secretKeyRef: {name: {{ include "ocor-poc.secret" . }}, key: OCOR_OPENBAO_TOKEN}}
- name: OCOR_OPS_OPERATOR_TOKEN
  valueFrom: {secretKeyRef: {name: {{ include "ocor-poc.secret" . }}, key: OCOR_OPS_OPERATOR_TOKEN}}
- name: PYTHONDONTWRITEBYTECODE
  value: "1"
{{- end -}}

{{- /*
Workload image of a pinned role (ops, postgresql, kafka, qdrant), rendered only from
`ocor.images.pins`: the executed artifact is the one the release binding covers.
*/ -}}
{{- define "ocor-poc.image" -}}
{{- $root := index . 0 -}}
{{- $role := index . 1 -}}
{{- range $key := list "image" "postgresImage" "kafkaImage" "qdrantImage" -}}
{{- if hasKey $root.Values.operational $key -}}
{{- fail (printf "operational.%s is not accepted: workload images derive only from ocor.images.pins" $key) -}}
{{- end -}}
{{- end -}}
{{- $ref := required (printf "ocor.images.pins.%s is required" $role) (index $root.Values.ocor.images.pins $role) -}}
{{- if not (regexMatch "^[a-z0-9]+([._/:-][a-z0-9]+)*@sha256:[0-9a-f]{64}$" (toString $ref)) -}}
{{- fail (printf "ocor.images.pins.%s must be digest-pinned (name@sha256:<64 hex>): %v" $role $ref) -}}
{{- end -}}
{{- $ref -}}
{{- end -}}
