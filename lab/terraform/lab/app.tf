# The Train-Ticket objects `make deploy` applies, plus flagd and the traffic driver, decoded from the committed YAML.
# deploy.yaml.sample is the deployed file as-is: make deploy's sed (nacos -> nacos, rabbitmq -> rabbitmq) is a no-op.

locals {
  yamls = "${local.repo}/deployment/kubernetes-manifests/quickstart-k8s/yamls"

  telemetry = yamldecode(file(var.telemetry_file))
  logs_off  = toset(coalesce(try(local.telemetry.logs_off, null), []))
  apm_off   = toset(coalesce(try(local.telemetry.apm_off, null), []))

  flagd_docs = provider::kubernetes::manifest_decode_multi(file("${local.repo}/deployment/lab/flagd.yaml"))

  deployment_docs = concat(
    provider::kubernetes::manifest_decode_multi(file("${local.yamls}/deploy.yaml.sample")),
    [for d in local.flagd_docs : d if d.kind == "Deployment"],
    provider::kubernetes::manifest_decode_multi(file("${local.repo}/deployment/lab/traffic-driver.yaml")),
  )

  other_docs = concat(
    provider::kubernetes::manifest_decode_multi(file("${local.yamls}/secret.yaml")),
    provider::kubernetes::manifest_decode_multi(file("${local.yamls}/svc.yaml")),
    [for d in local.flagd_docs : d if d.kind != "Deployment"],
    [yamldecode(file("${local.repo}/templates/flagd-config.yaml"))],
  )

  # Every pod template gets ad.datadoghq.com/tags, so the Agent tags this lab's metrics, logs and traces
  # even when the Agent is not ours (docs.datadoghq.com/containers/kubernetes/tag). logs_off adds
  # ad.datadoghq.com/logs_exclude on top; apm_off adds the pod label admission.datadoghq.com/enabled=false.
  deployments = {
    for d in local.deployment_docs : d.metadata.name => merge(d, {
      metadata = merge(d.metadata, { namespace = "train-ticket" })
      spec = merge(d.spec, {
        template = merge(d.spec.template, {
          metadata = merge(
            d.spec.template.metadata,
            {
              labels = merge(
                d.spec.template.metadata.labels,
                { for k, v in { "admission.datadoghq.com/enabled" = "false" } : k => v if contains(local.apm_off, d.metadata.name) },
              )
            },
            {
              annotations = merge(
                try(d.spec.template.metadata.annotations, {}),
                { "ad.datadoghq.com/tags" = jsonencode({ lab = var.lab_name }) },
                { for k, v in { "ad.datadoghq.com/logs_exclude" = "true" } : k => v if contains(local.logs_off, d.metadata.name) },
              )
            },
          )
        })
      })
    })
  }

  # kubernetes_manifest plans stringData as given, but the API never returns it (the server moves it into data),
  # so Terraform sees an inconsistent result after apply. Send Secrets as data (base64), never stringData.
  others = {
    for d in local.other_docs : "${d.kind}/${d.metadata.name}" => merge(
      { for k, v in d : k => v if k != "stringData" },
      { metadata = merge(d.metadata, { namespace = "train-ticket" }) },
      { for k, v in { data = merge(try(d.data, {}), { for sk, sv in try(d.stringData, {}) : sk => base64encode(sv) }) } : k => v if can(d.stringData) },
    )
  }

  unknown_services = sort(tolist(setsubtract(setunion(local.logs_off, local.apm_off), keys(local.deployments))))
}

resource "terraform_data" "telemetry_check" {
  lifecycle {
    precondition {
      condition     = length(local.unknown_services) == 0
      error_message = "lab/telemetry.yaml names unknown deployments: ${join(", ", local.unknown_services)}"
    }
  }
}

resource "kubernetes_manifest" "others" {
  for_each = local.others
  manifest = each.value
  field_manager {
    force_conflicts = true
  }
  depends_on = [kubernetes_namespace_v1.train_ticket]
}

resource "kubernetes_manifest" "deployments" {
  for_each = local.deployments
  manifest = each.value
  field_manager {
    force_conflicts = true
  }
  # computed_fields replaces, not extends, the provider's default (metadata.annotations, metadata.labels).
  # spec.template.metadata.annotations must stay tolerated too: kubectl rollout restart adds
  # kubectl.kubernetes.io/restartedAt there, and G5's fallback, every fault.sh flag toggle and a
  # cost-saving restart all do that, which would otherwise break the next apply.
  computed_fields = ["metadata.annotations", "metadata.labels", "spec.template.metadata.annotations"]
  depends_on = [
    terraform_data.telemetry_check,
    kubernetes_manifest.others,
    helm_release.nacos,
    helm_release.rabbitmq,
    helm_release.tsdb,
  ]
}
