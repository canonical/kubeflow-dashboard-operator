import logging

from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.resources.core_v1 import ConfigMap


class ResourceHandler():
    def __init__(self, app_name: str, model_name: str) -> None:
        self.app_name = app_name
        self.model_name = model_name
        self.log = logging.getLogger(__name__)

        self.lightkube_client = Client(namespace=self.model_name, field_manager="lightkube")

    def get_configmap(self, name: str, namespace: str) -> ConfigMap:
        try:
            return self.lightkube_client.get(
                ConfigMap, name, namespace=namespace
            )
        except ApiError as e:
            self.log.info(f"get_configmap: {name} does no exist")
            raise e
