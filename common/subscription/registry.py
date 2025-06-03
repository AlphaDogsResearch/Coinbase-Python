from common.seriallization import Serializable


class Registry(Serializable):
    def __init__(self):
        self.registered = set()

    def register(self, identity):
        self.registered.add(identity)

    def unregister(self, identity):
        self.registered.discard(identity)

    def get_all(self):
        return list(self.registered)

class Register(Serializable):
    def __init__(self, identity):
        self.identity = identity

class Unregister(Serializable):
    def __init__(self, identity):
        self.identity = identity

class Ack(Serializable):
    def __init__(self, status):
        self.status = status