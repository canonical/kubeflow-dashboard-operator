# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import shutil
from pathlib import Path
from time import sleep
from typing import Tuple

import pytest
import pytest_asyncio
import yaml
from lightkube import Client
from lightkube.resources.core_v1 import ConfigMap
from pytest_operator.plugin import OpsTest
from selenium import webdriver
from selenium.common.exceptions import JavascriptException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from sidebar_requirer_tester_charm.src.charm import generate_sidebar_items

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
CONFIGMAP_NAME = CONFIG["options"]["dashboard-configmap"]["default"]
PROFILES_CHARM_NAME = "kubeflow-profiles"

SIDEBAR_REQUIRER_TESTER_CHARM_PATH = Path(
    "tests/integration/sidebar_requirer_tester_charm"
).absolute()


@pytest.fixture(scope="module")
def copy_grafana_libraries_into_tester_charm() -> None:
    """Ensure that the tester charms use the current libraries."""
    lib = Path("lib/charms/kubeflow_dashboard/v1/kubeflow_dashboard_sidebar.py")
    Path(SIDEBAR_REQUIRER_TESTER_CHARM_PATH, lib.parent).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(lib.as_posix(), (SIDEBAR_REQUIRER_TESTER_CHARM_PATH / lib).as_posix())


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
async def test_configmap_contents_no_relations(lightkube_client: Client):
    """Tests the contents of the dashboard sidebar link configmap when no relations are present."""
    expected_links = []
    configmap = lightkube_client.get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    links = json.loads(configmap.data["links"])["menuLinks"]
    assert links == expected_links


@pytest.mark.asyncio
async def test_configmap_contents_with_relations(
    ops_test: OpsTest, copy_grafana_libraries_into_tester_charm, lightkube_client: Client
):
    """Tests the contents of the dashboard sidebar link configmap when relations are present."""
    tester1 = "kubeflow-dashboard-requirer-tester1"
    tester2 = "kubeflow-dashboard-requirer-tester2"
    charm = await ops_test.build_charm("./tests/integration/sidebar_requirer_tester_charm")
    await ops_test.model.deploy(charm, application_name=tester1)

    await ops_test.model.deploy(charm, application_name=tester2)

    await ops_test.model.relate(CHARM_NAME, tester1)
    await ops_test.model.relate(CHARM_NAME, tester2)

    expected_sidebar_items = [
        *generate_sidebar_items(tester1),
        *generate_sidebar_items(tester2),
    ]

    # Wait for everything to settle
    await ops_test.model.wait_for_idle(
        raise_on_error=True,
        raise_on_blocked=True,
        status="active",
        timeout=150,
    )

    # Assert that the configmap has the expected links
    configmap = lightkube_client.get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    sidebar_items = json.loads(configmap.data["links"])["menuLinks"]
    sidebar_item_text = [item["text"] for item in sidebar_items]

    # Order is not guaranteed, so check that each is included individually
    assert len(sidebar_items) == len(expected_sidebar_items)
    for item in expected_sidebar_items:
        # For some reason, comparing sidebar items did not work here.  Comparing sidebar item
        # names as an approximation.
        assert item.text in sidebar_item_text


@pytest.mark.asyncio
def test_default_dashboard_links(driver: Tuple[webdriver.Chrome, WebDriverWait, str]):
    """Tests all dashboard links other than the sidebar."""
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
