# Stage 1: the Datadog Operator, then the DatadogAgent it reconciles.
# The DatadogAgent ships as a local chart because a kubernetes_manifest needs its CRD at plan time;
# a helm_release only needs it at apply time, after the Operator release has installed it.
# Namespace `datadog` and Secret `datadog-secret` are created by lab/lab.sh, so the API keys never enter Terraform state.

resource "helm_release" "operator" {
  name       = "datadog-operator"
  repository = "https://helm.datadoghq.com"
  chart      = "datadog-operator"
  version    = "2.27.0"
  namespace  = "datadog"
  wait       = true
  timeout    = 600
}

resource "helm_release" "agent" {
  name      = "datadog-agent"
  chart     = "${path.module}/agent-chart"
  namespace = "datadog"
  wait      = true
  timeout   = 600
  values = [yamlencode({
    labName          = var.lab_name
    site             = var.dd_site
    apmEnabled       = var.apm_enabled
    kubeletTlsVerify = var.kubelet_tls_verify
  })]
  depends_on = [helm_release.operator]
}
