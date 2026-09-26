variable "kubeconfig" {
  description = "Minified kubeconfig for the lab context, written by lab/lab.sh."
  type        = string
}

variable "lab_name" {
  description = "Datadog cluster name and env tag for this lab."
  type        = string
}

variable "dd_site" {
  description = "Datadog site, e.g. datadoghq.eu."
  type        = string
}

variable "apm_enabled" {
  description = "Single Step Instrumentation for namespace train-ticket."
  type        = bool
}

variable "kubelet_tls_verify" {
  description = "global.kubelet.tlsVerify. false is required on OpenShift, Rancher, VMware VKS/TKG and AKS."
  type        = bool
}
