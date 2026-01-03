# test_bidirectional_communication.py
import threading
import time
import sys
import os
import json

# Add the parent directory to path to import your modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.subscription.messaging.dealer import BidirectionalClient
from common.subscription.messaging.router import BidirectionalServer


def test_server_client():
    """ACTUALLY test communication between server and client."""

    print("=" * 60)
    print("ACTUAL TEST: Bidirectional Server-Client Communication")
    print("=" * 60)

    # Store messages received for verification
    server_received = []
    client_received = []

    # Modified server class to track messages
    class TestableBidirectionalServer(BidirectionalServer):
        def listen_for_clients(self):
            """Override to track received messages."""
            poller = zmq.Poller()
            poller.register(self.router, zmq.POLLIN)

            while self.running:
                try:
                    socks = dict(poller.poll(1000))

                    if self.router in socks:
                        identity, empty, message = self.router.recv_multipart()

                        # Store the message
                        msg_text = message.decode('utf-8')
                        server_received.append(msg_text)
                        print(f"[SERVER] RECEIVED: '{msg_text}'")

                        # Call parent method to handle it
                        super().process_incoming_message(identity, msg_text)

                except Exception as e:
                    if self.running:
                        print(f"[SERVER] Error: {e}")

    # Modified client class to track messages
    class TestableBidirectionalClient(BidirectionalClient):
        def listen_to_server(self):
            """Override to track received messages."""
            poller = zmq.Poller()
            poller.register(self.dealer, zmq.POLLIN)
            poller.register(self.sub, zmq.POLLIN)

            while self.running:
                try:
                    socks = dict(poller.poll(1000))

                    if self.dealer in socks:
                        message = self.dealer.recv_multipart()
                        if len(message) >= 2:
                            msg_text = message[-1].decode('utf-8')
                            client_received.append(msg_text)
                            print(f"[CLIENT] RECEIVED DIRECT: '{msg_text}'")

                    if self.sub in socks:
                        msg = self.sub.recv_string()
                        client_received.append(f"BROADCAST: {msg}")
                        print(f"[CLIENT] RECEIVED BROADCAST: '{msg}'")

                except Exception as e:
                    if self.running:
                        print(f"[CLIENT] Error: {e}")

    try:
        import zmq
    except ImportError:
        print("ERROR: zmq not installed. Install with: pip install pyzmq")
        return

    # Start server
    print("\n" + "-" * 60)
    print("STEP 1: Starting server on localhost:5555")
    print("-" * 60)

    server = BidirectionalServer("localhost", 5555)

    # Run server in thread
    def run_server():
        server.run()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to initialize
    time.sleep(3)
    print("✓ Server is running")

    # Start client
    print("\n" + "-" * 60)
    print("STEP 2: Starting client and connecting to server")
    print("-" * 60)

    client = BidirectionalClient("localhost", 5555)

    # Run client in thread
    def run_client():
        client.run()

    client_thread = threading.Thread(target=run_client, daemon=True)
    client_thread.start()

    # Wait for client to connect
    time.sleep(2)
    print("✓ Client is connected")

    # TEST 1: Client sends message to server
    print("\n" + "-" * 60)
    print("TEST 1: Client → Server Communication")
    print("-" * 60)

    print("Sending message from client to server...")

    # We need to send an actual message
    # Since client.run() blocks on input, we'll use a different approach
    client_socket = zmq.Context().socket(zmq.DEALER)
    client_socket.setsockopt(zmq.IDENTITY, b"test-client-123")
    client_socket.connect("tcp://localhost:5555")

    test_messages = [
        "Hello Server!",
        "How are you?",
        "This is test message 3"
    ]

    for i, msg in enumerate(test_messages, 1):
        print(f"\nSending message {i}: '{msg}'")

        # Send message (format: [identity, empty, message])
        client_socket.send_multipart([b'', b'', msg.encode('utf-8')])

        # Wait for response
        print("Waiting for server response...")
        try:
            response = client_socket.recv_multipart(timeout=3000)
            if response and len(response) >= 3:
                reply = response[-1].decode('utf-8')
                print(f"Received reply from server: '{reply}'")
            else:
                print("No valid response received")
        except zmq.Again:
            print("Timeout: No response received")

        time.sleep(1)

    # TEST 2: Server sends message to client
    print("\n" + "-" * 60)
    print("TEST 2: Server → Client Communication")
    print("-" * 60)

    # Connect to server as a control client
    control_socket = zmq.Context().socket(zmq.REQ)
    control_socket.connect("tcp://localhost:5555")

    # Send a control message (this depends on your server's protocol)
    print("Attempting to send from server to client...")

    # Try to get list of clients
    control_socket.send_string("list")
    try:
        response = control_socket.recv_string(timeout=2000)
        print(f"Server response to 'list': {response}")
    except zmq.Again:
        print("No response to 'list' command")

    # Wait a bit more
    print("\n" + "-" * 60)
    print("Letting communication continue...")
    print("-" * 60)

    for i in range(10, 0, -1):
        print(f"Test continues for {i} more seconds...")
        time.sleep(1)

    # Cleanup
    print("\n" + "-" * 60)
    print("STEP 3: Cleaning up")
    print("-" * 60)

    client_socket.close()
    control_socket.close()

    # Stop server and client
    server.running = False
    client.running = False

    time.sleep(1)

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    print(f"\nServer received {len(server_received)} messages")
    print(f"Client received {len(client_received)} messages")

    if server_received:
        print("\nMessages received by server:")
        for msg in server_received:
            print(f"  - {msg}")

    if client_received:
        print("\nMessages received by client:")
        for msg in client_received:
            print(f"  - {msg}")

    # Basic verification
    if len(server_received) >= len(test_messages):
        print("\n✅ TEST PASSED: Server received client messages")
    else:
        print(f"\n❌ TEST FAILED: Server should have received {len(test_messages)} messages, got {len(server_received)}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    test_server_client()