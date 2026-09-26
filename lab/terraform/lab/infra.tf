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
resource "helm_release" "nacosdb" {
  name      = "nacosdb"
  chart     = "${local.charts}/mysql"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 1800
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
  timeout   = 1800
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
  timeout   = 1800
  set = [
    { name = "mysql.mysqlUser", value = "ts" },
    { name = "mysql.mysqlPassword", value = "Ts_123456" },
    { name = "mysql.mysqlDatabase", value = "ts" },
  ]
}
