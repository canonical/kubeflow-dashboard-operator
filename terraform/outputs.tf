output "app_name" {
  value = juju_application.kubeflow_dashboard.name
}

output "provides" {
  value = {
    grafana_dashboard = "grafana-dashboard",
    links             = "links",
    metrics_endpoint  = "metrics-endpoint",
    provide_cmr_mesh  = "provide-cmr-mesh"
  }
}

output "requires" {
  value = {
    ingress             = "ingress",
    istio_ingress_route = "istio-ingress-route",
    kubeflow_profiles   = "kubeflow-profiles",
    logging             = "logging",
    require_cmr_mesh    = "require-cmr-mesh",
    service_mesh        = "service-mesh"
  }
}
