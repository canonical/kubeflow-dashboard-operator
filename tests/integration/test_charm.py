# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from subprocess import check_output
from time import sleep

import json
import pytest
import yaml
from lightkube import Client
from lightkube.resources.core_v1 import ConfigMap
from selenium import webdriver
from selenium.common.exceptions import JavascriptException, WebDriverException
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
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


@pytest.mark.abort_on_fail
async def test_add_profile_relation(ops_test):
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


async def test_status(ops_test):
    charm_name = METADATA["name"]
    assert ops_test.model.applications[charm_name].units[0].workload_status == "active"


async def test_configmap_exist(ops_test):
    configmap = Client().get(ConfigMap, "centraldashboard-config")
    assert configmap is not None


async def test_configmap_contents(ops_test):
    expected_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    configmap = Client().get(ConfigMap, "centraldashboard-config")
    links = json.loads(configmap.data["links"])
    assert links == expected_links


@pytest.mark.abort_on_fail
async def test_add_sidebar_tensorboard_relation(ops_test):
    charm_path = "/home/pocik/Documents/code/kubeflow-tensorboards-operator/charms/tensorboards-web-app/tensorboards-web-app_ubuntu-20.04-amd64.charm"
    metadata_path = "/home/pocik/Documents/code/kubeflow-tensorboards-operator/charms/tensorboards-web-app/metadata.yaml"
    metadata = yaml.safe_load(Path(metadata_path).read_text())
    image_path = metadata["resources"]["oci-image"]["upstream-source"]

    await ops_test.model.deploy(charm_path, resources={"oci-image": image_path})
    tensorboard_charm_name = metadata["name"]
    charm_name = METADATA["name"]
    await ops_test.model.add_relation(
        f"{tensorboard_charm_name}:sidebar", f"{charm_name}:sidebar"
    )
    await ops_test.model.wait_for_idle(
        [tensorboard_charm_name],
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )


async def test_link_added_on_new_sidebar_relation(ops_test):
    metadata_path = "/home/pocik/Documents/code/kubeflow-tensorboards-operator/charms/tensorboards-web-app/metadata.yaml"
    metadata = yaml.safe_load(Path(metadata_path).read_text())
    tensorboard_charm_name = metadata["name"]
    tensorboard_link = {
        "app": tensorboard_charm_name,
        "type": "item",
        "link": "/tensorboards/",
        "text": "Tensorboards",
        "icon": "assessment",
    }
    base_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    base_links["menuLinks"] = base_links["menuLinks"] + [tensorboard_link]
    configmap = Client().get(ConfigMap, "centraldashboard-config")
    links = json.loads(configmap.data["links"])
    assert links == base_links


async def test_link_removed_on_removed_sidebar_relation(ops_test):
    metadata_path = "/home/pocik/Documents/code/kubeflow-tensorboards-operator/charms/tensorboards-web-app/metadata.yaml"
    metadata = yaml.safe_load(Path(metadata_path).read_text())
    tensorboard_charm_name = metadata["name"]
    charm_name = METADATA["name"]
    expected_links = json.loads(Path("./src/config/sidebar_config.json").read_text())
    await ops_test.run(
        "juju",
        "remove-relation",
        f"{tensorboard_charm_name}:sidebar",
        f"{charm_name}:sidebar",
    )
    await ops_test.model.wait_for_idle(
        [charm_name],
        status="active",
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )
    configmap = Client().get(ConfigMap, "centraldashboard-config")
    links = json.loads(configmap.data["links"])
    assert links == expected_links


# @pytest.mark.abort_on_fail
# async def test_add_sidebar_relation(ops_test):


# def fix_queryselector(elems):
#     """Workaround for web components breaking querySelector.

#     Because someone thought it was a good idea to just yeet the moral equivalent
#     of iframes everywhere over a single page 🤦

#     Shadow DOM was a terrible idea and everyone involved should feel professionally
#     ashamed of themselves. Every problem it tried to solved could and should have
#     been solved in better ways that don't break the DOM.
#     """

#     selectors = '").shadowRoot.querySelector("'.join(elems)
#     return 'return document.querySelector("' + selectors + '")'


# @pytest.fixture()
# async def driver(request, ops_test):
#     status = yaml.safe_load(
#         check_output(
#             ["juju", "status", "-m", ops_test.model_full_name, "--format=yaml"]
#         )
#     )
#     endpoint = status["applications"]["kubeflow-dashboard"]["address"]
#     application = ops_test.model.applications["kubeflow-dashboard"]
#     config = await application.get_config()
#     port = config["port"]["value"]
#     url = f"http://{endpoint}.nip.io:{port}/"
#     options = Options()
#     options.headless = True

#     with webdriver.Firefox(options=options) as driver:
#         wait = WebDriverWait(driver, 180, 1, (JavascriptException, StopIteration))
#         for _ in range(60):
#             try:
#                 driver.get(url)
#                 break
#             except WebDriverException:
#                 sleep(5)
#         else:
#             driver.get(url)

#         yield driver, wait, url

#         driver.get_screenshot_as_file(f"/tmp/selenium-{request.node.name}.png")


# def test_links(driver):
#     driver, wait, url = driver

#     # Ensure that sidebar links are set up properly
#     links = [
#         "/jupyter/",
#         # "/katib/",  # katib no longer available in default sidebar
#         "/pipeline/#/experiments",
#         "/pipeline/#/pipelines",
#         "/pipeline/#/runs",
#         "/pipeline/#/recurringruns",
#         # Removed temporarily until https://warthogs.atlassian.net/browse/KF-175 is fixed
#         # "/pipeline/#/artifacts",
#         # "/pipeline/#/executions",
#         "/volumes/",
#         # "/tensorboards/", # tensorboards no longer available in default sidebar
#     ]

#     for link in links:
#         print("Looking for link: %s" % link)
#         script = fix_queryselector(["main-page", f"iframe-link[href='{link}']"])
#         wait.until(lambda x: x.execute_script(script))

#     # Ensure that quick links are set up properly
#     links = [
#         "/pipeline/",
#         "/pipeline/#/runs",
#         "/jupyter/new?namespace=kubeflow",
#         "/katib/",
#     ]

#     for link in links:
#         print("Looking for link: %s" % link)
#         script = fix_queryselector(
#             [
#                 "main-page",
#                 "dashboard-view",
#                 f"iframe-link[href='{link}']",
#             ]
#         )
#         wait.until(lambda x: x.execute_script(script))

#     # Ensure that doc links are set up properly
#     links = [
#         "https://charmed-kubeflow.io/docs/kubeflow-basics",
#         "https://microk8s.io/docs/addon-kubeflow",
#         "https://www.kubeflow.org/docs/started/requirements/",
#     ]

#     for link in links:
#         print("Looking for link: %s" % link)
#         script = fix_queryselector(
#             [
#                 "main-page",
#                 "dashboard-view",
#                 f"a[href='{link}']",
#             ]
#         )
#         wait.until(lambda x: x.execute_script(script))
