from common.json_model import JsonModel
from common.subscription.external_transport.base_message_formatter import BaseMessageFormatter


class JsonDataModel(BaseMessageFormatter):

    def format(self, data: JsonModel):
        return data.to_json_external_with_time_stamp()
