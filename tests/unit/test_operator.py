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
    harness.begin()
    assert harness.charm.model.unit.status == BlockedStatus(
        "kubeflow-dashboard must be deployed to model named `kubeflow`:"
        " https://git.io/J6d35"
    )


def test_not_leader(harness):
    harness.begin()
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


def test_with_relation(harness):
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
    harness.begin_with_initial_hooks()

    _, k8s = harness.get_pod_spec()
    expected = yaml.safe_load(open("src/config.json"))
    got = yaml.safe_load(k8s["configMaps"]["centraldashboard-config"]["links"])
    assert got == expected
    assert isinstance(harness.charm.model.unit.status, ActiveStatus)
