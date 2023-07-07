# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from time import sleep
from typing import Dict, List, Tuple

import pytest
import pytest_asyncio
import yaml
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import DashboardLink
from dashboard_links_requirer_tester_charm.src.charm import generate_menu_links
from lightkube import Client
from lightkube.resources.core_v1 import ConfigMap
from pytest_operator.plugin import OpsTest
from selenium import webdriver
from selenium.common.exceptions import JavascriptException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from charm import ADDITIONAL_MENU_LINKS_CONFIG, MENU_LINKS_ORDER_CONFIG

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
CONFIGMAP_NAME = CONFIG["options"]["dashboard-configmap"]["default"]
PROFILES_CHARM_NAME = "kubeflow-profiles"

DASHBOARD_LINKS_REQUIRER_TESTER_CHARM = Path(
    "tests/integration/dashboard_links_requirer_tester_charm"
).absolute()
TESTER_CHARM_NAME = "kubeflow-dashboard-requirer-tester"


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


@pytest_asyncio.fixture
async def driver(ops_test: OpsTest) -> Tuple[webdriver.Chrome, WebDriverWait, str]:
    tmp = await ops_test.run(
        "juju",
        "status",
        "-m",
        ops_test.model_name,
        "--format=yaml",
    )
    status = yaml.safe_load(tmp[1])
    address = status["applications"][CHARM_NAME]["address"]
    config = await ops_test.model.applications[CHARM_NAME].get_config()
    port = config["port"]["value"]
    url = f"http://{address}.nip.io:{port}/"
    options = Options()
    options.headless = True

    with webdriver.Chrome(options=options) as driver:
        driver.delete_all_cookies()
        wait = WebDriverWait(driver, 20, 1, (JavascriptException, StopIteration))
        for _ in range(60):
            try:
                driver.get(url)
                break
            except WebDriverException:
                sleep(5)
        else:
            driver.get(url)

        yield driver, wait, url

        driver.get_screenshot_as_file("/tmp/selenium-dashboard.png")


def fix_queryselector(elems):
    """Workaround for web components breaking querySelector.
    Because someone thought it was a good idea to just yeet the moral equivalent
    of iframes everywhere over a single page 🤦
    Shadow DOM was a terrible idea and everyone involved should feel professionally
    ashamed of themselves. Every problem it tried to solved could and should have
    been solved in better ways that don't break the DOM.
    """

    selectors = '").shadowRoot.querySelector("'.join(elems)
    return 'return document.querySelector("' + selectors + '")'


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
        timeout=300,
    )


@pytest.mark.asyncio
async def test_status(ops_test: OpsTest):
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.asyncio
async def test_configmap_contents_no_relations_or_config(lightkube_client: Client):
    """Tests the contents of the dashboard link configmap when no relations are present."""
    expected_links = []
    configmap = lightkube_client.get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    links = json.loads(configmap.data["links"])["menuLinks"]
    assert links == expected_links


@pytest.mark.asyncio
async def test_configmap_contents_with_relations(
    ops_test: OpsTest, copy_libraries_into_tester_charm, lightkube_client: Client
):
    """Tests the contents of the dashboard link configmap when relations are present.

    This test uses ./tests/integration/dashboard_links_requirer_tester_charm, a mocker charm for the
    requirer side of the relation.  That charm is a simple charm that implements the Requirer side
    of the dashboard lib in a predictable way.
    """
    tester1 = f"{TESTER_CHARM_NAME}1"
    tester2 = f"{TESTER_CHARM_NAME}2"
    charm = await ops_test.build_charm("./tests/integration/dashboard_links_requirer_tester_charm")
    await ops_test.model.deploy(charm, application_name=tester1)

    await ops_test.model.deploy(charm, application_name=tester2)

    await ops_test.model.relate(CHARM_NAME, tester1)
    await ops_test.model.relate(CHARM_NAME, tester2)

    expected_menu_links = [
        *generate_menu_links(tester1),
        *generate_menu_links(tester2),
    ]

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    await assert_menulinks_in_configmap(expected_menu_links, lightkube_client)


