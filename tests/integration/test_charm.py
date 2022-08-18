# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from time import sleep

import json
from typing import Tuple
import pytest
import pytest_asyncio
import yaml
from lightkube import Client, ApiError
from lightkube.resources.core_v1 import ConfigMap
from selenium import webdriver
from selenium.common.exceptions import (
    JavascriptException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from pytest_operator.plugin import OpsTest


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
CONFIGMAP_NAME = CONFIG["options"]["dashboard-configmap"]["default"]
PROFILES_CHARM_NAME = "kubeflow-profiles"


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

    await ops_test.model.deploy(
        my_charm, resources={"oci-image": image_path}, trust=True
    )

    await ops_test.model.wait_for_idle(
        [CHARM_NAME],
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "waiting"
    assert (
        ops_test.model.applications[CHARM_NAME].units[0].workload_status_message
        == "Waiting for kubeflow-profiles relation data"
    )


@pytest.mark.asyncio
@pytest.mark.abort_on_fail
async def test_add_profile_relation(ops_test: OpsTest):
    await ops_test.model.deploy(PROFILES_CHARM_NAME, channel="latest/edge", trust=True)
    await ops_test.model.relate(PROFILES_CHARM_NAME, CHARM_NAME)
    await ops_test.model.wait_for_idle(
        [PROFILES_CHARM_NAME, CHARM_NAME],
        status="active",
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )


@pytest.mark.asyncio
async def test_status(ops_test: OpsTest):
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.asyncio
async def test_configmap_exist(lightkube_client: Client):
    configmap = lightkube_client.get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    assert configmap is not None


@pytest.mark.asyncio
def test_default_sidebar_links(driver: Tuple[webdriver.Chrome, WebDriverWait, str]):
    driver, wait, url = driver

    # Ensure that sidebar links are set up properly
    links = [
        "/jupyter/",
        "/pipeline/#/experiments",
        "/pipeline/#/pipelines",
        "/pipeline/#/runs",
        "/pipeline/#/recurringruns",
        "/volumes/",
        "/katib/",
        "/tensorboards/",
    ]

    for link in links:
        print("Looking for link: %s" % link)
        script = fix_queryselector(["main-page", f"iframe-link[href='{link}']"])
        wait.until(lambda x: x.execute_script(script))

    # Ensure that quick links are set up properly
    links = [
        "/pipeline/",
        "/pipeline/#/runs",
        "/jupyter/new?namespace=kubeflow",
        "/katib/",
    ]

    for link in links:
        print("Looking for link: %s" % link)
        script = fix_queryselector(
            [
                "main-page",
                "dashboard-view",
                f"iframe-link[href='{link}']",
            ]
        )
        wait.until(lambda x: x.execute_script(script))

    # Ensure that doc links are set up properly
    links = [
        "https://charmed-kubeflow.io/docs/kubeflow-basics",
        "https://microk8s.io/docs/addon-kubeflow",
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


@pytest.mark.asyncio
async def test_configmap_contents(lightkube_client: Client):
    expected_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    configmap = lightkube_client.get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    links = json.loads(configmap.data["links"])
    assert links == expected_links
