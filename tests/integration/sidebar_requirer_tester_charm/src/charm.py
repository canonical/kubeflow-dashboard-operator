#!/usr/bin/env python3
from typing import List

from charms.kubeflow_dashboard.v0.kubeflow_dashboard_sidebar import (
    KubeflowDashboardSidebarRequirer,
    SidebarItem,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus


class SidebarRequirerMockCharm(CharmBase):
    """Charm for mocking the Requirer side of an integration test for the sidebar."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sidebar_items = generate_sidebar_items(self.app.name)
        self.sidebar_requirer = KubeflowDashboardSidebarRequirer(
            charm=self, relation_name="sidebar", sidebar_items=self.sidebar_items
        )

        self.model.unit.status = ActiveStatus()


def generate_sidebar_items(app_name: str) -> List[SidebarItem]:
    """Returns a list of dummy SidebarItems with a specific structure."""
    return [
        SidebarItem(
            text=f"{app_name}-relative1",
            link=f"/{app_name}-relative1",
            type="item",
            icon="assessment",
        ),
        SidebarItem(
            text=f"{app_name}-relative2",
            link=f"/{app_name}-relative2",
            type="item",
            icon="assessment",
        ),
    ]


if __name__ == "__main__":
    main(SidebarRequirerMockCharm)