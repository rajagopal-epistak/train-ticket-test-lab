variable "kubeconfig" {
  description = "Minified kubeconfig for the lab context, written by lab/lab.sh."
  type        = string
}

variable "lab_name" {
  description = "Datadog cluster name, env tag and monitor-name prefix for this lab."
  type        = string
}

variable "dd_site" {
  description = "Datadog site, e.g. datadoghq.eu."
  type        = string
}

variable "apm_enabled" {
  description = "Create the APM monitors."
  type        = bool
}

variable "apm_hosts_budget" {
  description = "Alert when estimated APM hosts exceed this."
  type        = number
}

variable "apm_ingest_gb_budget" {
  description = "Monthly ingested-span budget in GB; the monitor alerts on a daily share."
  type        = number
}

variable "telemetry_file" {
  description = "Per-service logs_off / apm_off switches."
  type        = string
}
