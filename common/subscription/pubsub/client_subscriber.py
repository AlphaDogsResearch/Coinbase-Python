import zmq

class Subscriber:
    def __init__(self, addresses: list[str], topic_filter: str = "", name: str = "Subscriber"):
        self.name = name
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)

        for addr in addresses:
            self.socket.connect(addr)
            print(f"[{self.name}] Connected to {addr}")

        self.socket.setsockopt_string(zmq.SUBSCRIBE, topic_filter)
        print(f"[{self.name}] Subscribed with filter: '{topic_filter}'")

    def listen(self, callback=None):
        print(f"[{self.name}] Listening for messages...")
        while True:
            msg = self.socket.recv_pyobj()
            if callback:
                callback(msg)
            else:
                print(f"[{self.name}] Received -> {msg}")

    def close(self):
        self.socket.close()
        self.context.term()
        print(f"[{self.name}] Closed subscriber.")
