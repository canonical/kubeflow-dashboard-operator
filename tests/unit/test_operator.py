# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch, Mock
from unittest import mock

import pytest
import yaml

from jinja2 import Environment, FileSystemLoader
from lightkube import codecs
from lightkube.core.exceptions import ApiError
from ops.model import BlockedStatus, WaitingStatus, ActiveStatus
from ops.testing import Harness
from pathlib import Path

from charm import KubeflowDashboardOperator


BASE_SIDEBAR = Path("src/config/sidebar_config.json").read_text()
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]


class _FakeResponse:
    """Used to fake an httpx response during testing only."""

    def __init__(self, code):
        self.code = code

    def json(self):
        return {"apiVersion": 1, "code": self.code, "message": "broken"}


class _FakeApiError(ApiError):
    """Used to simulate an ApiError during testing."""

    def __init__(self, code=400):
        super().__init__(response=_FakeResponse(code))


@pytest.fixture(scope="function")
def harness() -> Harness:
    harness = Harness(KubeflowDashboardOperator)
    # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
    harness.set_model_name("kubeflow")
    yield harness
    harness.cleanup()


@pytest.fixture(scope="function")
def harness_with_relation(harness: Harness) -> Harness:
    harness.set_leader(True)
    rel_id = harness.add_relation("kubeflow-profiles", "app")

    harness.add_relation_unit(rel_id, "app/0")
    data = {"service-name": "service-name", "service-port": "6666"}
    harness.update_relation_data(
        rel_id,
        "app",
        {"_supported_versions": "- v1", "data": yaml.dump(data)},
    )
    return harness


class TestCharm:
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_leader_failure(self, harness: Harness):
        harness.begin_with_initial_hooks()
        assert isinstance(harness.charm.model.unit.status, WaitingStatus)
        assert (
            "status_set",
            "waiting",
            "Waiting for leadership",
            {"is_app": False},
        ) in harness._get_backend_calls()

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_leader_success(self, harness: Harness):
        harness.set_leader(True)
        harness.begin_with_initial_hooks()
        assert isinstance(harness.charm.model.unit.status, WaitingStatus)
        assert (
            "status_set",
            "waiting",
            "Waiting for leadership",
            {"is_app": False},
        ) not in harness._get_backend_calls()

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

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_model_name_success(self, harness: Harness):
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status != BlockedStatus(
            "kubeflow-dashboard must be deployed to model named `kubeflow`:"
            " https://git.io/J6d35"
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_kf_profiles_failure(self, harness: Harness):
        harness.set_leader(True)
        harness.begin_with_initial_hooks()

        assert harness.charm.model.unit.status == WaitingStatus(
            "Waiting for kubeflow-profiles relation data"
        )

    @patch("charm.KubeflowDashboardOperator._create_resources")
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_kf_profiles_success(self, harness_with_relation: Harness):
        harness_with_relation.begin_with_initial_hooks()

        assert harness_with_relation.charm.model.unit.status != WaitingStatus(
            "Waiting for kubeflow-profiles relation data"
        )

    @patch("charm.KubeflowDashboardOperator._update_layer")
    def test_on_kubeflow_dashboard_pebble_ready(
        self, update, harness_with_relation: Harness
    ):
        harness_with_relation.container_pebble_ready(CHARM_NAME)
        assert (
            harness_with_relation.get_container_pebble_plan(CHARM_NAME)._services
            is not None
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_create_resources_success(self, harness_with_relation: Harness):
        context = {
            "app_name": "kubeflow-dashboard",
            "namespace": "kubeflow",
            "configmap_name": "test-configmap",
            "profilename": "test-profile",
            "links": "",
            "settings": "",
        }
        resource_files = [
            "profile_crds.yaml.j2",
            "auth_manifests.yaml.j2",
            "configmaps.yaml.j2",
        ]
        env = Environment(loader=FileSystemLoader("src/templates"))
        expected_objects = []
        for file in resource_files:
            manifest = env.get_template(file).render(context)
            for obj in codecs.load_all_yaml(manifest):
                expected_objects.append(mock.call.create(obj))

        mocked_lightkube_client = Mock()
        harness_with_relation.begin()
        harness_with_relation.charm.lightkube_client = mocked_lightkube_client
        harness_with_relation.charm._context = context
        harness_with_relation.charm._create_resources()
        mocked_lightkube_client.assert_has_calls(expected_objects)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator._create_resources")
    @patch("charm.KubeflowDashboardOperator._update_layer")
    def test_main(self, update_layer, create_resources, harness_with_relation: Harness):
        expected_links = BASE_SIDEBAR
        harness_with_relation.begin_with_initial_hooks()
        create_resources.assert_called()
        update_layer.assert_called()
        assert isinstance(harness_with_relation.charm.model.unit.status, ActiveStatus)
        assert harness_with_relation.charm._context["links"] == expected_links
