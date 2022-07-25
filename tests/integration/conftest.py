# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from collections import defaultdict
import urllib.request

import pytest
from _pytest.config.argparsing import Parser
import yaml


def pytest_addoption(parser: Parser):
    parser.addoption(
        "--version-bundle-uri",
        help="A uri to a charm bundle.yaml file that defines reference charm versions to be used "
        "during this test.  Typically used to dynamically define the versions of the external"
        " dependencies used during integration tests.  This can be an internet url, such as "
        "a link to a github raw file, or a local file using file:./some/relative/file. "
        "If any required charms are omitted, or if this option is omitted entirely, charms "
        "will be deployed from the CharmHub default track.",
    )


@pytest.fixture(scope="session")
def dependency_version_map(request) -> defaultdict:
    """Yields a defaultdict of {charm_name: charm_channel} according to a loaded bundle file.

    For any undefined charm_name, the defaultdict returns None, which will map a charm deploy to
    the stable risk of the charm's default channel in CharmHub
    """

    # The default value returned if not set in the bundle is None, which means we use the stable
    # risk of the charm's default channel in CharmHub
    version_map = defaultdict(lambda: None)

    bundle_uri = request.config.option.version_bundle_uri

    if bundle_uri is not None:
        bundle = fetch_bundle(bundle_uri)
        # Note: A bundle could in theory use multiple versions of the same charm, named differently.
        #       eg: spark-old pulls from ch:spark/old/latest, and spark-new pulls from
        #       ch:spark/new/latest.  We ignore this here and just take the last channel used for a
        #       given charm.
        for application in bundle["applications"].values():
            version_map[application["charm"]] = application["channel"]

    yield version_map


def fetch_bundle(uri: str, max_characters: int = 50000) -> dict:
    """Fetch a bundle.yaml from an uri

    Args:
        uri (str): uri to fetch bundle from.  Can be https://, file:./some/file (relative),
                   file:///some/file (absolute), etc.
        max_characters (int): Maximum number of characters loaded from the uri (to prevent
                              accidentally loading something enormous)

    Returns: a rendered bundle.yaml file as a dict
    """
    data_stream = urllib.request.urlopen(uri).read(max_characters)
    return yaml.safe_load(data_stream)
