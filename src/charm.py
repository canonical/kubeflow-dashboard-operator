#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from typing import List

import yaml
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_sidebar import (
    KubeflowDashboardSidebarProvider,
    SidebarItem,
    sidebar_items_to_json,
)
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import ChangeError, Layer
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

ADDITIONAL_SIDEBAR_LINKS_CONFIG = "additional-sidebar-links"
K8S_RESOURCE_FILES = [
    "src/templates/auth_manifests.yaml.j2",
]
CONFIGMAP_FILE = "src/templates/configmaps.yaml.j2"
SIDEBAR_LINKS_ORDER_CONFIG = "sidebar-link-order"
SIDEBAR_RELATION_NAME = "sidebar"


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
        self._configmap_name = self.model.config["dashboard-configmap"]
        self._port = self.model.config["port"]
        self._registration_flow = self.model.config["registration-flow"]
        self._k8s_resource_handler = None
        self._configmap_handler = None

        port = ServicePort(int(self._port), name=f"{self.app.name}")
        self.service_patcher = KubernetesServicePatch(self, [port])

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
        self.framework.observe(self.on.remove, self._on_remove)

        # Handle the Kubeflow Dashboard sidebar relation
        self.sidebar_provider = KubeflowDashboardSidebarProvider(
            charm=self,
            relation_name=SIDEBAR_RELATION_NAME,
        )
        self.framework.observe(self.sidebar_provider.on.data_updated, self.main)

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
    def _context(self) -> dict:
        """Returns the context used to create Kubernetes resources."""
        sidebar_items_as_json = self._get_sidebar_items_as_json()

        return {
            "app_name": self._name,
            "namespace": self._namespace,
            "configmap_name": self._configmap_name,
            "links": sidebar_items_as_json,
            "settings": json.dumps({"DASHBOARD_FORCE_IFRAME": True}),
        }

    @property
    def k8s_resource_handler(self):
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KubernetesResourceHandler):
        self._k8s_resource_handler = handler

    @property
    def configmap_handler(self):
        if not self._configmap_handler:
            self._configmap_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=[CONFIGMAP_FILE],
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._configmap_handler

    @configmap_handler.setter
    def configmap_handler(self, handler: KubernetesResourceHandler):
        self._configmap_handler = handler

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
                        "REGISTRATION_FLOW": self._registration_flow,
                        "DASHBOARD_CONFIGMAP": self._configmap_name,
                        "LOGOUT_URL": "/authservice/logout",
                    },
                }
            },
        }
        return Layer(layer_config)

    def _check_container_connection(self):
        if not self.container.can_connect():
            raise CheckFailed("Pod startup is not complete", MaintenanceStatus)

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
        if current_layer.services != new_layer.services:
            self.unit.status = MaintenanceStatus("Applying new pebble layer")
            self.container.add_layer(self._container_name, new_layer, combine=True)
            try:
                self.logger.info("Pebble plan updated with new configuration, replaning")
                self.container.replan()
            except ChangeError as e:
                raise GenericCharmRuntimeError("Failed to replan") from e

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def _handle_ingress(self, interfaces):
        if interfaces["ingress"]:
            interfaces["ingress"].send_data(
                {
                    "prefix": "/",
                    "rewrite": "/",
                    "service": self.model.app.name,
                    "port": self._port,
                }
            )

    def _check_kf_profiles(self, interfaces):
        kf_profiles = interfaces["kubeflow-profiles"]

        if not kf_profiles:
            raise CheckFailed("Add required relation to kubeflow-profiles", BlockedStatus)

        if not kf_profiles.get_data():
            raise CheckFailed("Waiting for kubeflow-profiles relation data", WaitingStatus)

        return kf_profiles

    def _deploy_k8s_resources(self) -> None:
        try:
            self.unit.status = MaintenanceStatus("Creating k8s resources")
            self.k8s_resource_handler.apply()
            self.configmap_handler.apply()
        except ApiError as e:
            raise GenericCharmRuntimeError("Failed to create K8S resources") from e
        self.model.unit.status = ActiveStatus()

    def _get_data_from_profiles_interface(self, kf_profiles_interface):
        return list(kf_profiles_interface.get_data().values())[0]

    def _get_sidebar_items(self) -> List[SidebarItem]:
        """Returns a list of all SidebarItems for this charm.

        Includes sidebar items defined through relations and user config.
        """
        sidebar_items = []
        sidebar_items.extend(self.sidebar_provider.get_sidebar_items())
        sidebar_items.extend(self._get_sidebar_items_from_config())
        sidebar_items = sort_sidebar_items(
            sidebar_items, preferred_links=self._get_sidebar_items_order_from_config()
        )

        return sidebar_items

    def _get_sidebar_items_as_json(self) -> str:
        """Returns a list of all SidebarItems for this charm, as a JSON string.

        Includes sidebar items defined through relations and user config.
        """
        return sidebar_items_to_json(self._get_sidebar_items())

    def _get_sidebar_items_from_config(self) -> List[SidebarItem]:
        """Returns a list of SidebarItems as defined by the additional-sidebar-links config.

        If there are errors in parsing the config, this returns an empty list and logs a warning.
        """
        error_message = (
            f"Cannot parse user-defined sidebar links from config "
            f"`{ADDITIONAL_SIDEBAR_LINKS_CONFIG}` - ignoring this input."
        )

        sidebar_config = self.model.config[ADDITIONAL_SIDEBAR_LINKS_CONFIG]
        if not sidebar_config:
            return []

        try:
            user_sidebar_links = yaml.safe_load(sidebar_config)
        except yaml.YAMLError as err:
            self.logger.warning(f"{error_message}  Got error: {err}")
            return []

        try:
            user_sidebar_links = [SidebarItem(**item) for item in user_sidebar_links]
        except TypeError as err:
            self.logger.warning(f"{error_message}  Got error: {err}")
            return []

        return user_sidebar_links

    def _get_sidebar_items_order_from_config(self) -> List[str]:
        """Returns a list of strings defining the sidebar-link-order.

        If there are errors in parsing the config, this returns an empty list and logs a warning.
        """
        error_message = (
            f"Cannot parse user-defined sidebar link order from config "
            f"`{SIDEBAR_LINKS_ORDER_CONFIG}` - ignoring this input and leaving links unordered."
        )

        sidebar_link_order = self.model.config[SIDEBAR_LINKS_ORDER_CONFIG]
        try:
            return yaml.safe_load(sidebar_link_order)
        except Exception as err:
            self.logger.warning(f"{error_message}  Got error: {err}")
            return []

    def main(self, _) -> None:
        """Main entry point for the Charm."""
        try:
            self._check_container_connection()
            self._check_model_name()
            self._check_leader()
            interfaces = self._get_interfaces()
            kf_profiles_interface = self._check_kf_profiles(interfaces)
            self._handle_ingress(interfaces)
            self._deploy_k8s_resources()
            kf_profiles = self._get_data_from_profiles_interface(kf_profiles_interface)
            self.profiles_service = kf_profiles["service-name"]
            self._update_layer()
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        self.model.unit.status = ActiveStatus()

    def _on_remove(self, _):
        self.unit.status = MaintenanceStatus("Removing k8s resources")
        k8s_resources_manifests = self.k8s_resource_handler.render_manifests()
        configmap_manifest = self.configmap_handler.render_manifests()
        try:
            delete_many(self.k8s_resource_handler.lightkube_client, k8s_resources_manifests)
            delete_many(self.configmap_handler.lightkube_client, configmap_manifest)
        except ApiError as e:
            self.logger.warning(f"Failed to delete resources, with error: {e}")
            raise e
        self.unit.status = MaintenanceStatus("K8s resources removed")


