output "app_name" {
  value = juju_application.kubeflow_dashboard.name
}

output "provides" {
  value = {
    links             = "links",
    grafana_dashboard = "grafana-dashboard",
    metrics_endpoint  = "metrics-endpoint"
  }
}

output "requires" {
  value = {
    ingress           = "ingress",
    kubeflow_profiles = "kubeflow-profiles",
    logging           = "logging"
  }
}
