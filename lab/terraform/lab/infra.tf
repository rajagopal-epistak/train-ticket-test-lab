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

resource "helm_release" "nacosdb" {
  name      = "nacosdb"
  chart     = "${local.charts}/mysql"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
  set = [
    { name = "mysql.mysqlUser", value = "nacos" },
    { name = "mysql.mysqlPassword", value = "Abcd1234#" },
    { name = "mysql.mysqlDatabase", value = "nacos" },
  ]
}

resource "helm_release" "nacos" {
  name      = "nacos"
  chart     = "${local.charts}/nacos"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
  set = [
    { name = "nacos.db.host", value = "nacosdb-mysql-leader" },
    { name = "nacos.db.username", value = "nacos" },
    { name = "nacos.db.name", value = "nacos" },
    { name = "nacos.db.password", value = "Abcd1234#" },
  ]
  depends_on = [helm_release.nacosdb]
}

resource "helm_release" "rabbitmq" {
  name      = "rabbitmq"
  chart     = "${local.charts}/rabbitmq"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
}

resource "helm_release" "tsdb" {
  name      = "tsdb"
  chart     = "${local.charts}/mysql"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
  set = [
    { name = "mysql.mysqlUser", value = "ts" },
    { name = "mysql.mysqlPassword", value = "Ts_123456" },
    { name = "mysql.mysqlDatabase", value = "ts" },
  ]
}
