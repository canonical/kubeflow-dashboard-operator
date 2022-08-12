# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import patch, Mock
from unittest import mock

import pytest
import yaml

from jinja2 import Environment, FileSystemLoader
from lightkube import codecs
from lightkube.generic_resource import create_global_resource
from lightkube.core.exceptions import ApiError
from lightkube.types import PatchType
from ops.model import BlockedStatus, WaitingStatus, ActiveStatus
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
RESOURCE_FILES = [
    "profile_crds.yaml.j2",
    "auth_manifests.yaml.j2",
    "configmaps.yaml.j2",
]


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
    def test_check_kf_profiles_success(self, harness_with_profiles: Harness):
        harness_with_profiles.begin_with_initial_hooks()

        assert harness_with_profiles.charm.model.unit.status != WaitingStatus(
            "Waiting for kubeflow-profiles relation data"
        )

    @patch("charm.KubeflowDashboardOperator._update_layer")
    def test_on_kubeflow_dashboard_pebble_ready(
        self, update, harness_with_profiles: Harness
    ):
        harness_with_profiles.container_pebble_ready(CHARM_NAME)
        assert (
            harness_with_profiles.get_container_pebble_plan(CHARM_NAME)._services
            is not None
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_create_resources_success(self, harness_with_profiles: Harness):
        resource_files = RESOURCE_FILES
        create_global_resource(
            group="kubeflow.org", version="v1", kind="Profile", plural="profiles"
        )
        # I am doing this so I can create list of mocked resources to compare later.
        env = Environment(loader=FileSystemLoader("src/templates"))
        expected_objects = []
        for file in resource_files:
            manifest = env.get_template(file).render(DEFAULT_CONTEXT)
            for obj in codecs.load_all_yaml(manifest):
                expected_objects.append(mock.call.apply(obj))

        mocked_lightkube_client = Mock()
        harness_with_profiles.begin()
        harness_with_profiles.charm.lightkube_client = mocked_lightkube_client
        harness_with_profiles.charm._context = DEFAULT_CONTEXT
        harness_with_profiles.charm._create_resources()
        mocked_lightkube_client.assert_has_calls(expected_objects)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_create_resources_patch(self, harness_with_profiles: Harness):
        resource_files = RESOURCE_FILES
        create_global_resource(
            group="kubeflow.org", version="v1", kind="Profile", plural="profiles"
        )
        # I am doing this so I can create list of mocked resources to compare later.
        env = Environment(loader=FileSystemLoader("src/templates"))
        expected_objects = []
        for file in resource_files:
            manifest = env.get_template(file).render(DEFAULT_CONTEXT)
            for obj in codecs.load_all_yaml(manifest):
                expected_objects.append(mock.call.apply(obj))
                expected_objects.append(
                    mock.call.patch(
                        type(obj), obj.metadata.name, obj, patch_type=PatchType.MERGE
                    )
                )
        mocked_lightkube_client = Mock()
        harness_with_profiles.begin()
        harness_with_profiles.charm.lightkube_client = mocked_lightkube_client
        mocked_lightkube_client.apply.side_effect = _FakeApiError(code=409)
        harness_with_profiles.charm._context = DEFAULT_CONTEXT
        harness_with_profiles.charm._create_resources()
        mocked_lightkube_client.assert_has_calls(expected_objects)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_create_resources_failure(self, harness_with_profiles: Harness):
        mocked_lightkube_client = Mock()
        harness_with_profiles.begin()
        harness_with_profiles.charm.lightkube_client = mocked_lightkube_client
        mocked_lightkube_client.apply.side_effect = _FakeApiError(code=409)
        mocked_lightkube_client.patch.side_effect = _FakeApiError(code=404)
        with pytest.raises(ApiError):
            harness_with_profiles.charm._create_resources()

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator._create_resources")
    @patch("charm.KubeflowDashboardOperator._update_layer")
    def test_main(self, update_layer, create_resources, harness_with_profiles: Harness):
        mocked_lightkube_client = Mock()
        expected_links = BASE_SIDEBAR
        harness_with_profiles.begin()
        harness_with_profiles.charm.lightkube_client = mocked_lightkube_client
        harness_with_profiles.charm.on.install.emit()
        create_resources.assert_called()
        update_layer.assert_called()
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)
        assert harness_with_profiles.charm._context["links"] == expected_links

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.lightkube_client")
    def test_on_sidebar_relation_changed(
        self, lightkube_client, harness_with_profiles: Harness
    ):
        # Expected tensorboard link data

        expected_links = json.loads(BASE_SIDEBAR)
        expected_links["menuLinks"].append(RELATION_DATA)
        context = DEFAULT_CONTEXT
        context = {
            **DEFAULT_CONTEXT,
            **{"links": json.dumps(expected_links)},
        }
        cm_file = "configmaps.yaml.j2"
        env = Environment(loader=FileSystemLoader("src/templates"))
        manifest = env.get_template(cm_file).render(context)
        expected_objects = []
        for obj in codecs.load_all_yaml(manifest):
            expected_objects.append(mock.call.apply(obj))
        relation_id = harness_with_profiles.add_relation(
            "sidebar", "tensorboards-web-app"
        )
        harness_with_profiles.add_relation_unit(relation_id, "tensorboards-web-app/0")
        harness_with_profiles.update_relation_data(
            relation_id,
            "tensorboards-web-app",
            {"_supported_versions": "- v1", "config": json.dumps(RELATION_DATA)},
        )
        harness_with_profiles.begin_with_initial_hooks()
        lightkube_client.assert_has_calls(expected_objects)
        assert harness_with_profiles.charm._context["links"] == json.dumps(
            expected_links
        )
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.lightkube_client")
    def test_on_sidebar_relation_removed(
        self, lightkube_client, harness_with_profiles: Harness
    ):
        relation_id = harness_with_profiles.add_relation(
            "sidebar", "tensorboards-web-app"
        )
        harness_with_profiles.add_relation_unit(relation_id, "tensorboards-web-app/0")
        harness_with_profiles.update_relation_data(
            relation_id,
            "tensorboards-web-app",
            {"_supported_versions": "- v1", "config": json.dumps(RELATION_DATA)},
        )
        harness_with_profiles.remove_relation(relation_id)
        harness_with_profiles.begin_with_initial_hooks()
        assert harness_with_profiles.charm._context["links"] == BASE_SIDEBAR
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)
