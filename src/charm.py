#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import traceback

from pathlib import Path
from typing import Dict

from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.resources.core_v1 import ConfigMap
from ops.charm import CharmBase, RelationChangedEvent, RelationBrokenEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import ChangeError, Layer
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)

BASE_SIDEBAR = Path("src/config/sidebar_config.json").read_text()
DEFAULT_RESOURCE_FILES = {
    "profiles": "src/templates/profile_crds.yaml.j2",
    "auths": "src/templates/auth_manifests.yaml.j2",
    "config_maps": "src/templates/configmaps.yaml.j2",
}


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg: str, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


class KubeflowDashboardOperator(CharmBase):
    """A Juju Charm for Kubeflow Dashboard Operator"""

    def __init__(self, *args):
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._profiles_service = None
        self._name = self.model.app.name
        self._service = "npm start"
        self._container_name = "kubeflow-dashboard"
        self._container = self.unit.get_container(self._name)
        self._resource_files = DEFAULT_RESOURCE_FILES
        self._context = {
            "app_name": self._name,
            "namespace": self._namespace,
            "configmap_name": self.model.config["dashboard-configmap"],
            "profilename": self.model.config["profile"],
            "links": BASE_SIDEBAR,
            "settings": json.dumps({"DASHBOARD_FORCE_IFRAME": True}),
        }
        self._k8s_resource_handler = None
        self.service_patcher = KubernetesServicePatch(
            self, [(self._container_name, self.model.config["port"])]
        )
        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["kubeflow-profiles"].relation_changed,
            self.on["ingress"].relation_changed,
            self.on.kubeflow_dashboard_pebble_ready,
        ]:
            self.framework.observe(event, self.main)

        self.framework.observe(
            self.on.sidebar_relation_changed, self._on_sidebar_relation_changed
        )
        self.framework.observe(
            self.on.sidebar_relation_broken, self._on_sidebar_relation_broken
        )

        self.framework.observe(self.on.remove, self._on_remove)

    @property
    def profiles_service(self):
        return self._profiles_service

    @profiles_service.setter
    def profiles_service(self, service):
        self._profiles_service = service

    @property
    def container(self):
        return self._container

    @property
    def k8s_resource_handler(self):
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=self._resource_files.values(),
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KubernetesResourceHandler):
        self._k8s_resource_handler = handler

    @property
    def _kubeflow_dashboard_operator_layer(self) -> Layer:
        layer_config = {
            "summary": "kubeflow-dashboard-operator layer",
            "description": "pebble config layer for kubeflow_dashboard_operator",
            "services": {
                self._container_name: {
                    "override": "replace",
                    "summary": "entrypoint of the kubeflow_dashboard_operator image",
                    "command": self._service,
                    "startup": "enabled",
                    "environment": {
                        "USERID_HEADER": "kubeflow-userid",
                        "USERID_PREFIX": "",
                        "PROFILES_KFAM_SERVICE_HOST": f"{self.profiles_service}.{self.model.name}",
                        "REGISTRATION_FLOW": self.model.config["registration-flow"],
                        "DASHBOARD_LINKS_CONFIGMAP": self.model.config[
                            "dashboard-configmap"
                        ],
                    },
                }
            },
        }
        return Layer(layer_config)

    def _check_container_connection(self):
        if not self.container.can_connect():
            raise CheckFailed("Waiting for pod startup to complete", WaitingStatus)

    def _check_model_name(self):
        if self.model.name != "kubeflow":
            # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
            raise CheckFailed(
                "kubeflow-dashboard must be deployed to model named `kubeflow`:"
                " https://git.io/J6d35",
                BlockedStatus,
            )

    def _check_leader(self):
        if not self.unit.is_leader():
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _update_layer(self) -> None:
        """Updates the Pebble configuration layer if changed."""
        current_layer = self.container.get_plan()
        new_layer = self._kubeflow_dashboard_operator_layer
        self.logger.debug(f"NEW LAYER: {new_layer}")
        if current_layer.services != new_layer.services:
            self.unit.status = MaintenanceStatus("Applying new pebble layer")
            self.container.add_layer(self._container_name, new_layer, combine=True)
            try:
                self.logger.info(
                    "Pebble plan updated with new configuration, replaning"
                )
                self.container.replan()
            except ChangeError:
                raise CheckFailed("Failed to replan", BlockedStatus)

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def handle_ingress(self, interfaces):
        if interfaces["ingress"]:
            interfaces["ingress"].send_data(
                {
                    "prefix": "/",
                    "rewrite": "/",
                    "service": self.model.app.name,
                    "port": self.model.config["port"],
                }
            )

    def _check_kf_profiles(self, interfaces):
        if not (
            (kf_profiles := interfaces["kubeflow-profiles"]) and kf_profiles.get_data()
        ):
            raise CheckFailed(
                "Waiting for kubeflow-profiles relation data", WaitingStatus
            )

        return kf_profiles

    def main(self, event) -> None:
        """Main entry point for the Charm."""
        try:
            self._check_container_connection()
            self._check_model_name()
            self._check_leader()
            interfaces = self._get_interfaces()
            kf_profiles = self._check_kf_profiles(interfaces)
            self.handle_ingress(interfaces)
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        try:
            self.unit.status = MaintenanceStatus("Creating k8s resources")
            self.k8s_resource_handler.apply()
        except ApiError:
            self.logger.error(traceback.format_exc())
            self.unit.status = BlockedStatus("kubernetes resource creation failed")
            return
        self.handle_ingress(interfaces)
        kf_profiles = list(kf_profiles.get_data().values())[0]
        self.profiles_service = kf_profiles["service-name"]
        try:
            self._update_layer()
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        self.model.unit.status = ActiveStatus()

    def _get_sidebar_config(self) -> Dict:
        try:
            current_configmap = self.k8s_resource_handler.lightkube_client.get(
                ConfigMap, name=self._context["configmap_name"]
            )
            old_sidebar_config = json.loads(current_configmap.data["links"])
        except ApiError as e:
            self.logger.warning(
                f"PROBLEM during configmap retrieval {e}. USING BASE CONFIG"
            )
            old_sidebar_config = json.loads(BASE_SIDEBAR)
        return old_sidebar_config

    def _update_sidebar_config(self, links_data: Dict) -> None:
        self._context["links"] = json.dumps(links_data)
        try:
            self.k8s_resource_handler.context = self._context
            self.k8s_resource_handler.template_files = [
                self._resource_files["config_maps"]
            ]
            self.k8s_resource_handler.apply()
        except ApiError as e:
            self.unit.status = BlockedStatus(
                f"kubernetes resource creation failed with {e}"
            )

    def _on_sidebar_relation_changed(self, event: RelationChangedEvent) -> None:
        if not self.unit.is_leader():
            return
        new_links_string = event.relation.data[event.app].get("config")
        if new_links_string is None:
            self.logger.info("No links found in relation data, skipping")
            return
        self.unit.status = MaintenanceStatus("Adjusting sidebar configmap")
        old_sidebar_config = self._get_sidebar_config()
        new_links = json.loads(new_links_string)
        new_valid_links = [
            link for link in new_links if link not in old_sidebar_config["menuLinks"]
        ]
        old_sidebar_config["menuLinks"] = (
            old_sidebar_config["menuLinks"] + new_valid_links
        )
        old_sidebar_config["menuLinks"] = sorted(
            old_sidebar_config["menuLinks"], key=lambda x: x["text"]
        )
        self._update_sidebar_config(old_sidebar_config)
        self.model.unit.status = ActiveStatus()

    def _on_sidebar_relation_broken(self, event: RelationBrokenEvent) -> None:
        if not self.unit.is_leader():
            return
        self.logger.info(f"{event.app.name} relation broken")
        self.unit.status = MaintenanceStatus("Adjusting sidebar configmap")
        old_sidebar_config = self._get_sidebar_config()
        new_menu_links = [
            conf
            for conf in old_sidebar_config["menuLinks"]
            if conf.get("app", None) != event.app.name
        ]
        if len(new_menu_links) != len(old_sidebar_config["menuLinks"]):
            old_sidebar_config["menuLinks"] = new_menu_links
            self._update_sidebar_config(old_sidebar_config)
        self.model.unit.status = ActiveStatus()

    def _on_remove(self, event):
        self.unit.status = MaintenanceStatus("Removing k8s resources")
        self.k8s_resource_handler._template_files = DEFAULT_RESOURCE_FILES.values()
        manifests = self.k8s_resource_handler.render_manifests()
        self.logger.info(f"MANIFESTS are {manifests}")
        try:
            delete_many(self.k8s_resource_handler.lightkube_client, manifests)
        except ApiError as e:
            self.logger.warning(f"Failed to delete resources: {e}")
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(KubeflowDashboardOperator)
