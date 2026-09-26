# Namespace and the four infrastructure charts, with the values `make deploy` uses (hack/deploy/utils.sh).

locals {
  repo   = abspath("${path.module}/../../..")
  charts = "${local.repo}/deployment/kubernetes-manifests/quickstart-k8s/charts"
}

resource "kubernetes_namespace_v1" "train_ticket" {
  metadata {
    name   = "train-ticket"
    labels = { lab = var.lab_name }
  }
}

# The MySQL and Nacos charts run 3-replica StatefulSets whose replicas start in order: a MySQL release took
# ~22 min on the first live run, past the 900 s these had. RabbitMQ is a Deployment and keeps 900 s.
# upgrade_install (`helm upgrade --install`): a release whose install timed out isn't in state, and a plain
# install of the same name is refused, so the next `up` takes the leftover release over instead.
resource "helm_release" "nacosdb" {
  name            = "nacosdb"
  chart           = "${local.charts}/mysql"
  namespace       = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout         = 1800
  upgrade_install = true
  set = [
    { name = "mysql.mysqlUser", value = "nacos" },
    { name = "mysql.mysqlPassword", value = "Abcd1234#" },
    { name = "mysql.mysqlDatabase", value = "nacos" },
  ]
}

# The vendored RadonDB MySQL chart creates root@localhost and root@127.0.0.1 only. Where pods have an IPv6 loopback,
# xenon's health check (root@localhost:3306) arrives from ::1, is denied under skip-name-resolve, and no leader is
# ever elected, so the -leader Service stays empty (upstream train-ticket #234, #233, #246, #268). RadonDB's own fix
# (radondb-mysql-kubernetes #441) is a root@::1 account; add it on every pod, outside the binlog.
resource "terraform_data" "mysql_root_ipv6" {
  for_each         = { nacosdb = helm_release.nacosdb.metadata, tsdb = helm_release.tsdb.metadata }
  triggers_replace = [each.value]
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    environment = { KUBECONFIG = var.kubeconfig, RELEASE = each.key }
    command     = <<-EOT
      set -euo pipefail
      pods=$(kubectl -n train-ticket get pods -l release="$RELEASE" -o name)
      [ -n "$pods" ] || { echo "no pods for MySQL release $RELEASE" >&2; exit 1; }
      for pod in $pods; do
        # Skip pods that have it: once a leader exists, xenon makes followers super_read_only (ERROR 1290).
        has=$(kubectl -n train-ticket exec "$pod" -c mysql -- mysql -uroot -N -e \
          "SELECT COUNT(*) FROM mysql.user WHERE user='root' AND host='::1'")
        [ "$has" = 1 ] && continue
        kubectl -n train-ticket exec "$pod" -c mysql -- mysql -uroot -e \
          "SET SESSION sql_log_bin=0; CREATE USER IF NOT EXISTS 'root'@'::1'; GRANT ALL PRIVILEGES ON *.* TO 'root'@'::1' WITH GRANT OPTION;"
      done
    EOT
  }
}

resource "helm_release" "nacos" {
  name            = "nacos"
  chart           = "${local.charts}/nacos"
  namespace       = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout         = 1800
  upgrade_install = true
  set = [
    { name = "nacos.db.host", value = "nacosdb-mysql-leader" },
    { name = "nacos.db.username", value = "nacos" },
    { name = "nacos.db.name", value = "nacos" },
    { name = "nacos.db.password", value = "Abcd1234#" },
  ]
  depends_on = [terraform_data.mysql_root_ipv6["nacosdb"]]
}

resource "helm_release" "rabbitmq" {
  name            = "rabbitmq"
  chart           = "${local.charts}/rabbitmq"
  namespace       = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout         = 900
  upgrade_install = true
}

resource "helm_release" "tsdb" {
  name            = "tsdb"
  chart           = "${local.charts}/mysql"
  namespace       = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout         = 1800
  upgrade_install = true
  set = [
    { name = "mysql.mysqlUser", value = "ts" },
    { name = "mysql.mysqlPassword", value = "Ts_123456" },
    { name = "mysql.mysqlDatabase", value = "ts" },
  ]
}
