#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from random import choices
from string import ascii_uppercase, digits
from pathlib import Path
from hashlib import sha256

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase, RelationChangedEvent, RelationBrokenEvent
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)

SIDEBAR_EXTRA_OPTIONS = json.loads(Path("src/extra_config.json").read_text())


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg: str, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


class Operator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger(__name__)
        self.image = OCIImageResource(self, "oci-image")
        self._stored.set_default(hash_salt=_gen_pass())
        self._stored.set_default(side_bar_tabs=Path("src/config.json").read_text())

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["kubeflow-profiles"].relation_changed,
            self.on["ingress"].relation_changed,
        ]:
            self.framework.observe(event, self.main)
        self.framework.observe(
            self.on.sidepanel_relation_changed, self._on_sidepanel_relation_changed
        )
        self.framework.observe(
            self.on.sidepanel_relation_broken,
            self._on_sidepanel_relation_broken,
        )

    def main(self, event):
        try:
            self._check_model_name()

            self._check_leader()

            interfaces = self._get_interfaces()

            image_details = self._check_image_details()

            kf_profiles = self._check_kf_profiles(interfaces)
        except CheckFailed as check_failed:
            self.model.unit.status = check_failed.status
            return

        self._configure_mesh(interfaces)

        kf_profiles = list(kf_profiles.get_data().values())[0]
        profiles_service = kf_profiles["service-name"]

        model = self.model.name
        config = self.model.config
        configmap_hash = self._generate_config_hash()

        self.model.unit.status = MaintenanceStatus("Setting pod spec")

        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "global": True,
                            "rules": [
                                {
                                    "apiGroups": [""],
                                    "resources": ["events", "namespaces", "nodes"],
                                    "verbs": ["get", "list", "watch"],
                                },
                                {
                                    "apiGroups": ["", "app.k8s.io"],
                                    "resources": [
                                        "applications",
                                        "pods",
                                        "pods/exec",
                                        "pods/log",
                                    ],
                                    "verbs": ["get", "list", "watch"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["secrets", "configmaps"],
                                    "verbs": ["get"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "kubeflow-dashboard",
                        "imageDetails": image_details,
                        "envConfig": {
                            "USERID_HEADER": "kubeflow-userid",
                            "USERID_PREFIX": "",
                            "PROFILES_KFAM_SERVICE_HOST": f"{profiles_service}.{model}",
                            "REGISTRATION_FLOW": config["registration-flow"],
                            "DASHBOARD_LINKS_CONFIGMAP": config["dashboard-configmap"],
                            "CONFIGMAP_HASH": configmap_hash,
                        },
                        "ports": [{"name": "ui", "containerPort": config["port"]}],
                        "kubernetes": {
                            "livenessProbe": {
                                "httpGet": {"path": "/healthz", "port": config["port"]},
                                "initialDelaySeconds": 30,
                                "periodSeconds": 30,
                            }
                        },
                    }
                ],
            },
            {
                "configMaps": {
                    config["dashboard-configmap"]: {
                        "settings": json.dumps(
                            {
                                "DASHBOARD_FORCE_IFRAME": True,
                            }
                        ),
                        "links": self._stored.side_bar_tabs,
                    },
                },
                "kubernetesResources": {
                    "customResources": {
                        "profiles.kubeflow.org": [
                            {
                                "apiVersion": "kubeflow.org/v1beta1",
                                "kind": "Profile",
                                "metadata": {"name": config["profile"]},
                                "spec": {
                                    "owner": {"kind": "User", "name": config["profile"]}
                                },
                            }
                        ]
                    },
                },
            },
        )

        self.model.unit.status = ActiveStatus()

    def _on_sidepanel_relation_changed(self, event: RelationChangedEvent):
        try:
            self._check_leader()
        except CheckFailed as check_failed:
            self.model.unit.status = check_failed.status
            return
        if event.app.name in SIDEBAR_EXTRA_OPTIONS:
            self.log.info(f"ADDING {event.app.name} to side panel")
            side_bar_tabs_dict = json.loads(self._stored.side_bar_tabs)
            if (
                SIDEBAR_EXTRA_OPTIONS[event.app.name]["menuLink"]
                not in side_bar_tabs_dict["menuLinks"]
            ):
                side_bar_tabs_dict["menuLinks"].append(
                    SIDEBAR_EXTRA_OPTIONS[event.app.name]["menuLink"]
                )
                self.log.info(f"NEW SIDE BAR {side_bar_tabs_dict}")
                self._stored.side_bar_tabs = json.dumps(side_bar_tabs_dict)
                self.main(event)

    def _on_sidepanel_relation_broken(self, event: RelationBrokenEvent):
        try:
            self._check_leader()
        except CheckFailed as check_failed:
            self.model.unit.status = check_failed.status
            return
        if event.app.name in SIDEBAR_EXTRA_OPTIONS:
            self.log.info(f"REMOVING {event.app.name} to side panel")
            side_bar_tabs_dict = json.loads(self._stored.side_bar_tabs)
            side_bar_tabs_dict["menuLinks"] = [
                link
                for link in side_bar_tabs_dict["menuLinks"]
                if link != SIDEBAR_EXTRA_OPTIONS[event.app.name]["menuLink"]
            ]
            self.log.info(f"NEW SIDE BAR {side_bar_tabs_dict}")
            self._stored.side_bar_tabs = json.dumps(side_bar_tabs_dict)
            self.main(event)

    def _configure_mesh(self, interfaces):
        if interfaces["ingress"]:
            interfaces["ingress"].send_data(
                {
                    "prefix": "/",
                    "rewrite": "/",
                    "service": self.model.app.name,
                    "port": self.model.config["port"],
                }
            )

    def _generate_config_hash(self):
        """Returns a hash of the current config state"""
        # Add a randomly generated salt to the config to make it hard to reverse engineer the
        # secret-key from the password.
        salt = self._stored.hash_salt
        all_config = tuple(
            str(self.model.config[name]) for name in sorted(self.model.config.keys())
        ) + (salt,)
        config_hash = sha256(".".join(all_config).encode("utf-8"))
        return config_hash.hexdigest()

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

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def _check_image_details(self):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            raise CheckFailed(f"{e.status_message}: oci-image", e.status_type)
        return image_details

    def _check_kf_profiles(self, interfaces):
        if not (
            (kf_profiles := interfaces["kubeflow-profiles"]) and kf_profiles.get_data()
        ):
            raise CheckFailed(
                "Waiting for kubeflow-profiles relation data", WaitingStatus
            )

        return kf_profiles


def _gen_pass() -> str:
    return "".join(choices(ascii_uppercase + digits, k=30))


if __name__ == "__main__":
    main(Operator)
