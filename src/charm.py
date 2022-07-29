#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import traceback

from pathlib import Path

from charmed_kubeflow_chisme.lightkube.batch import apply_many
from jinja2 import Environment, FileSystemLoader
from lightkube import Client, ApiError, codecs
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import ChangeError, Layer
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)

BASE_SIDEBAR = json.loads(Path("src/config.json").read_text())


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
        super.__init__(self, *args)

        self.logger = logging.getLogger(__name__)
        self.lightkube_field_manager = "lightkube"
        self.lightkube_client = Client(
            namespace=self._namespace, field_manager=self.lightkube_field_manager
        )
        self.env = Environment(loader=FileSystemLoader("src"))
        self._name = self.model.app.name
        self._namespace = self.model.name
        self._entrypoint = "npm start"
        self._container_name = "kubeflow-dashboard"
        self._container = self.unit.get_container(self._name)
        self._resource_files = {
            "crds": "crds_manifests.yaml",
            # "service_accounts":  "service_account.yaml",
            "config_maps": "configmaps_manifests.yaml",
        }
        self._context = {
            "namespace": self._namespace,
            "configmap_name": self.model.config["dashboard-configmap"],
            "profilename": self.model.config["profile"],
            "links": Path("src/config.json").read_text(),
            "settings": json.dumps(
                {
                    "DASHBOARD_FORCE_IFRAME": True,
                }
            ),
        }
        for event in [
            self.on.install,
            self.on.config_changed,
            self.on.ingress_relation_changed,
            self.on.knative_operator_pebble_ready,
        ]:
            self.framework.observe(event, self.main)

    def get_kubeflow_dashboard_operator_layer(self, profiles_service: str) -> Layer:
        """Returns a pre-configured Pebble layer."""
        layer_config = {
            "summary": "dex-auth-operator layer",
            "description": "pebble config layer for dex-auth-operator",
            "services": {
                self._container_name: {
                    "override": "replace",
                    "summary": "entrypoint of the dex-auth-operator image",
                    "command": f"{self._entrypoint}",
                    "startup": "enabled",
                    "environment": {
                        "USERID_HEADER": "kubeflow-userid",
                        "USERID_PREFIX": "",
                        "PROFILES_KFAM_SERVICE_HOST": f"{profiles_service}.{self.model.name}",
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
        if not self._container.can_connect():
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
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _update_layer(self, profiles_service: str) -> None:
        """Updates the Pebble configuration layer if changed."""
        try:
            self._check_container_connection()
        except CheckFailed as e:
            self.logger.error(traceback.format_exc())
            self.model.unit.status = e.status
            return

        current_layer = self._container.get_plan()
        new_layer = self.get_kubeflow_dashboard_operator_layer(profiles_service)
        if current_layer.services != new_layer.services:
            self.unit.status = MaintenanceStatus("Applying new pebble layer")
            self._container.add_layer(self._container_name, new_layer, combine=True)
            try:
                self.logger.info(
                    "Pebble plan updated with new configuration, replanning"
                )
                self._container.replan()
            except ChangeError as e:
                self.logger.error(traceback.format_exc())
                self.unit.status = BlockedStatus("Failed to replan")
                raise e

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

    def _create_resources(self, resource_type=None) -> None:
        """Creates the resources for the charm."""
        if resource_type is None:
            resource_type = self._resource_files.keys()
        for resource_type in resource_type:
            resource_file = self._resource_files[resource_type]
            manifest = self.env.get_template(resource_file).render(self._context)
            objs = codecs.load_all_yaml(manifest)
            try:
                apply_many(self.lightkube_client, objs, self.lightkube_field_manager)
            except ApiError as e:
                self.logger.error(traceback.format_exc())
                self.unit.status = BlockedStatus(
                    f"Applying resources failed with code {str(e.status.code)}."
                )
                if e.status.code == 403:
                    self.logger.error(
                        "Received Forbidden (403) error when creating auth resources."
                        "This may be due to the charm lacking permissions to create"
                        "cluster-scoped resources."
                        "Charm must be deployed with --trust"
                    )
                raise e
        self.unit.status = ActiveStatus()

    def main(self, event):
        """Main entry point for the Charm."""
        try:
            self._check_model_name()
            self._check_leader()
            interfaces = self._get_interfaces()
            kf_profiles = self._check_kf_profiles(interfaces)
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        self.handle_ingress(interfaces)
        kf_profiles = list(kf_profiles.get_data().values())[0]
        profiles_service = kf_profiles["service-name"]
        self._update_layer(profiles_service)
        self._create_resources()
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(KubeflowDashboardOperator)
