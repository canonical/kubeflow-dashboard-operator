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
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from pytest_operator.plugin import OpsTest


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
CONFIGMAP_NAME = CONFIG["options"]["dashboard-configmap"]["default"]
PROFILES_CHARM_NAME = "kubeflow-profiles"
TENSORBOARD_CHARM_NAME = "tensorboards-web-app"


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
    await ops_test.model.add_relation(PROFILES_CHARM_NAME, CHARM_NAME)
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
async def test_configmap_exist():
    configmap = Client().get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
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
async def test_default_sidebar_links_missing_tensoboards(
    driver: Tuple[webdriver.Chrome, WebDriverWait, str]
):
    driver, wait, url = driver
    with pytest.raises(TimeoutException):
        script = fix_queryselector(["main-page", "iframe-link[href='/tensorboards/']"])
        wait.until(lambda x: x.execute_script(script))


async def test_configmap_contents(ops_test: OpsTest):
    expected_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    configmap = Client().get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    links = json.loads(configmap.data["links"])
    assert links == expected_links


@pytest.mark.abort_on_fail
async def test_add_sidebar_tensorboard_relation(ops_test: OpsTest):
    await ops_test.model.deploy(
        "TENSORBOARD_CHARM_NAME", channel="latest/edge", trust=True
    )  # This assumes that the chages were merged
    await ops_test.model.add_relation(
        f"{TENSORBOARD_CHARM_NAME}:sidebar", f"{CHARM_NAME}:sidebar"
    )
    await ops_test.model.wait_for_idle(
        [TENSORBOARD_CHARM_NAME],
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )


def test_configmap_link_added_on_new_sidebar_relation(ops_test: OpsTest):
    tensorboard_link = {
        "app": TENSORBOARD_CHARM_NAME,
        "type": "item",
        "link": "/tensorboards/",
        "text": "Tensorboards",
        "icon": "assessment",
    }
    base_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    base_links["menuLinks"] = base_links["menuLinks"] + [tensorboard_link]
    configmap = Client().get(ConfigMap, CONFIGMAP_NAME)
    links = json.loads(configmap.data["links"])
    assert links == base_links


@pytest.mark.asyncio
async def test_tensorboard_added_sidebar_links(
    driver: Tuple[webdriver.Chrome, WebDriverWait, str]
):
    driver, wait, url = driver

    # Ensure that sidebar links are set up properly
    links = [
        "/jupyter/",
        "/pipeline/#/experiments",
        "/pipeline/#/pipelines",
        "/pipeline/#/runs",
        "/pipeline/#/recurringruns",
        "/volumes/",
        "/tensorboards/",
    ]

    for link in links:
        print("Looking for link: %s" % link)
        script = fix_queryselector(["main-page", f"iframe-link[href='{link}']"])
        wait.until(lambda x: x.execute_script(script))


async def test_configmap_link_removed_on_removed_sidebar_relation(
    ops_test: OpsTest, driver: Tuple[webdriver.Chrome, WebDriverWait, str]
):
    expected_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    await ops_test.run(
        "juju",
        "remove-relation",
        f"{TENSORBOARD_CHARM_NAME}:sidebar",
        f"{CHARM_NAME}:sidebar",
    )
    await ops_test.model.wait_for_idle(
        [CHARM_NAME],
        status="active",
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )
    configmap = Client().get(ConfigMap, CONFIGMAP_NAME)
    links = json.loads(configmap.data["links"])
    assert links == expected_links
    driver, wait, url = driver
    with pytest.raises(TimeoutException):
        script = fix_queryselector(["main-page", "iframe-link[href='/tensorboard/']"])
        wait.until(lambda x: x.execute_script(script))


@pytest.mark.asyncio
async def test_charm_removal(ops_test: OpsTest):
    await ops_test.model.remove_application(CHARM_NAME, block_until_done=True)

    # Ensure that the configmap is gone
    try:
        _ = Client().get(ConfigMap, CONFIGMAP_NAME, namespace="kubeflow")
    except ApiError as e:
        assert e.status.code == 404
