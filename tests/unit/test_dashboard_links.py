import json
from dataclasses import asdict

import pytest
import yaml
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import DashboardLink

from dashboard_links import (
    aggregate_links,
    aggregate_links_as_json,
    parse_dashboard_link_config,
    sort_dashboard_links,
)


@pytest.mark.parametrize(
    "location, expected_links",
    [
        ("menu", []),  # Empty config
        (
            "menu",
            [
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="2",
                    link="/2",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
        ),
    ],
)
def test_parse_dashboard_link_config_with_valid_links(location, expected_links):
    # Arrange
    expected_links_dicts = [asdict(link) for link in expected_links]

    actual_links = parse_dashboard_link_config(yaml.dump(expected_links_dicts), location)

    # Assert
    assert actual_links == expected_links


@pytest.mark.parametrize(
    "location, expected_links",
    [
        ("menu", []),  # Empty config
        (
            "menu",
            [
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="2",
                    link="/2",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
        ),
    ],
)
def test_parse_dashboard_link_config_with_valid_links_as_json(location, expected_links):
    # Arrange
    expected_links_dicts = [asdict(link) for link in expected_links]

    actual_links = parse_dashboard_link_config(json.dumps(expected_links_dicts), location)

    # Assert
    assert actual_links == expected_links


@pytest.mark.parametrize(
    "config_yaml",
    (
        "[malformed yaml",
        '[{"correct yaml with incomplete sidebar item dicts": "x"}]',
    ),
)
def test_parse_dashboard_link_config_with_invalid_links(config_yaml, caplog):
    actual_links = parse_dashboard_link_config(config_yaml, location="menu")

    assert actual_links == []
    assert len(caplog.records) == 1
    assert "Cannot parse" in caplog.records[-1].message


@pytest.mark.parametrize(
    "dashboard_links, preferred_link_order, expected_result",
    [
        ([], ["some stuff"], []),  # Case where we have null input/output
        # Case where we have empty reorder, so nothing should change
        (
            [
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="2",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
            [],
            [
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="2",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
        ),
        # Case where we have links that should be reordered
        (
            [
                DashboardLink(
                    text="3",
                    link="/3",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="2",
                    link="/2",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
            ("2", "3"),
            [
                DashboardLink(
                    text="2",
                    link="/2",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="3",
                    link="/3",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
        ),
        # Case where we have multiple links with the same text
        (
            [
                DashboardLink(
                    text="3",
                    link="/3",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="1",
                    link="/1b",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="3",
                    link="/3b",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="2",
                    link="/2",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
            ("2", "3"),
            [
                DashboardLink(
                    text="2",
                    link="/2",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="3",
                    link="/3",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="3",
                    link="/3b",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
                DashboardLink(
                    text="1",
                    link="/1b",
                    type="item",
                    icon="assessment",
                    location="menu",
                ),
            ],
        ),
    ],
)
def test_sort_dashboard_links(dashboard_links, preferred_link_order, expected_result):
    """Tests that sort_sidebar_items works as expected."""
    actual_sorted_items = sort_dashboard_links(
        dashboard_links, preferred_link_order=preferred_link_order
    )
    assert actual_sorted_items == expected_result


@pytest.mark.parametrize(
    "links_from_relation, additional_link_config, link_order_config, location, expected_aggregated_links",  # noqa
    (
        (
            # Empty case
            (
                [],
                "",
                "",
                "menu",
                [],
            ),
            # Case where we have links that should be reordered
            (
                # links_from_relation
                [
                    DashboardLink(
                        text="3",
                        link="/3",
                        type="item",
                        icon="assessment",
                        location="menu",
                    ),
                    DashboardLink(
                        text="1",
                        link="/1",
                        type="item",
                        icon="assessment",
                        location="menu",
                    ),
                    DashboardLink(
                        text="2",
                        link="/2",
                        type="item",
                        icon="assessment",
                        location="menu",
                    ),
                ],
                # additional_link_config
                yaml.dump(
                    [
                        {
                            "text": "4",
                            "link": "/4",
                            "type": "item",
                            "icon": "assessment",
                            "location": "menu",
                        }
                    ]
                ),
                # link_order_config
                yaml.dump(["2", "4"]),
                # expected_aggregated_links
                "menu",
                [
                    DashboardLink(
                        text="2",
                        link="/2",
                        type="item",
                        icon="assessment",
                        location="menu",
                    ),
                    DashboardLink(
                        text="4",
                        link="/4",
                        type="item",
                        icon="assessment",
                        location="menu",
                    ),
                    DashboardLink(
                        text="1",
                        link="/1",
                        type="item",
                        icon="assessment",
                        location="menu",
                    ),
                    DashboardLink(
                        text="3",
                        link="/3",
                        type="item",
                        icon="assessment",
                        location="menu",
                    ),
                ],
            ),
        )
    ),
)
def test_aggregate_links(
    links_from_relation,
    additional_link_config,
    link_order_config,
    location,
    expected_aggregated_links,
):
    actual_aggregated_links = aggregate_links(
        links_from_relation, additional_link_config, link_order_config, location
    )
    assert actual_aggregated_links == expected_aggregated_links


@pytest.mark.parametrize(
    "dashboard_links, location, expected_json",
    [
        [
            [
                DashboardLink(
                    text="1",
                    link="/1",
                    type="item",
                    icon="assessment",
                    location="menu",
                    desc="desc",
                ),
            ],
            "menu",
            json.dumps(
                [
                    {
                        "text": "1",
                        "link": "/1",
                        "type": "item",
                        "icon": "assessment",
                        "location": "menu",
                        "desc": "desc",
                    }
                ]
            ),
        ],
        [
            [],
            "menu",
            json.dumps([]),
        ],
    ],
)
def test_aggregate_links_as_json(dashboard_links, location, expected_json):
    actual_json = aggregate_links_as_json(dashboard_links, "", "", location)

    # Interpret the JSON as python object to ignore ordering differences
    actual = json.loads(actual_json)
    expected = json.loads(expected_json)

    assert actual == expected
