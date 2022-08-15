# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch, MagicMock
from unittest import mock

import pytest
import yaml

from ops.model import BlockedStatus, WaitingStatus, ActiveStatus
from ops.pebble import ChangeError
from ops.testing import Harness
from pathlib import Path

from charm import KubeflowDashboardOperator


BASE_SIDEBAR = Path("src/config/sidebar_config.json").read_text()
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
RELATION_DATA = {
    "app": "tensorboards-web-app",
    "type": "item",
    "link": "/tensorboards/",
    "text": "Tensorboards",
    "icon": "assessment",
}
DEFAULT_CONTEXT = {
    "app_name": "kubeflow-dashboard",
    "namespace": "kubeflow",
    "configmap_name": "centraldashboard-config",
    "profilename": "test-profile",
    "links": BASE_SIDEBAR,
    "settings": "",
}
DEFAULT_RESOURCE_FILES = [
    "profile_crds.yaml.j2",
    "auth_manifests.yaml.j2",
    "configmaps.yaml.j2",
]


class _FakeChangeError(ChangeError):
    """Used to simulate a ChangeError during testing."""

    def __init__(self, err, change):
        super().__init__(err, change)


@pytest.fixture(scope="function")
def harness() -> Harness:
    harness = Harness(KubeflowDashboardOperator)
    # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
    harness.set_model_name("kubeflow")
    yield harness
    harness.cleanup()


@pytest.fixture(scope="function")
def harness_with_profiles(harness: Harness) -> Harness:
    harness.set_leader(True)
    rel_id = harness.add_relation("kubeflow-profiles", "app")

    harness.add_relation_unit(rel_id, "app/0")
    data = {"service-name": "service-name", "service-port": "6666"}
    harness.update_relation_data(
        rel_id,
        "app",
        {"_supported_versions": "- v1", "data": yaml.dump(data)},
    )
    yield harness
    harness.cleanup()


class TestCharm:
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    def test_check_leader_failure(self, harness: Harness):
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status == WaitingStatus(
            "Waiting for leadership"
        )
        assert (
            "status_set",
            "waiting",
            "Waiting for leadership",
            {"is_app": False},
        ) in harness._get_backend_calls()
        harness.set_leader(True)
        assert harness.charm.model.unit.status != WaitingStatus(
            "Waiting for leadership"
        )

    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_leader_success(self, harness: Harness):
        harness.set_leader(True)
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status != WaitingStatus(
            "Waiting for leadership"
        )
        assert (
            "status_set",
            "waiting",
            "Waiting for leadership",
            {"is_app": False},
        ) not in harness._get_backend_calls()

    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_model_name_failure(self):
        # Tests that unit will BlockStatus if deployed outside a model named kubeflow
        # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
        harness = Harness(KubeflowDashboardOperator)
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status == BlockedStatus(
            "kubeflow-dashboard must be deployed to model named `kubeflow`:"
            " https://git.io/J6d35"
        )

    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_model_name_success(self, harness: Harness):
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status != BlockedStatus(
            "kubeflow-dashboard must be deployed to model named `kubeflow`:"
            " https://git.io/J6d35"
        )

    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_kf_profiles_failure(self, harness: Harness):
        harness.set_leader(True)
        harness.begin_with_initial_hooks()

        assert harness.charm.model.unit.status == WaitingStatus(
            "Waiting for kubeflow-profiles relation data"
        )

    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_kf_profiles_success(self, harness_with_profiles: Harness):
        harness_with_profiles.begin_with_initial_hooks()

        assert harness_with_profiles.charm.model.unit.status != WaitingStatus(
            "Waiting for kubeflow-profiles relation data"
        )

    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_update_layer_success(self, harness_with_profiles: Harness):
        harness_with_profiles.container_pebble_ready(CHARM_NAME)
        harness_with_profiles.begin_with_initial_hooks()
        assert (
            harness_with_profiles.get_container_pebble_plan(CHARM_NAME)._services
            is not None
        )
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)

    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.container")
    def test_update_layer_failure(
        self,
        container: MagicMock,
        harness_with_profiles: Harness,
    ):
        container.replan.side_effect = _FakeChangeError(
            "Fake problem during layer update", None
        )
        harness_with_profiles.container_pebble_ready(CHARM_NAME)
        harness_with_profiles.begin_with_initial_hooks()
        assert harness_with_profiles.charm.model.unit.status == BlockedStatus(
            "Failed to replan"
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    def test_create_resources_success(
        self,
        k8s_resource_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        harness_with_profiles.begin()
        harness_with_profiles.charm.on.install.emit()
        k8s_resource_handler.apply.assert_called_once()
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    @patch("charm.KubeflowDashboardOperator._update_layer")
    def test_main(
        self,
        update_layer: MagicMock,
        k8s_resource_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        expected_links = BASE_SIDEBAR
        harness_with_profiles.begin()
        harness_with_profiles.charm.on.install.emit()
        k8s_resource_handler.apply.assert_called()
        update_layer.assert_called()
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)
        assert harness_with_profiles.charm._context["links"] == expected_links

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    @patch("charm.delete_many")
    def test_on_remove_success(
        self,
        delete_many: MagicMock,
        k8s_resource_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        harness_with_profiles.begin()
        harness_with_profiles.charm.on.remove.emit()
        k8s_resource_handler.assert_has_calls([mock.call.render_manifests()])
        delete_many.assert_called()
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)
