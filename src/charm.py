#!/usr/bin/env python3

import json
import logging
from pathlib import Path

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    WaitingStatus,
    StatusBase,
)
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger(__name__)
        self.image = OCIImageResource(self, "oci-image")

        # This comes out cleaner if we update the serialized_data_interface.get_interfaces() to
        # return interfaces regardless of whether any interface raised an error.  Maybe it returns:
        # {'working_interface_A': SDI_instance, 'broken_interface_B': NoCompatibleVersions, ...}
        # This way we can interrogate interfaces independently
        # (This might be a breaking change, so maybe we'd want to add a second get_interfaces
        # method, bump the package to 0.4, or add an arg to the existing one)
        self.interfaces = get_interfaces(self)

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["kubeflow-profiles"].relation_changed,
        ]:
            self.framework.observe(event, self.install)

        # Should this be both joined and changed or just one of them?
        self.framework.observe(self.on["ingress"].relation_joined, self.configure_mesh)
        self.framework.observe(self.on["ingress"].relation_changed, self.configure_mesh)

        self.framework.observe(self.on.update_status, self.update_status)

    def install(self, event):
        if not isinstance(
                dependency_status := self._check_dependencies(), ActiveStatus
        ):
            self.model.unit.status = dependency_status
            return

        if not isinstance(is_leader := self._check_is_leader(), ActiveStatus):
            self.model.unit.status = is_leader
            return

        if not isinstance(
                required_relation_status := self._check_required_relations(), ActiveStatus
        ):
            self.model.unit.status = required_relation_status
            return

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self._set_pod_spec()

        self.update_status(event)

    def configure_mesh(self, event):
        if not isinstance(
            interface_status := validate_interface(interface), ActiveStatus
        ):
            self.model.unit.status = interface_status
            return

        if self.interfaces["ingress"]:
            self.interfaces["ingress"].send_data(
                {
                    "prefix": "/",
                    "rewrite": "/",
                    "service": self.model.app.name,
                    "port": self.model.config["port"],
                }
            )

    def update_status(self, event):
        # This method should always result in a status being set to something as it follows things
        # like install's MaintenanceStatus
        self.model.unit.status = self._get_application_status()
        # This could also try to fix a broken application if status != Active

    def _check_dependencies(self) -> StatusBase:
        # TODO: Check if any dependencies required by this charm are available and Block otherwise
        #       This charm would check for Istio CRDs, maybe other stuff

        if self.model.name != "kubeflow":
            # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
            self.model.unit.status = BlockedStatus(
                "kubeflow-dashboard must be deployed to model named `kubeflow`:"
                " https://git.io/J6d35"
            )
            return

        # This might make sense to return a list of statuses in case we're missing multiple things
        return ActiveStatus()

    def _get_application_status(self) -> StatusBase:
        # TODO: Do whatever checks are needed to confirm we are actually working correctly
        #       Maybe check for key deployments, etc?

        # Until we have a real check - cheat :)  Note that this needs to be fleshed out if actually
        # used by a relation hook
        return ActiveStatus()

    def _check_required_relations(self) -> StatusBase:
        # TODO: I dont think this handles if the relation is just not established?
        if not isinstance(
            interface_status := validate_interface(
                self.interfaces["kubeflow-profiles"]
            ),
            ActiveStatus,
        ):
            self.model.unit.status = interface_status
            return

        if not (
            (kf_profiles := self.interfaces["kubeflow-profiles"])
            and kf_profiles.get_data()
        ):
            return WaitingStatus("Waiting for kubeflow-profiles relation data")
        return ActiveStatus()

    # TODO: I think there's a better way to do the return type hint here
    def _check_is_leader(self) -> StatusBase:
        if not self.unit.is_leader():
            return WaitingStatus("Waiting for leadership")
        else:
            # Or we could return None. It felt odd that this function would return a status or None
            return ActiveStatus()

    def _set_pod_spec(self):
        # Left this on its own as I think it is just valid for install?
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

        model = self.model.name

        kf_profiles = list(kf_profiles.get_data().values())[0]
        profiles_service = kf_profiles["service-name"]

        config = self.model.config

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
                        "links": Path("src/config.json").read_text(),
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


def validate_interface(interface):
    if is_instance(interface, NoVersionsListed):
        return WaitingStatus(str(interface))
    elif is_instance(interface, NoCompatibleVersions):
        return BlockedStatus(str(interface))
    elif is_instance(interface, Exception):
        return ErrorStatus(f"Unexpected error: {str(interface)}")

    return ActiveStatus()


if __name__ == "__main__":
    main(Operator)
