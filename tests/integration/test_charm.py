# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

import aiohttp
import pytest
import pytest_asyncio
import yaml
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DASHBOARD_LINK_LOCATIONS,
    DashboardLink,
)
from dashboard_links_requirer_tester_charm.src.charm import generate_links_for_location
from lightkube import Client
from lightkube.resources.core_v1 import Service, ConfigMap
from pytest_operator.plugin import OpsTest

from charm import ADDITIONAL_LINKS_CONFIG_NAME, EXTERNAL_LINKS_ORDER_CONFIG_NAME

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
CONFIGMAP_NAME = CONFIG["options"]["dashboard-configmap"]["default"]
PROFILES_CHARM_NAME = "kubeflow-profiles"

DASHBOARD_LINKS_REQUIRER_TESTER_CHARM = Path(
    "tests/integration/dashboard_links_requirer_tester_charm"
).absolute()
TESTER_CHARM_NAME = "kubeflow-dashboard-requirer-tester"

DEFAULT_DOCUMENTATION_TEXTS = [
    "Getting started with Charmed Kubeflow",
    "Microk8s for Kubeflow",
    "Requirements for Kubeflow",
]


@pytest.fixture(scope="module")
def copy_libraries_into_tester_charm() -> None:
    """Ensure that the tester charms use the current libraries."""
    lib = Path("lib/charms/kubeflow_dashboard/v0/kubeflow_dashboard_links.py")
    Path(DASHBOARD_LINKS_REQUIRER_TESTER_CHARM, lib.parent).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(lib.as_posix(), (DASHBOARD_LINKS_REQUIRER_TESTER_CHARM / lib).as_posix())


@pytest_asyncio.fixture
async def lightkube_client():
    lightkube_client = Client(field_manager="test")
    yield lightkube_client


@pytest.mark.asyncio
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    my_charm = await ops_test.build_charm(".")
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]

    await ops_test.model.deploy(my_charm, resources={"oci-image": image_path}, trust=True)

    await ops_test.model.wait_for_idle(
        [CHARM_NAME],
        raise_on_error=True,
        timeout=300,
    )
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "blocked"
    assert (
        ops_test.model.applications[CHARM_NAME].units[0].workload_status_message
        == "Add required relation to kubeflow-profiles"
    )


@pytest.mark.asyncio
@pytest.mark.abort_on_fail
async def test_add_profile_relation(ops_test: OpsTest):
    await ops_test.model.deploy(PROFILES_CHARM_NAME, channel="latest/edge", trust=True)
    await ops_test.model.relate(PROFILES_CHARM_NAME, CHARM_NAME)
    await ops_test.model.wait_for_idle(
        [PROFILES_CHARM_NAME, CHARM_NAME],
        status="active",
        raise_on_error=True,
        timeout=600,
    )


@pytest.mark.asyncio
async def test_status(ops_test: OpsTest):
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.parametrize(
    "location, default_link_texts",
    [
        ("menu", [""]),
        ("external", [""]),
        ("quick", [""]),
        ("documentation", DEFAULT_DOCUMENTATION_TEXTS),
    ],
)
def test_configmap_contents_no_relations_or_config(
    lightkube_client: Client, location, default_link_texts
):
    """Tests the dashboard links before any relations or additional config.

    If this test failed, then likely the default links for one or more location have changed.  If
    this was desired, update this test.  Otherwise, fix the bug that removed them.
    """
    dummy_dashbaord_links = [
        DashboardLink(text=text, link="", location=location, icon="", type="", desc="")
        for text in default_link_texts
    ]
    assert_links_in_configmap_by_text_value(
        dummy_dashbaord_links, lightkube_client, location=location
    )


@pytest.mark.asyncio
async def test_configmap_contents_with_relations(
    ops_test: OpsTest, copy_libraries_into_tester_charm, lightkube_client: Client
):
    """Tests the contents of the dashboard link configmap after relations are added.

    This test uses ./tests/integration/dashboard_links_requirer_tester_charm, a mocker charm for the
    requirer side of the relation.  That charm is a simple charm that implements the Requirer side
    of the dashboard lib in a predictable way, providing the links requested for each location.
    """
    charm = await ops_test.build_charm("./tests/integration/dashboard_links_requirer_tester_charm")

    # Get the number of links for each group before, so we can confirm we didn't remove them later.
    starting_n_links = {
        location: len(await get_link_texts_from_configmap(lightkube_client, location))
        for location in DASHBOARD_LINK_LOCATIONS
    }

    expected_links = {name: [] for name in DASHBOARD_LINK_LOCATIONS}

    for tester_suffix in ["1", "2"]:
        tester = f"{TESTER_CHARM_NAME}{tester_suffix}"
        await ops_test.model.deploy(charm, application_name=tester)
        for location in ["menu", "documentation"]:
            link_texts = [location]
            these_links = generate_links_for_location(tester, texts=link_texts, location=location)
            await ops_test.model.applications[tester].set_config(
                {f"{location}_link_texts": yaml.dump(link_texts)}
            )
            expected_links[location].extend(these_links)

        await ops_test.model.relate(CHARM_NAME, tester)

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    for location in DASHBOARD_LINK_LOCATIONS:
        links = await assert_links_in_configmap_by_text_value(
            expected_links[location], lightkube_client, location=location, assert_exact=False
        )
        assert len(links) == starting_n_links[location] + len(expected_links[location])


