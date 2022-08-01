# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
from ops.model import BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KubeflowDashboardOperator


@pytest.fixture
def harness():
    harness = Harness(KubeflowDashboardOperator)
    # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
    harness.set_model_name("kubeflow")
    return harness


@patch("charm.KubernetesServicePatch", lambda x, y: None)
def test_not_leader(harness: Harness):
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, WaitingStatus)
    assert (
        "status_set",
        "waiting",
        "Waiting for leadership",
        {"is_app": False},
    ) in harness._get_backend_calls()


@patch("charm.KubernetesServicePatch", lambda x, y: None)
def test_not_kubeflow_model():
    # Tests that unit will BlockStatus if deployed outside a model named kubeflow
    # Remove when this bug is resolved: https://github.com/kubeflow/kubeflow/issues/6136
    harness = Harness(KubeflowDashboardOperator)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "kubeflow-dashboard must be deployed to model named `kubeflow`:"
        " https://git.io/J6d35"
    )
