import json
from dataclasses import asdict
from typing import List

from ops.charm import CharmBase
from ops.testing import Harness

from lib.charms.harness_extensions.v0.capture_events import capture
from lib.charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DASHBOARD_LINKS_FIELD,
    DashboardLink,
    KubeflowDashboardLinksProvider,
    KubeflowDashboardLinksRequirer,
    KubeflowDashboardLinksUpdatedEvent,
)

RELATION_NAME = "sidebar"
DUMMY_PROVIDER_METADATA = """
name: dummy-provider
provides:
  sidebar:
    interface: kubeflow_dashboard_sidebar
"""
DUMMY_REQUIRER_METADATA = """
name: dummy-requirer
requires:
  sidebar:
    interface: kubeflow_dashboard_sidebar
"""
REQUIRER_DASHBOARD_LINKS = [
    DashboardLink(
        text=f"text{i}", link=f"link{i}", type=f"type{i}", icon=f"icon{i}", location="menu"
    )
    for i in range(3)
]


class DummyProviderCharm(CharmBase):
    """Mock charm that is a sidebar Provider."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sidebar_provider = KubeflowDashboardLinksProvider(
            charm=self, relation_name=RELATION_NAME
        )


class DummyRequirerCharm(CharmBase):
    """Mock charm that is a sidebar Requirer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sidebar_requirer = KubeflowDashboardLinksRequirer(
            charm=self,
            relation_name=RELATION_NAME,
            dashboard_links=REQUIRER_DASHBOARD_LINKS,
        )


