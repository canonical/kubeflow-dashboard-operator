#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import traceback
from typing import List, Optional

from pathlib import Path

from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from jinja2 import Environment, FileSystemLoader
from lightkube import Client, ApiError, codecs
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.types import PatchType
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
        self._lightkube_client: Optional[Client] = None
        self.env = Environment(loader=FileSystemLoader("src/templates"))
        self._name = self.model.app.name
        self._service = "npm start"
        self._container_name = "kubeflow-dashboard"
        self._container = self.unit.get_container(self._name)
        self._resource_files = {
            "profiles": "profile_crds.yaml.j2",
            "auths": "auth_manifests.yaml.j2",
            "config_maps": "configmaps.yaml.j2",
        }
        self._context = {
            "app_name": self._name,
            "namespace": self._namespace,
            "configmap_name": self.model.config["dashboard-configmap"],
            "profilename": self.model.config["profile"],
            "links": BASE_SIDEBAR,
            "settings": json.dumps({"DASHBOARD_FORCE_IFRAME": True}),
        }
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

    @property
    def lightkube_client(self):
        if not self._lightkube_client:
            self._lightkube_client = Client(
                namespace=self._namespace, field_manager=self._lightkube_field_manager
            )
            load_in_cluster_generic_resources(self._lightkube_client)
        return self._lightkube_client

    @lightkube_client.setter
    def lightkube_client(self, client):
        self._lightkube_client = client

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
    def _kubeflow_dashboard_operator_layer(self) -> Layer:
        layer_config = {
            "summary": "dex-auth-operator layer",
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

    def _create_resources(self, resource_type: List[str] = None) -> None:
        """Creates the resources for the charm."""
        if resource_type is None:
            resource_type = self._resource_files.keys()
        for resource_type in resource_type:
            resource_file = self._resource_files[resource_type]
            manifest = self.env.get_template(resource_file).render(self._context)
            for obj in codecs.load_all_yaml(manifest):
                try:
                    self.lightkube_client.apply(obj)
                except ApiError as e:
                    if e.status.code == 409:
                        self.logger.info("replacing resource: %s.", str(obj.to_dict()))
                        self.logger.debug(f"manifest is {manifest}")
                        try:
                            self.lightkube_client.patch(
                                type(obj),
                                obj.metadata.name,
                                obj,
                                patch_type=PatchType.MERGE,
                            )
                        except ApiError as e:
                            if e.status.code == 409:
                                self.logger.info(
                                    "Unable to replace resource: %s. Skipping.",
                                    str(obj.to_dict()),
                                )
                            else:
                                raise e
                    else:
                        self.logger.debug(
                            "failed to create resource: %s.", str(obj.to_dict())
                        )
                        raise e

    def main(self, event) -> None:
        """Main entry point for the Charm."""
        try:
            self._check_container_connection()
            self._check_model_name()
            self._check_leader()
            interfaces = self._get_interfaces()
            kf_profiles = self._check_kf_profiles(interfaces)
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        try:
            self.unit.status = MaintenanceStatus("Creating k8s resources")
            try:
                self._create_resources(["auths", "profiles"])
                current_configmap = self.lightkube_client.get(
                    ConfigMap, name=self._context["configmap_name"]
                )
            except ApiError as e:
                if e.status.code == 404:
                    self.logger.info(f"ConfigMap not found: {e}. Creating one")
            else:
                self.logger.info(f"ConfigMap found: {current_configmap}. Replacing it")
                self.lightkube_client.delete(
                    ConfigMap, name=self._context["configmap_name"]
                )
            self._create_resources(["config_maps"])
        except ApiError:
            self.logger.error(traceback.format_exc())
            self.unit.status = BlockedStatus("kubernetes resource creation failed")
        self.handle_ingress(interfaces)
        kf_profiles = list(kf_profiles.get_data().values())[0]
        self.profiles_service = kf_profiles["service-name"]
        try:
            self._update_layer()
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        self.model.unit.status = ActiveStatus()

    def _on_sidebar_relation_changed(self, event: RelationChangedEvent) -> None:
        if not self.unit.is_leader():
            return
        new_config_string = event.relation.data[event.app].get("config")
        if new_config_string is None:
            self.logger.info("No config link found in relation data")
            return
        try:
            self.unit.status = MaintenanceStatus("Adjusting sidebar configmap")
            current_configmap = self.lightkube_client.get(
                ConfigMap, name=self._context["configmap_name"]
            )
            old_sidebar_config = json.loads(current_configmap.data["links"])
        except Exception as e:
            self.logger.info(
                f"PROBLEM during configmap retrieval {e}. USING BASE CONFIG"
            )
            old_sidebar_config = json.loads(BASE_SIDEBAR)
        new_config_link = json.loads(new_config_string)
        if new_config_link not in old_sidebar_config["menuLinks"]:
            old_sidebar_config["menuLinks"].append(new_config_link)
            self._context["links"] = json.dumps(old_sidebar_config)
            try:
                self._create_resources(resource_type=["config_maps"])
            except ApiError:
                self.logger.error(traceback.format_exc())
                self.unit.status = BlockedStatus("kubernetes resource creation failed")
            self.model.unit.status = ActiveStatus()
        else:
            self.logger.info(f"{new_config_link} already exists in configmap")

    def _on_sidebar_relation_broken(self, event: RelationBrokenEvent) -> None:
        if not self.unit.is_leader():
            return
        self.logger.info(f"{event.app.name} relation broken")
        try:
            self.unit.status = MaintenanceStatus("Adjusting sidebar configmap")
            current_configmap = self.lightkube_client.get(
                ConfigMap, name=self._context["configmap_name"]
            )
            old_sidebar_config = json.loads(current_configmap.data["links"])
        except Exception as e:
            self.logger.info(
                f"PROBLEM during configmap retrieval {e}. USING BASE CONFIG"
            )
            old_sidebar_config = json.loads(BASE_SIDEBAR)

        new_menu_links = [
            conf
            for conf in old_sidebar_config["menuLinks"]
            if conf.get("app", None) != event.app.name
        ]
        if len(new_menu_links) != len(old_sidebar_config["menuLinks"]):
            old_sidebar_config["menuLinks"] = new_menu_links
            self._context["links"] = json.dumps(old_sidebar_config)
            try:
                self._create_resources(resource_type=["config_maps"])
            except ApiError:
                self.logger.error(traceback.format_exc())
                self.unit.status = BlockedStatus("kubernetes resource creation failed")
            self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(KubeflowDashboardOperator)