@pytest.mark.asyncio
async def test_configmap_contents_with_menu_links_from_config(
    ops_test: OpsTest, lightkube_client: Client
):
    """Tests the contents of the dashboard menu link configmap when user-driven links added."""
    # Arrange
    # Add config and check if we get additional menu links
    config_menu_links = [
        DashboardLink(
            text="1",
            link="/1",
            type="item",
            icon="assessment",
        ),
        DashboardLink(
            text="2",
            link="/2",
            type="item",
            icon="assessment",
        ),
    ]

    config_menu_links_as_dicts = [asdict(link) for link in config_menu_links]

    expected_menu_links = [
        *config_menu_links,
        *generate_menu_links(f"{TESTER_CHARM_NAME}1"),
        *generate_menu_links(f"{TESTER_CHARM_NAME}2"),
    ]

    # Act
    await ops_test.model.applications[CHARM_NAME].set_config(
        {ADDITIONAL_MENU_LINKS_CONFIG: yaml.dump(config_menu_links_as_dicts)}
    )

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    # Assert
    await assert_menulinks_in_configmap(expected_menu_links, lightkube_client)


@pytest.mark.asyncio
async def test_configmap_contents_for_menu_links_with_ordering(
    ops_test: OpsTest, lightkube_client: Client
):
    """Tests that, if we add a menu link order, the configmap contents update as expected."""
    # Move the user-driven link '2' from the previous test to the top of the list
    menu_link_order = ["2"]

    expected_menu_links = [
        DashboardLink(
            text="2",
            link="/2",
            type="item",
            icon="assessment",
        ),
        DashboardLink(
            text="1",
            link="/1",
            type="item",
            icon="assessment",
        ),
        *generate_menu_links(f"{TESTER_CHARM_NAME}1"),
        *generate_menu_links(f"{TESTER_CHARM_NAME}2"),
    ]

    await ops_test.model.applications[CHARM_NAME].set_config(
        {MENU_LINKS_ORDER_CONFIG: yaml.dump(menu_link_order)}
    )

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    # Assert
    actual_menu_links = await assert_menulinks_in_configmap(expected_menu_links, lightkube_client)
    assert actual_menu_links[0]["text"] == expected_menu_links[0].text


@pytest.mark.asyncio
def test_default_dashboard_links(driver: Tuple[webdriver.Chrome, WebDriverWait, str]):
    """Tests all dashboard links other than the menu links."""
    driver, wait, url = driver

    # Ensure that doc links are set up properly
    links = [
        "https://charmed-kubeflow.io/docs/get-started-with-charmed-kubeflow#heading--part-ii-get-started-with-charmed-kubeflow",  # noqa: E501
        "https://charmed-kubeflow.io/docs/get-started-with-charmed-kubeflow#heading--install-and-prepare-microk8s-",  # noqa: E501
        "https://www.kubeflow.org/docs/started/requirements/",
    ]

    for link in links:
        print("Looking for link: %s" % link)
        script = fix_queryselector(
            [
                "main-page",
                "dashboard-view",
                f"a[href='{link}']",
            ]
        )
        wait.until(lambda x: x.execute_script(script))


async def assert_menulinks_in_configmap(expected_menu_links, lightkube_client) -> List[Dict]:
    """Asserts that the dashboard configmap has exactly the menuLinks (sidebar links) expected.

    Returns the menu link data pulled from the configmap in case further processing is needed.
    """
    configmap = lightkube_client.get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    menu_links = json.loads(configmap.data["links"])["menuLinks"]
    menu_links_text = [item["text"] for item in menu_links]
    # Order is not guaranteed, so check that each is included individually
    assert len(menu_links) == len(expected_menu_links)
    for item in expected_menu_links:
        # For some reason, comparing DashboardItems did not work here.  Comparing link texts
        # as an approximation.
        assert item.text in menu_links_text

    return menu_links