@pytest.mark.asyncio
async def test_configmap_contents_with_menu_links_from_config(
    ops_test: OpsTest, lightkube_client: Client
):
    """Tests adding dashboard links via user config.

    Tests only menu and documentation, as the implementation for all locations is the same.
    """
    # Arrange
    # Remove any existing links from config before the test (it simplifies predicting the outcome
    # of the test)
    for location in ["menu", "documentation"]:
        await ops_test.model.applications[CHARM_NAME].set_config(
            {ADDITIONAL_LINKS_CONFIG_NAME[location]: ""}
        )

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    # Get the number of links for each group before adding config, so we can confirm we didn't
    # remove any preexisting links from other sources at the end of the test.
    starting_n_links = {
        location: len(await get_link_texts_from_configmap(lightkube_client, location))
        for location in DASHBOARD_LINK_LOCATIONS
    }

    # Add config and check if we get additional menu links
    expected_links = {name: [] for name in DASHBOARD_LINK_LOCATIONS}

    for location in ["menu", "documentation"]:
        config_links = [
            DashboardLink(
                text=f"{location}-config1",
                link="/1",
                type="item",
                icon="assessment",
                location=location,
            ),
            DashboardLink(
                text=f"{location}-config2",
                link="/2",
                type="item",
                icon="assessment",
                location=location,
            ),
        ]

        expected_links[location].extend(config_links)

        config_links_as_dicts = [asdict(link) for link in config_links]
        await ops_test.model.applications[CHARM_NAME].set_config(
            {ADDITIONAL_LINKS_CONFIG_NAME[location]: yaml.dump(config_links_as_dicts)}
        )

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    # Assert
    for location in DASHBOARD_LINK_LOCATIONS:
        links = await assert_links_in_configmap_by_text_value(
            expected_links[location], lightkube_client, location=location, assert_exact=False
        )
        assert len(links) == starting_n_links[location] + len(
            expected_links[location]
        ), f"unexpected number of links at {location}"


@pytest.mark.asyncio
async def test_configmap_contents_with_ordering(ops_test: OpsTest, lightkube_client: Client):
    """Tests that, if we add a link order, the configmap contents update as expected.

    Tests only menu and documentation, as the implementation for all locations is the same.
    """
    # Get the number of links for each group before adding config, so we can confirm we didn't
    # remove any preexisting links from other sources at the end of the test.
    starting_n_links = {
        location: len(await get_link_texts_from_configmap(lightkube_client, location))
        for location in DASHBOARD_LINK_LOCATIONS
    }

    # Move the user-driven links '*2' from the previous test to the top of the list
    # Test with both menu and documentation to confirm it works for different locations.
    for location in ["menu", "documentation"]:
        link_order = [f"{location}-config2"]

        await ops_test.model.applications[CHARM_NAME].set_config(
            {EXTERNAL_LINKS_ORDER_CONFIG_NAME[location]: yaml.dump(link_order)}
        )

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    # Assert
    for location in DASHBOARD_LINK_LOCATIONS:
        link_texts = await get_link_texts_from_configmap(lightkube_client, location)
        assert len(link_texts) == starting_n_links[location]
        if location in ["menu", "documentation"]:
            assert link_texts[0] == f"{location}-config2"


async def get_link_texts_from_configmap(lightkube_client, location):
    location_map = {
        "menu": "menuLinks",
        "external": "externalLinks",
        "quick": "quickLinks",
        "documentation": "documentationItems",
    }
    configmap = lightkube_client.get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    links = json.loads(configmap.data["links"])[location_map[location]]
    actual_link_text = [item["text"] for item in links]
    return actual_link_text


async def assert_links_in_configmap_by_text_value(
    expected_links, lightkube_client, location="menu", assert_exact=True
) -> List[Dict]:
    """Asserts that the dashboard configmap has the given link texts at this location.

    Link text is used as a proxy for comparing the whole DashboardLink item.

    Returns the link texts for this location in case further processing is needed.

    If assert_exact=True, this asserts configmap must have exactly these links.  Else, we only
    test that these links are in the configmap (aka, the configmap is a superset)
    """
    links_texts = await get_link_texts_from_configmap(lightkube_client, location)
    # Order is not guaranteed, so check that each is included individually
    if assert_exact:
        assert len(links_texts) == len(expected_links)
    for item in expected_links:
        # For some reason, comparing DashboardItems did not work here.  Comparing link texts
        # as an approximation.
        assert item.text in links_texts

    return links_texts


@pytest.mark.asyncio
async def test_dashboard_access(ops_test: OpsTest, lightkube_client: Client):
    namespace = ops_test.model_name
    application_ip = lightkube_client.get(Service, CHARM_NAME, namespace=namespace).spec.clusterIP
    config = await ops_test.model.applications[CHARM_NAME].get_config()
    application_port = config['port']['value']
    url = "http://" + str(application_ip) + ":" + str(application_port)

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=None) as response:
            result_status = response.status
            result_text = await response.text()
    assert result_status == 200
