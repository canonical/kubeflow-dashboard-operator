# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from dataclasses import asdict
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DASHBOARD_LINKS_FIELD,
    DashboardLink,
)
from lightkube import ApiError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ChangeError
from ops.testing import Harness

from charm import (
    ADDITIONAL_MENU_LINKS_CONFIG,
    DASHBOARD_LINKS_RELATION_NAME,
    MENU_LINKS_ORDER_CONFIG,
    KubeflowDashboardOperator,
)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
RELATION_DATA = [
    {
        "app": "tensorboards-web-app",
        "type": "item",
        "link": "/tensorboards/",
        "text": "Tensorboards",
        "icon": "assessment",
    }
]


DEFAULT_RESOURCE_FILES = [
    "profile_crds.yaml.j2",
    "auth_manifests.yaml.j2",
    "configmaps.yaml.j2",
]


class _FakeResponse:
    """Used to fake an httpx response during testing only."""

    def __init__(self, code):
        self.code = code
        self.name = ""

    def json(self):
        reason = ""
        if self.code == 409:
            reason = "AlreadyExists"
        return {
            "apiVersion": 1,
            "code": self.code,
            "message": "broken",
            "reason": reason,
        }


class _FakeApiError(ApiError):
    """Used to simulate an ApiError during testing."""

    def __init__(self, code=400):
        super().__init__(response=_FakeResponse(code))


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
    def test_check_leader_failure(self, harness: Harness):
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")
        harness.set_leader(True)
        assert harness.charm.model.unit.status != WaitingStatus("Waiting for leadership")

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_leader_success(self, harness: Harness):
        harness.set_leader(True)
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status != WaitingStatus("Waiting for leadership")

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

        assert harness.charm.model.unit.status == BlockedStatus(
            "Add required relation to kubeflow-profiles"
        )

    @patch("charm.KubernetesResourceHandler")
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_check_kf_profiles_success(self, harness_with_profiles: Harness):
        harness_with_profiles.begin_with_initial_hooks()

        assert harness_with_profiles.charm.model.unit.status != WaitingStatus(
            "Waiting for kubeflow-profiles relation data"
        )

    @patch("charm.KubeflowDashboardOperator.configmap_handler", MagicMock())
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler", MagicMock())
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.container")
    def test_update_layer_failure(
        self,
        container: MagicMock,
        harness_with_profiles: Harness,
    ):
        container.replan.side_effect = _FakeChangeError("Fake problem during layer update", None)
        harness_with_profiles.container_pebble_ready(CHARM_NAME)
        with pytest.raises(GenericCharmRuntimeError):
            harness_with_profiles.begin_with_initial_hooks()

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.configmap_handler")
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    def test_deploy_k8s_resources_success(
        self,
        k8s_resource_handler: MagicMock,
        configmap_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        harness_with_profiles.begin()
        harness_with_profiles.charm._deploy_k8s_resources()
        k8s_resource_handler.apply.assert_called()
        configmap_handler.apply.assert_called()
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.configmap_handler")
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    def test_create_resources_success(
        self,
        k8s_resource_handler: MagicMock,
        configmap_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        harness_with_profiles.begin()
        harness_with_profiles.charm.on.install.emit()
        k8s_resource_handler.apply.assert_called_once()
        configmap_handler.apply.assert_called_once()
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.configmap_handler")
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    @patch("charm.KubeflowDashboardOperator._update_layer")
    def test_main(
        self,
        update_layer: MagicMock,
        k8s_resource_handler: MagicMock,
        configmap_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        expected_links = []
        harness_with_profiles.begin()
        harness_with_profiles.charm.on.install.emit()
        k8s_resource_handler.apply.assert_called()
        configmap_handler.apply.assert_called_once()
        update_layer.assert_called()
        assert isinstance(harness_with_profiles.charm.model.unit.status, ActiveStatus)
        actual_links = json.loads(harness_with_profiles.charm._context["menuLinks"])
        assert actual_links == expected_links

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    @patch("charm.KubeflowDashboardOperator.configmap_handler")
    @patch("charm.delete_many")
    def test_on_remove_success(
        self,
        delete_many: MagicMock,
        configmap_handler: MagicMock,
        k8s_resource_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        harness_with_profiles.begin()
        harness_with_profiles.charm.on.remove.emit()
        k8s_resource_handler.assert_has_calls([mock.call.render_manifests()])
        configmap_handler.assert_has_calls([mock.call.render_manifests()])
        delete_many.assert_called()

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    @patch("charm.KubeflowDashboardOperator.configmap_handler")
    @patch("charm.delete_many")
    def test_on_remove_failure(
        self,
        delete_many: MagicMock,
        _: MagicMock,
        __: MagicMock,
        harness_with_profiles: Harness,
    ):
        delete_many.side_effect = _FakeApiError()
        harness_with_profiles.begin()
        with pytest.raises(ApiError):
            harness_with_profiles.charm.on.remove.emit()


class TestSidebarLinks:
    """Tests for the sidebar relation."""

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_context_with_sidebar_relations_no_links(
        self,
        harness_with_profiles: Harness,
    ):
        """Tests that context renders properly when no sidebar relations are present."""
        expected_links = []
        harness_with_profiles.begin()
        actual_links = json.loads(harness_with_profiles.charm._context["menuLinks"])
        assert actual_links == expected_links

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KubeflowDashboardOperator.k8s_resource_handler")
    @patch("charm.KubeflowDashboardOperator.configmap_handler")
    @patch("charm.delete_many")
    def test_context_with_adding_and_removing_sidebar_relations(
        self,
        update_layer: MagicMock,
        k8s_resource_handler: MagicMock,
        configmap_handler: MagicMock,
        harness_with_profiles: Harness,
    ):
        """e2e test of the sidebar relation, checking k8s context for added/removed relations."""
        harness_with_profiles.begin()

        relations = [
            add_sidebar_relation(harness_with_profiles, other_app_name=f"other{i}")
            for i in range(3)
        ]

        # Related apps, but no links
        expected_items = []
        actual_items = json.loads(harness_with_profiles.charm._context["menuLinks"])
        assert actual_items == expected_items

        # Add links to relations[0]
        relation_data = add_data_to_sidebar_relation(harness_with_profiles, relations[0])
        relations[0].update(relation_data)

        actual_items = [
            DashboardLink(**item)
            for item in json.loads(harness_with_profiles.charm._context["menuLinks"])
        ]
        assert actual_items == relations[0]["sidebar_items"]

        # Add some links to relation 2, skipping relation1
        relation_data = add_data_to_sidebar_relation(harness_with_profiles, relations[2])
        relations[2].update(relation_data)
        actual_items = [
            DashboardLink(**item)
            for item in json.loads(harness_with_profiles.charm._context["menuLinks"])
        ]
        assert actual_items == relations[0]["sidebar_items"] + relations[2]["sidebar_items"]

        # Remove relation1, which should do nothing to the sidebar items
        harness_with_profiles.remove_relation(relation_id=relations[1]["rel_id"])
        actual_items = [
            DashboardLink(**item)
            for item in json.loads(harness_with_profiles.charm._context["menuLinks"])
        ]
        assert actual_items == relations[0]["sidebar_items"] + relations[2]["sidebar_items"]

        # Remove relation0, which should leave only the second set of sidebar items
        harness_with_profiles.remove_relation(relation_id=relations[0]["rel_id"])
        actual_items = [
            DashboardLink(**item)
            for item in json.loads(harness_with_profiles.charm._context["menuLinks"])
        ]
        assert actual_items == relations[2]["sidebar_items"]

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_sidebar_relation_and_config_and_ordering_together(
        self,
        harness_with_profiles: Harness,
    ):
        """Tests that combining relation- and user-driven sidebar items, with ordering."""
        # Arrange
        harness = harness_with_profiles

        # Add relation-based sidebar items
        relation = add_sidebar_relation(harness, other_app_name="other")
        relation_data = add_data_to_sidebar_relation(harness, relation)

        # Add config-based sidebar items
        config_sidebar_items = [
            DashboardLink(
                text="text-user-1",
                link="link-user-1",
                type="item-user-1",
                icon="icon-user-1",
            ),
        ]
        config_sidebar_items_as_dicts = [asdict(link) for link in config_sidebar_items]
        harness.update_config(
            {ADDITIONAL_MENU_LINKS_CONFIG: yaml.dump(config_sidebar_items_as_dicts)}
        )

        expected_sidebar_items = relation_data["sidebar_items"] + config_sidebar_items
        harness.begin()

        # Mock away lightkube-related tooling so config-changed hooks dont fail
        harness.charm._deploy_k8s_resources = MagicMock()

        # Act
        actual_items = [
            DashboardLink(**item) for item in json.loads(harness.charm._context["menuLinks"])
        ]

        # Assert
        # Should include both relation- and config-based items, ordered relation then config
        assert actual_items == expected_sidebar_items

        # Reorder the items via config
        preferred_links = ["text-user-1", "text-relation1-2"]  # the user-config link,
        harness.update_config({MENU_LINKS_ORDER_CONFIG: yaml.dump(preferred_links)})

        expected_sidebar_items_ordered = [
            config_sidebar_items[0],
            relation_data["sidebar_items"][2],
            relation_data["sidebar_items"][0],
            relation_data["sidebar_items"][1],
        ]
        # Assert
        # Should include both relation- and config-based items, ordered as set in config
        actual_items = [
            DashboardLink(**item) for item in json.loads(harness.charm._context["menuLinks"])
        ]
        assert actual_items == expected_sidebar_items_ordered


def add_sidebar_relation(harness: Harness, other_app_name: str):
    """Adds a sidebar relation to a harness."""
    rel_id = harness.add_relation(DASHBOARD_LINKS_RELATION_NAME, remote_app=other_app_name)
    return {"rel_id": rel_id, "app_name": other_app_name}


def add_data_to_sidebar_relation(harness: Harness, relation_metadata: dict):
    """Adds mock sidebar relation data to a relation on a harness."""
    rel_id = relation_metadata["rel_id"]
    app_name = relation_metadata["app_name"]
    sidebar_items = [
        DashboardLink(
            text=f"text-relation{rel_id}-{i}",
            link=f"link-relation{rel_id}-{i}",
            type=f"type-relation{rel_id}-{i}",
            icon=f"icon-relation{rel_id}-{i}",
        )
        for i in range(3)
    ]
    databag = {
        DASHBOARD_LINKS_FIELD: json.dumps([asdict(sidebar_item) for sidebar_item in sidebar_items])
    }
    harness.update_relation_data(relation_id=rel_id, app_or_unit=app_name, key_values=databag)

    return {
        "sidebar_items": sidebar_items,
        "databag": databag,
    }
