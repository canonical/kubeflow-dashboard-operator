import json
from dataclasses import asdict
from typing import List

from ops.charm import CharmBase
from ops.testing import Harness

from lib.charms.harness_extensions.v0.capture_events import capture
from lib.charms.kubeflow_dashboard.v1.kubeflow_dashboard_sidebar import (
    KubeflowDashboardSidebarProvider,
    SidebarItem,
    KubeflowDashboardSidebarRequirer,
    SIDEBAR_ITEMS_FIELD,
    KubeflowDashboardSidebarDataUpdatedEvent,
)

RELATION_NAME = "sidebar"
DUMMY_PROVIDER_METADATA = """
name: dummy-provider
provides:
  sidebar:
    interface: kubeflow-dashboard-sidebar
"""
DUMMY_REQUIRER_METADATA = """
name: dummy-requirer
requires:
  sidebar:
    interface: kubeflow-dashboard-sidebar
"""
REQUIRER_SIDEBAR_ITEMS = [
    SidebarItem(text=f"text{i}", link=f"link{i}", type=f"type{i}", icon=f"icon{i}")
    for i in range(3)
]


class DummyProviderCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sidebar_provider = KubeflowDashboardSidebarProvider(
            charm=self, relation_name=RELATION_NAME
        )


class DummyRequirerCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sidebar_requirer = KubeflowDashboardSidebarRequirer(
            charm=self,
            relation_name=RELATION_NAME,
            sidebar_items=REQUIRER_SIDEBAR_ITEMS,
        )


class TestProvider:
    def test_get_sidebar_items(self):
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data
        expected_sidebar_items = [
            SidebarItem(text=f"text{i}", link=f"link{i}", type=f"type{i}", icon=f"icon{i}")
            for i in range(3)
        ]
        databag = {
            SIDEBAR_ITEMS_FIELD: json.dumps(
                [asdict(sidebar_item) for sidebar_item in expected_sidebar_items]
            )
        }

        # Add data to relation
        relation_id = harness.add_relation(RELATION_NAME, other_app)
        harness.update_relation_data(
            relation_id=relation_id, app_or_unit=other_app, key_values=databag
        )

        harness.begin()

        # Act
        # Get SidebarItems from relation data
        actual_sidebar_items = harness.charm.sidebar_provider.get_sidebar_items()

        # Assert
        assert actual_sidebar_items == expected_sidebar_items

    def test_emit_data_updated(self):
        """Tests that the Provider library emits KubeflowDashboardSidebarDataUpdatedEvents."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data
        sidebar_item = SidebarItem(text="text", link="link", type="type", icon="icon")
        databag = {SIDEBAR_ITEMS_FIELD: json.dumps([asdict(sidebar_item)])}

        harness.begin()

        # Act/Assert
        relation_id = harness.add_relation(RELATION_NAME, other_app)

        # Add data to relation
        # Assert that we emit a data_updated event
        with capture(harness.charm, KubeflowDashboardSidebarDataUpdatedEvent) as captured:
            harness.update_relation_data(
                relation_id=relation_id, app_or_unit=other_app, key_values=databag
            )

        # Remove relation
        # Assert that we emit a data_updated event
        with capture(harness.charm, KubeflowDashboardSidebarDataUpdatedEvent) as captured:
            harness.remove_relation(relation_id=relation_id)


class TestRequirer:
    def test_send_sidebar_on_leader_elected(self):
        harness = Harness(DummyRequirerCharm, meta=DUMMY_REQUIRER_METADATA)
        other_app = "provider"
        this_app = harness.model.app

        relation_id = harness.add_relation(relation_name=RELATION_NAME, remote_app=other_app)

        harness.begin()
        # Confirm that we have no data in the relation yet
        raw_relation_data = harness.get_relation_data(
            relation_id=relation_id, app_or_unit=this_app
        )
        assert raw_relation_data == {}

        # Act
        harness.set_leader(True)

        # Assert
        actual_sidebar_items = get_sidebar_items_from_relation(harness, relation_id, this_app)

        assert actual_sidebar_items == REQUIRER_SIDEBAR_ITEMS

    def test_send_sidebar_on_relation_created(self):
        other_app = "provider"
        harness = Harness(DummyRequirerCharm, meta=DUMMY_REQUIRER_METADATA)
        harness.set_leader(True)
        harness.begin()

        relation_id = harness.add_relation(relation_name=RELATION_NAME, remote_app=other_app)

        actual_sidebar_items = get_sidebar_items_from_relation(
            harness, relation_id, harness.model.app
        )

        assert actual_sidebar_items == REQUIRER_SIDEBAR_ITEMS

    def test_send_sidebar_without_leadership(self):
        """Tests whether library incorrectly sends sidebar data when unit is not leader."""
        # Arrange
        other_app = "provider"
        harness = Harness(DummyRequirerCharm, meta=DUMMY_REQUIRER_METADATA)
        harness.set_leader(False)
        harness.begin()

        # Act
        # This should do nothing because we are not the leader
        relation_id = harness.add_relation(relation_name=RELATION_NAME, remote_app=other_app)

        # Assert
        # There should be no data in the relation, because we should skip writing data when not
        # leader
        raw_relation_data = harness.get_relation_data(
            relation_id=relation_id, app_or_unit=harness.model.app
        )
        assert raw_relation_data == {}


def get_sidebar_items_from_relation(harness, relation_id, this_app) -> List[SidebarItem]:
    raw_relation_data = harness.get_relation_data(relation_id=relation_id, app_or_unit=this_app)
    relation_data_as_dicts = json.loads(raw_relation_data[SIDEBAR_ITEMS_FIELD])
    actual_sidebar_items = [SidebarItem(**data) for data in relation_data_as_dicts]
    return actual_sidebar_items
