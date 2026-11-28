#!/usr/bin/env python3
"""Small test client for claudegg-wiiu-bridge.

Examples (run on any PC in the same network as the Pi):
  python bridge_client.py <pi-ip> STATUS
  python bridge_client.py <pi-ip> SYNC SHDC          # symbols shown by the Wii U
  python bridge_client.py <pi-ip> CONNECT --wait
  python bridge_client.py <pi-ip> press A
  python bridge_client.py <pi-ip> tap 427 240        # touch the middle of the screen
  python bridge_client.py <pi-ip> record gamepad.h264 10   # 10 seconds of GamePad video

Play the video live with: ffplay -f h264 tcp://<pi-ip>:51201
"""

import socket
import sys
import time

CMD_PORT = 51200
VIDEO_PORT = 51201


class Bridge:
    def __init__(self, host, port=CMD_PORT):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.file = self.sock.makefile("r", encoding="ascii", newline="\n")
        hello = self.file.readline().strip()
        if not hello.startswith("HELLO"):
            raise RuntimeError(f"unexpected greeting: {hello!r}")

    def command(self, line):
        """Send one command and return its OK/ERR reply. EVENT lines are printed."""
        self.sock.sendall((line + "\n").encode("ascii"))
        while True:
            reply = self.file.readline()
            if not reply:
                raise RuntimeError("bridge closed the connection")
            reply = reply.strip()
            if reply.startswith("EVENT"):
                print(reply)
                continue
            return reply

    def wait_event(self, timeout):
        self.sock.settimeout(timeout)
        try:
            line = self.file.readline().strip()
        except socket.timeout:
            return None
        finally:
            self.sock.settimeout(10)
        return line or None

    def press(self, button, hold=0.1):
        self.command(f"BTN {button} 1")
        time.sleep(hold)
        self.command(f"BTN {button} 0")

    def tap(self, x, y, hold=0.1):
        self.command(f"TOUCH {x} {y}")
        time.sleep(hold)
        self.command("TOUCH OFF")


def record(host, path, seconds):
    with socket.create_connection((host, VIDEO_PORT), timeout=10) as s, open(path, "wb") as f:
        end = time.time() + seconds
        total = 0
        while time.time() < end:
            data = s.recv(65536)
            if not data:
                break
            f.write(data)
            total += len(data)
    print(f"wrote {total} bytes to {path}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    host, action, args = sys.argv[1], sys.argv[2], sys.argv[3:]

    if action == "record":
        record(host, args[0] if args else "gamepad.h264", float(args[1]) if len(args) > 1 else 10)
        return 0

    bridge = Bridge(host)
    if action == "press":
        bridge.press(args[0].upper(), float(args[1]) if len(args) > 1 else 0.1)
        print("OK")
    elif action == "tap":
        bridge.tap(int(args[0]), int(args[1]))
        print("OK")
    else:
        wait = "--wait" in args
        args = [a for a in args if a != "--wait"]
        print(bridge.command(" ".join([action] + args)))
        if wait:
            # SYNC and CONNECT report their result later as an EVENT line.
            event = bridge.wait_event(60)
            print(event or "no event within 60 s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
