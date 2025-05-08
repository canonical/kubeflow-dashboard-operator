"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="latest/edge", trust=True)
