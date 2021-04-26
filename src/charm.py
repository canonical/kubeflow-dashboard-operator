#!/usr/bin/env python3

import logging
import yaml
from pathlib import Path

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus, BlockedStatus
from ops.framework import StoredState

from oci_image import OCIImageResource, OCIImageResourceError
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)


class Operator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            self.model.unit.status = WaitingStatus("Waiting for leadership")
            return
        self.log = logging.getLogger(__name__)
        self.image = OCIImageResource(self, "oci-image")

        try:
            self.interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            self.model.unit.status = WaitingStatus(str(err))
            return
        except NoCompatibleVersions as err:
            self.model.unit.status = BlockedStatus(str(err))
            return
        else:
            self.model.unit.status = ActiveStatus()

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["kubeflow-profiles"].relation_changed,
        ]:
            self.framework.observe(event, self.main)

        self.framework.observe(self.on["ingress"].relation_changed, self.configure_mesh)

    def configure_mesh(self, event):
        if self.interfaces["ingress"]:
            self.interfaces["ingress"].send_data(
                {
                    "prefix": "/",
                    "rewrite": "/",
                    "service": self.model.app.name,
                    "port": self.model.config["port"],
                }
            )

    def main(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

        model = self.model.name

        if not (
            (kf_profiles := self.interfaces["kubeflow-profiles"])
            and kf_profiles.get_data()
        ):
            self.model.unit.status = WaitingStatus(
                "Waiting for kubeflow-profiles relation data"
            )
            return

        kf_profiles = list(kf_profiles.get_data().values())[0]
        profiles_service = kf_profiles["service-name"]

        port = self.model.config["port"]
        profile = self.model.config["profile"]

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
                            "REGISTRATION_FLOW": self.model.config["registration-flow"],
                            "DASHBOARD_LINKS_CONFIGMAP": self.model.config[
                                "dashboard-configmap"
                            ],
                        },
                        "ports": [{"name": "ui", "containerPort": port}],
                        "kubernetes": {
                            "livenessProbe": {
                                "httpGet": {"path": "/healthz", "port": port},
                                "initialDelaySeconds": 30,
                                "periodSeconds": 30,
                            }
                        },
                    }
                ],
            },
            {
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(
                            Path("files/crds.yaml").read_text()
                        )
                    ],
                    "customResources": {
                        "profiles.kubeflow.org": [
                            {
                                "apiVersion": "kubeflow.org/v1beta1",
                                "kind": "Profile",
                                "metadata": {"name": profile},
                                "spec": {"owner": {"kind": "User", "name": profile}},
                            }
                        ]
                    },
                }
            },
        )

        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
