# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness
import yaml

from charm import Operator


@pytest.fixture
def harness():
    harness = Harness(Operator)
    # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
    harness.set_model_name("kubeflow")
    return harness


def test_not_kubeflow_model():
    # Tests that unit will BlockStatus if deployed outside a model named kubeflow
    # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
    harness = Harness(Operator)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "kubeflow-dashboard must be deployed to model named `kubeflow`:"
        " https://git.io/J6d35"
    )


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_missing_image(harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "Missing resource: oci-image"
    )


def test_no_relation(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.begin_with_initial_hooks()

    assert harness.charm.model.unit.status == WaitingStatus(
        "Waiting for kubeflow-profiles relation data"
    )


@pytest.fixture(scope="function")
def charm_ingress_init(harness: Harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    rel_id = harness.add_relation("kubeflow-profiles", "app")
    harness.add_relation_unit(rel_id, "app/0")
    data = {"service-name": "service-name", "service-port": "6666"}
    harness.update_relation_data(
        rel_id,
        "app",
        {"_supported_versions": "- v1", "data": yaml.dump(data)},
    )
    return harness


def test_with_relation(charm_ingress_init: Harness):
    charm_ingress_init.begin_with_initial_hooks()
    _, k8s = charm_ingress_init.get_pod_spec()
    expected = yaml.safe_load(open("src/config.json"))
    got = yaml.safe_load(k8s["configMaps"]["centraldashboard-config"]["links"])
    assert got == expected
    assert isinstance(charm_ingress_init.charm.model.unit.status, ActiveStatus)


@pytest.mark.parametrize("sidebar_element", ["katib-ui", "tensorboards-web-app"])
def test_sidepanel_element_relation_joined(
    charm_ingress_init: Harness, sidebar_element: str
):
    rel_id = charm_ingress_init.add_relation("sidepanel", sidebar_element)
    charm_ingress_init.add_relation_unit(rel_id, f"{sidebar_element}/0")
    charm_ingress_init.begin_with_initial_hooks()
    _, k8s = charm_ingress_init.get_pod_spec()
    expected = yaml.safe_load(open("src/config.json"))
    extra_cfg = yaml.safe_load(open("src/extra_config.json"))
    expected["menuLinks"].append(extra_cfg[sidebar_element]["menuLink"])
    got = yaml.safe_load(k8s["configMaps"]["centraldashboard-config"]["links"])

    assert got == expected
    assert isinstance(charm_ingress_init.charm.model.unit.status, ActiveStatus)


@pytest.mark.parametrize("sidebar_element", ["katib-ui", "tensorboards-web-app"])
def test_sidepanel_element_relation_departed(
    charm_ingress_init: Harness, sidebar_element: str
):
    rel_id = charm_ingress_init.add_relation("sidepanel", sidebar_element)
    charm_ingress_init.add_relation_unit(rel_id, f"{sidebar_element}/0")
    charm_ingress_init.begin_with_initial_hooks()
    charm_ingress_init.remove_relation(rel_id)

    _, k8s = charm_ingress_init.get_pod_spec()
    expected = yaml.safe_load(open("src/config.json"))
    got = yaml.safe_load(k8s["configMaps"]["centraldashboard-config"]["links"])

    assert got == expected
    assert isinstance(charm_ingress_init.charm.model.unit.status, ActiveStatus)
