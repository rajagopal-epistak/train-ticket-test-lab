# Fault-agnostic monitors. No notification handle: lab/lab.sh reads their state through the API.
# Thresholds are initial values, tuned after the first baseline.

locals {
  apm_scope = "env:${var.lab_name}"
  k8s_scope = "kube_cluster_name:${var.lab_name},kube_namespace:train-ticket"
  log_scope = "kube_namespace:train-ticket service:tt-traffic-driver"

  apm_monitors = {
    java_latency = {
      name = "Java p95 latency by service", type = "query alert", critical = 2
      expr = "percentile(last_10m):p95:trace.servlet.request{${local.apm_scope}} by {service}"
    }
    voucher_latency = {
      name = "Voucher p95 latency", type = "query alert", critical = 2
      expr = "percentile(last_10m):p95:trace.tornado.request{${local.apm_scope}} by {service}"
    }
    java_errors = {
      name = "Java error rate by service", type = "query alert", critical = 0.1
      expr = "sum(last_10m):sum:trace.servlet.request.errors{${local.apm_scope}} by {service}.as_count() / sum:trace.servlet.request.hits{${local.apm_scope}} by {service}.as_count()"
    }
    voucher_errors = {
      name = "Voucher error rate", type = "query alert", critical = 0.1
      expr = "sum(last_10m):sum:trace.tornado.request.errors{${local.apm_scope}} by {service}.as_count() / sum:trace.tornado.request.hits{${local.apm_scope}} by {service}.as_count()"
    }
  }

  base_monitors = {
    oom_killed = {
      name = "OOMKilled by deployment", type = "query alert", critical = 1
      expr = "max(last_10m):max:kubernetes.containers.state.terminated{${local.k8s_scope},reason:oomkilled} by {kube_deployment}"
    }
    restarts = {
      name = "Restarts by deployment", type = "query alert", critical = 2
      expr = "change(max(last_10m),last_10m):sum:kubernetes.containers.restarts{${local.k8s_scope}} by {kube_deployment}"
    }
    edge_5xx = {
      name = "Edge 5xx by path", type = "log alert", critical = 2
      expr = "logs(\"${local.log_scope} @evt:outcome (@http_status:500 OR @http_status:502 OR @http_status:503 OR @http_status:504)\").index(\"*\").rollup(\"count\").by(\"@path\").last(\"10m\")"
    }
    edge_4xx = {
      name = "Edge 4xx by path", type = "log alert", critical = 5
      expr = "logs(\"${local.log_scope} @evt:outcome (@http_status:400 OR @http_status:401 OR @http_status:403 OR @http_status:404 OR @http_status:413)\").index(\"*\").rollup(\"count\").by(\"@path\").last(\"10m\")"
    }
    business_rejections = {
      name = "Business rejections by path", type = "log alert", critical = 20
      expr = "logs(\"${local.log_scope} @evt:outcome @tt_status:0\").index(\"*\").rollup(\"count\").by(\"@path\").last(\"10m\")"
    }
    fare_anomaly = {
      name = "Fare anomaly", type = "log alert", critical = 0
      expr = "logs(\"${local.log_scope} @evt:fare_anomaly\").index(\"*\").rollup(\"count\").last(\"10m\")"
    }
    apm_hosts_budget = {
      name = "APM hosts budget", type = "query alert", critical = var.apm_hosts_budget
      expr = "max(last_1h):max:datadog.estimated_usage.apm_hosts{*}"
    }
    apm_ingest_budget = {
      name = "APM ingestion budget (daily share)", type = "query alert", critical = floor(var.apm_ingest_gb_budget * 1000000000 / 30)
      expr = "sum(last_1d):sum:datadog.estimated_usage.apm.ingested_bytes{*}.as_count()"
    }
  }

  monitors = merge(local.base_monitors, { for k, v in local.apm_monitors : k => v if var.apm_enabled })
}

resource "datadog_monitor" "lab" {
  for_each = local.monitors

  name                = "[${var.lab_name}] ${each.value.name}"
  type                = each.value.type
  query               = "${each.value.expr} > ${each.value.critical}"
  message             = "Train-Ticket lab ${var.lab_name}: ${each.value.name}. No notification handle by design."
  require_full_window = false
  notify_no_data      = false
  tags                = ["lab:${var.lab_name}", "managed-by:terraform"]

  monitor_thresholds {
    critical = each.value.critical
  }
}