class TestProvider:
    def test_get_dashboard_links(self):
        """Tests that get_dashboard_links correctly returns information from the relation."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data, including multiple location values
        expected_sidebar_items_per_relation = (
                [
                    DashboardLink(text=f"text{i}-menu", link=f"link{i}-menu", type=f"type{i}-menu", icon=f"icon{i}-menu", location="menu")
                    for i in range(3)
                ] +
                [
                    DashboardLink(text=f"text{i}-documentation", link=f"link{i}-documentation", type=f"type{i}-documentation", icon=f"icon{i}-documentation", location="documentation")
                    for i in range(3)
                ]
        )
        databag = {
            DASHBOARD_LINKS_FIELD: json.dumps(
                [asdict(sidebar_item) for sidebar_item in expected_sidebar_items_per_relation]
            )
        }

        # Add data to relation
        relation_id = harness.add_relation(RELATION_NAME, other_app)
        harness.update_relation_data(
            relation_id=relation_id, app_or_unit=other_app, key_values=databag
        )

        # Add to a second relation so we simulate having two relations of data
        relation_id = harness.add_relation(RELATION_NAME, other_app)
        harness.update_relation_data(
            relation_id=relation_id, app_or_unit=other_app, key_values=databag
        )

        expected_sidebar_items = expected_sidebar_items_per_relation * 2

        harness.begin()

        # Act
        # Get DashboardLinks from relation data
        actual_sidebar_items = harness.charm.sidebar_provider.get_dashboard_links()

        # Assert
        assert actual_sidebar_items == expected_sidebar_items

    def test_get_dashboard_links_with_location(self):
        """Tests that get_dashboard_links correctly returns links for the location specified."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data, including multiple location values
        expected_dashboard_menu_links = [
            DashboardLink(text=f"text{i}-menu", link=f"link{i}-menu", type=f"type{i}-menu", icon=f"icon{i}-menu", location="menu")
            for i in range(3)
                ]
        other_dashboard_links = [
            DashboardLink(text=f"text{i}-documentation", link=f"link{i}-documentation", type=f"type{i}-documentation", icon=f"icon{i}-documentation", location="documentation")
            for i in range(3)
        ]

        databag = {
            DASHBOARD_LINKS_FIELD: json.dumps(
                [asdict(sidebar_item) for sidebar_item in expected_dashboard_menu_links + other_dashboard_links]
            )
        }

        # Add data to relation
        relation_id = harness.add_relation(RELATION_NAME, other_app)
        harness.update_relation_data(
            relation_id=relation_id, app_or_unit=other_app, key_values=databag
        )

        # Add to a second relation so we simulate having two relations of data
        relation_id = harness.add_relation(RELATION_NAME, other_app)
        harness.update_relation_data(
            relation_id=relation_id, app_or_unit=other_app, key_values=databag
        )

        # Double the data, because each relation has some
        expected_dashboard_menu_links = expected_dashboard_menu_links * 2

        harness.begin()

        # Act
        # Get DashboardLinks from relation data for just one location
        actual_dashboard_menu_links = harness.charm.sidebar_provider.get_dashboard_links(location="menu")

        # Assert
        assert actual_dashboard_menu_links == expected_dashboard_menu_links

    def test_get_dashboard_links_from_empty_relation(self):
        """Tests that get_sidebar_items correctly handles empty relations."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Add empty relation
        harness.add_relation(RELATION_NAME, other_app)

        expected_sidebar_items = []

        harness.begin()

        # Act
        # Get DashboardLinks from relation data
        actual_sidebar_items = harness.charm.sidebar_provider.get_dashboard_links()

        # Assert
        assert actual_sidebar_items == expected_sidebar_items

    def test_get_dashboard_links_as_json(self):
        """Tests that get_sidebar_items_as_json returns relation data correctly."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data
        expected_sidebar_items = [
            DashboardLink(text=f"text{i}", link=f"link{i}", type=f"type{i}", icon=f"icon{i}", location="menu")
            for i in range(3)
        ]
        databag = {
            DASHBOARD_LINKS_FIELD: json.dumps(
                [asdict(sidebar_item) for sidebar_item in expected_sidebar_items]
            )
        }
        expected_sidebar_items_as_json = json.dumps(
            [asdict(item) for item in expected_sidebar_items]
        )

        # Add data to relation
        relation_id = harness.add_relation(RELATION_NAME, other_app)
        harness.update_relation_data(
            relation_id=relation_id, app_or_unit=other_app, key_values=databag
        )

        harness.begin()

        # Act
        # Get DashboardLinks from relation data as json
        actual_sidebar_items_as_json = harness.charm.sidebar_provider.get_dashboard_links_as_json()

        # Assert
        assert actual_sidebar_items_as_json == expected_sidebar_items_as_json

    def test_emit_data_updated(self):
        """Tests that the Provider library emits KubeflowDashboardLinksUpdatedEvents."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data
        sidebar_item = DashboardLink(text="text", link="link", type="type", icon="icon", location="menu")
        databag = {DASHBOARD_LINKS_FIELD: json.dumps([asdict(sidebar_item)])}

        harness.begin()

        # Act/Assert
        relation_id = harness.add_relation(RELATION_NAME, other_app)

        # Add data to relation
        # Assert that we emit a data_updated event
        with capture(harness.charm, KubeflowDashboardLinksUpdatedEvent):
            harness.update_relation_data(
                relation_id=relation_id, app_or_unit=other_app, key_values=databag
            )

        # Remove relation
        # Assert that we emit a data_updated event
        with capture(harness.charm, KubeflowDashboardLinksUpdatedEvent):
            harness.remove_relation(relation_id=relation_id)


class TestRequirer:
    def test_send_dashboard_links_on_leader_elected(self):
        """Test that the Requirer correctly handles the leader elected event."""
        # Arrange
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

        assert actual_sidebar_items == REQUIRER_DASHBOARD_LINKS

    def test_send_dashboard_links_on_relation_created(self):
        """Test that the Requirer correctly handles the relation created event."""
        # Arrange
        other_app = "provider"
        harness = Harness(DummyRequirerCharm, meta=DUMMY_REQUIRER_METADATA)
        harness.set_leader(True)
        harness.begin()

        # Act
        relation_id = harness.add_relation(relation_name=RELATION_NAME, remote_app=other_app)

        # Assert
        actual_sidebar_items = get_sidebar_items_from_relation(
            harness, relation_id, harness.model.app
        )

        assert actual_sidebar_items == REQUIRER_DASHBOARD_LINKS

    def test_send_dashboard_links_without_leadership(self):
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


def get_sidebar_items_from_relation(harness, relation_id, this_app) -> List[DashboardLink]:
    """Returns the list of DashboardLinks from a sidebar relation on a harness."""
    raw_relation_data = harness.get_relation_data(relation_id=relation_id, app_or_unit=this_app)
    relation_data_as_dicts = json.loads(raw_relation_data[DASHBOARD_LINKS_FIELD])
    actual_dashboard_links = [DashboardLink(**data) for data in relation_data_as_dicts]
    return actual_dashboard_links