def sort_sidebar_items(sidebar_items: List[SidebarItem], preferred_links: List[str]):
    """Sorts a list of SidebarItems by their link text, moving preferred links to the top.

    The sorted order of the returned list will be:
    * any links who have a text field that matches a string in `preferred_link_text`, in the order
      specified in preferred_link_text
    * any remaining links, in alphabetical order

    For example, if:
      sidebar_items=[SidebarItem(text="1"...), SidebarItem(text="2"...), SidebarItem(text="3"...)]
      preferred_link_text=["2", "4"]
    The return will be:
      sidebar_items=[SidebarItem(text="2"...), SidebarItem(text="1"...), SidebarItem(text="3"...)]

    If there are any links that have the same text, they will all be placed in the preferred
    links at the top.  They will be in the same order as provided in sidebar_items.  For example:

    For example, if:
      sidebar_items=[
        SidebarItem(text="other"...),
        SidebarItem(text="1", link="1a", ...),
        SidebarItem(text="1", link="1b", ...),
      ]
      preferred_link_text=["1"]
    The return will be:
      sidebar_items=[
        SidebarItem(text="1", link="1a", ...),
        SidebarItem(text="1", link="1b", ...),
        SidebarItem(text="other"...),
      ]

    Args:
        sidebar_items: List of SidebarItems to sort
        preferred_links: List of strings of SidebarItem text values

    Returns:
        Ordered list of SidebarItems
    """
    ordered_sidebar_items = []
    removed_sidebar_items_index = set()
    for preferred_link in preferred_links:
        for i, sidebar_item in enumerate(sidebar_items):
            if sidebar_item.text == preferred_link:
                ordered_sidebar_items.append(sidebar_item)
                removed_sidebar_items_index.add(i)

    remaining_sidebar_items = [item for i, item in enumerate(sidebar_items) if i not in removed_sidebar_items_index]
    remaining_sidebar_items = sorted(remaining_sidebar_items, key=lambda item: item.text)

    return ordered_sidebar_items + remaining_sidebar_items


if __name__ == "__main__":
    main(KubeflowDashboardOperator)
