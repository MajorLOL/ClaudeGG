#!/usr/bin/env python3
"""A systemctl that is not one, for the tests of the agent: `is-active`, `start`, `stop` and `restart` of
one service, kept in a file (FAKE_SYSTEMCTL_STATE); every call is added to FAKE_SYSTEMCTL_LOG. With
FAKE_SYSTEMCTL_FAIL set, start/stop/restart fail the way sudo does without a rule."""

import os
import sys


def main(argv):
    state = os.environ.get("FAKE_SYSTEMCTL_STATE", "")
    log = os.environ.get("FAKE_SYSTEMCTL_LOG", "")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(argv) + "\n")
    action = argv[0] if argv else ""
    if action == "is-active":
        try:
            with open(state, "r", encoding="utf-8") as handle:
                print(handle.read().strip() or "inactive")
        except OSError:
            print("inactive")
        return 3 if not os.path.exists(state) else 0
    if action in ("start", "restart", "stop"):
        if os.environ.get("FAKE_SYSTEMCTL_FAIL"):
            sys.stderr.write("sudo: a password is required\n")
            return 1
        with open(state, "w", encoding="utf-8") as handle:
            handle.write("inactive\n" if action == "stop" else "active\n")
        return 0
    sys.stderr.write("fake systemctl: no such action: %s\n" % action)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
