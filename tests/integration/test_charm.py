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
    address = status["applications"]["kubeflow-dashboard"]["address"]
    config = await ops_test.model.applications["kubeflow-dashboard"].get_config()
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

    charm_name = METADATA["name"]
    await ops_test.model.wait_for_idle(
        [charm_name],
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )
    assert ops_test.model.applications[charm_name].units[0].workload_status == "waiting"
    assert (
        ops_test.model.applications[charm_name].units[0].workload_status_message
        == "Waiting for kubeflow-profiles relation data"
    )


@pytest.mark.asyncio
@pytest.mark.abort_on_fail
async def test_add_profile_relation(ops_test: OpsTest):
    charm_name = METADATA["name"]
    await ops_test.model.deploy("kubeflow-profiles", channel="latest/edge", trust=True)
    await ops_test.model.add_relation("kubeflow-profiles", charm_name)
    await ops_test.model.wait_for_idle(
        ["kubeflow-profiles", charm_name],
        status="active",
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )


@pytest.mark.asyncio
async def test_status(ops_test: OpsTest):
    charm_name = METADATA["name"]
    assert ops_test.model.applications[charm_name].units[0].workload_status == "active"


@pytest.mark.asyncio
async def test_configmap_exist():
    configmap = Client().get(ConfigMap, "centraldashboard-config", namespace="kubeflow")
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
async def test_configmap_contents(ops_test: OpsTest):
    expected_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    configmap = Client().get(ConfigMap, "centraldashboard-config", namespace="kubeflow")
    links = json.loads(configmap.data["links"])
    assert links == expected_links


@pytest.mark.asyncio
async def test_charm_removal(ops_test: OpsTest):
    charm_name = METADATA["name"]
    await ops_test.model.remove_application(charm_name, block_until_done=True)

    # Ensure that the configmap is gone
    try:
        _ = Client().get(ConfigMap, "centraldashboard-config", namespace="kubeflow")
    except ApiError as e:
        assert e.status.code == 404
