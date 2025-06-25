#!/usr/bin/env python3
from typing import List, Optional

import yaml
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DASHBOARD_LINK_LOCATIONS,
    DashboardLink,
    KubeflowDashboardLinksRequirer,
)
from ops import main
from ops.charm import CharmBase
from ops.model import ActiveStatus

# Map of location to the config field names for that location
ADDITIONAL_LINKS_CONFIG_NAME = {
    location: f"additional-{location}-links" for location in DASHBOARD_LINK_LOCATIONS
}
EXTERNAL_LINKS_ORDER_CONFIG_NAME = {
    location: f"{location}-link-order" for location in DASHBOARD_LINK_LOCATIONS
}

# Map to provide either absolute or relative link based on location
LOCATION_TO_LINK = {
    "menu": "/not-real-page",
    "quick": "/not-real-page",
    "external": "https://charmed-kubeflow.io/",
    "documentation": "https://charmed-kubeflow.io/",
}


class DashboardLinkRequirerMockCharm(CharmBase):
    """Charm for mocking the Requirer side of an integration test for the dashboard links.

    Generates a link for each link text provided in juju config.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dashboard_links = self.generate_menu_links()
        self.dashboard_link_requirer = KubeflowDashboardLinksRequirer(
            charm=self, relation_name="dashboard-links", dashboard_links=self.dashboard_links
        )

        self.model.unit.status = ActiveStatus()

    def generate_menu_links(self) -> List[DashboardLink]:
        """Returns a list of dummy DashboardLinks for each request through charm config."""
        menu_texts = self.get_links_texts(location="menu")
        external_texts = self.get_links_texts(location="external")
        quick_texts = self.get_links_texts(location="quick")
        documentation_texts = self.get_links_texts(location="documentation")
        return generate_links(
            self.app.name,
            menu_texts=menu_texts,
            external_texts=external_texts,
            quick_texts=quick_texts,
            documentation_texts=documentation_texts,
        )

    def get_links_texts(self, location) -> List[str]:
        return yaml.safe_load(self.model.config[f"{location}_link_texts"])


def generate_links(
    app_name, menu_texts=None, external_texts=None, quick_texts=None, documentation_texts=None
):
    """Returns a list of DashboardLink items for all the provided text values."""

    return (
        generate_links_for_location(app_name, texts=menu_texts, location="menu")
        + generate_links_for_location(app_name, texts=external_texts, location="external")
        + generate_links_for_location(app_name, texts=quick_texts, location="quick")
        + generate_links_for_location(
            app_name, texts=documentation_texts, location="documentation"
        )
    )


def generate_links_for_location(
    app_name: str, texts: Optional[List[str]], location: str
) -> List[DashboardLink]:
    """Returns list of dummy DashboardLinks."""
    if texts is None:
        return []

    dashboard_links = []
    for text in texts:
        dashboard_links.append(
            DashboardLink(
                text=f"{app_name}-{text}",
                link=LOCATION_TO_LINK[location],
                type="item",
                icon="assessment",
                location=location,
            )
        )
    return dashboard_links


if __name__ == "__main__":
    main(DashboardLinkRequirerMockCharm)
