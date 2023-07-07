#!/usr/bin/env python3
from typing import List

from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    KubeflowDashboardLinksRequirer,
    DashboardLink,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus


class DashboardLinkRequirerMockCharm(CharmBase):
    """Charm for mocking the Requirer side of an integration test for the dashboard links."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dashboard_links = generate_menu_links(self.app.name)
        self.dashboard_link_requirer = KubeflowDashboardLinksRequirer(
            charm=self, relation_name="dashboard-links", dashboard_links=self.dashboard_links
        )

        self.model.unit.status = ActiveStatus()


def generate_menu_links(app_name: str) -> List[DashboardLink]:
    """Returns a list of dummy DashboardLinks with a specific structure for the sidebar."""
    return [
        DashboardLink(
            text=f"{app_name}-relative1",
            link=f"/{app_name}-relative1",
            type="item",
            icon="assessment",
        ),
        DashboardLink(
            text=f"{app_name}-relative2",
            link=f"/{app_name}-relative2",
            type="item",
            icon="assessment",
        ),
    ]


if __name__ == "__main__":
    main(DashboardLinkRequirerMockCharm)
