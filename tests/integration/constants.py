# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""Constants module including constants used in tests."""
from pathlib import Path

import yaml

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
IMAGE_PATH = METADATA["resources"]["oci-image"]["upstream-source"]
CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
CONFIGMAP_NAME = CONFIG["options"]["dashboard-configmap"]["default"]
KUBEFLOW_PROFILES = "kubeflow-profiles"
KUBEFLOW_PROFILES_CHANNEL = "1.8/stable"
KUBEFLOW_PROFILES_TRUST = True

DASHBOARD_LINKS_REQUIRER_TESTER_CHARM = Path(
    "tests/integration/dashboard_links_requirer_tester_charm"
).absolute()
TESTER_CHARM_NAME = "kubeflow-dashboard-requirer-tester"

DEFAULT_DOCUMENTATION_TEXTS = [
    "Getting started with Charmed Kubeflow",
    "Microk8s for Kubeflow",
    "Requirements for Kubeflow",
]
