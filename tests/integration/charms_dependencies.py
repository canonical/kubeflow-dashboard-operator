"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="1.10/stable", trust=True)
