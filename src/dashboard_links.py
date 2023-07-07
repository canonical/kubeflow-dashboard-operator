# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Tools for managing dashboard links from relations and charm config."""
import logging
from typing import List

import yaml
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DashboardLink,
    dashboard_links_to_json,
)

logger = logging.getLogger(__name__)


def aggregate_links(
    links_from_relation: List[DashboardLink], additional_link_config: str, link_order_config: str
):
    links_from_config = parse_dashboard_link_config(additional_link_config)
    preferred_link_order = parse_dashboard_link_order(link_order_config)

    all_links = links_from_relation + links_from_config
    all_links = sort_dashboard_links(all_links, preferred_link_order=preferred_link_order)
    return all_links


def aggregate_links_as_json(
    links_from_relation, additional_link_config: str, link_order_config: str
) -> str:
    return dashboard_links_to_json(
        aggregate_links(links_from_relation, additional_link_config, link_order_config)
    )


def parse_dashboard_link_config(config: str):
    """Parses the raw data from an additional-*-links config field, returning DashboardItems.

    If there are errors in parsing the config, this returns an empty list and logs a warning.
    """
    error_message = (
        f"Cannot parse a config-defined dashboard link from config '{config}' - this"
        "config input will be ignored."
    )

    if not config:
        return []

    try:
        links = yaml.safe_load(config)
    except yaml.YAMLError as err:
        logger.warning(f"{error_message}  Got error: {err}")
        return []

    try:
        links = [DashboardLink(**item) for item in links]
    except TypeError as err:
        logger.warning(f"{error_message}  Got error: {err}")
        return []

    return links


def parse_dashboard_link_order(config: str) -> List[str]:
    """Parses the string config value defining link order, returning the link order as strings.

    If there are errors in parsing the config, this returns an empty list and logs a warning.
    """
    error_message = (
        f"Cannot parse config-defined link order from config '{config}' - this config will be "
        "ignored and no preferred links will be set."
    )

    try:
        ordering = yaml.safe_load(config)
    except Exception as err:
        logger.warning(f"{error_message}  Got error: {err}")
        return []

    if not isinstance(ordering, (list, tuple)):
        logger.warning(f"{error_message}  Input must be a list of strings")
        return []

    for item in ordering:
        if not isinstance(item, str):
            logger.warning(f"{error_message}  Input must be a list of strings")
            return []

    return ordering


def sort_dashboard_links(dashboard_links: List[DashboardLink], preferred_link_order: List[str]):
    """Sorts a list of DashboardLinks by their link text, moving preferred links to the top.

    The sorted order of the returned list will be:
    * any links who have a text field that matches a string in `preferred_link_order`, in the order
      specified in preferred_link_order
    * any remaining links, in alphabetical order

    For example, if:
      dashboard_items=[
        DashboardLink(text="1"...),
        DashboardLink(text="2"...),
        DashboardLink(text="3"...)
      ]
      preferred_link_order=["2", "4"]
    The return will be:
      dashboard_links=[
        DashboardLink(text="2"...),
        DashboardLink(text="1"...),
        DashboardLink(text="3"...)
      ]

    If there are any links that have the same text, they will all be placed in the preferred
    links at the top.  They will be in the same order as provided in dashboard_links.  For example,
    if:
      dashboard_links=[
        DashboardLink(text="other"...),
        DashboardLink(text="1", link="1b", ...),
        DashboardLink(text="1", link="1a", ...),
      ]
      preferred_link_order=["1"]
    The return will be:
      dashboard_links=[
        DashboardLink(text="1", link="1b", ...),
        DashboardLink(text="1", link="1a", ...),
        DashboardLink(text="other"...),
      ]

    Args:
        dashboard_links: List of DashboardLinks to sort
        preferred_link_order: List of strings of DashboardLink text values to be moved to the top.

    Returns:
        Ordered list of DashboardLinks
    """
    ordered_dashboard_links = []
    removed_dashboard_links_index = set()
    for preferred_link in preferred_link_order:
        for i, dashboard_link in enumerate(dashboard_links):
            if dashboard_link.text == preferred_link:
                ordered_dashboard_links.append(dashboard_link)
                removed_dashboard_links_index.add(i)

    remaining_dashboard_links = [
        item for i, item in enumerate(dashboard_links) if i not in removed_dashboard_links_index
    ]
    remaining_dashboard_links = sorted(remaining_dashboard_links, key=lambda item: item.text)

    return ordered_dashboard_links + remaining_dashboard_links
