import logging
from datetime import datetime
import uuid


# A class to generate unique identifier of an order
class IdGenerator:
    def __init__(self, prefix: str):
        if len(prefix) > 4:
            raise ValueError("prefix cannot be more than 4 characters long")
        self._prefix = prefix

    def get_prefix(self) -> str:
        return self._prefix

    def next(self) -> str:
        random_id = uuid.uuid4().hex
        generated_id = self._prefix + str(random_id)
        logging.info(f"Generated order id: {generated_id}")
        return generated_id

    def match(self, client_id: str) -> bool:
        if client_id:
            return client_id.startswith(self._prefix)
        return False


if __name__ == '__main__':
    id_generator = IdGenerator('algo')
    for i in range(100):
        identifier = id_generator.next()
        print(identifier)
