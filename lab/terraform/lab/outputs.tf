output "monitor_ids" {
  description = "Monitor key => Datadog monitor id, read by lab/lab.sh test."
  value       = { for k, m in datadog_monitor.lab : k => m.id }
}
