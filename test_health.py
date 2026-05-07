#!/usr/bin/env python3
"""
Health check for deliverx: runs an actual send/receive cycle through every
combination of enabled tunnel provider and URL shortener, and reports which
combinations are working.

Usage:
    ./test_health.py                       # every enabled combo
    ./test_health.py -k serveo             # only combos whose name matches
    python -m unittest test_health         # standard unittest invocation

Each test spawns a real `deliverx send` subprocess (constrained to one
tunnel + one shortener via DELIVERX_ONLY_TUNNEL / DELIVERX_ONLY_SHORTENER),
parses the printed Public URL and Passphrase, then drives `deliverx receive`
through stdin and verifies the file came back byte-for-byte.

Tests hit live public services, so expect each combo to take ~30 seconds.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT_DIR  = Path(__file__).resolve().parent
DELIVERX    = SCRIPT_DIR / "deliverx.py"
ANSI_RE     = re.compile(r"\033\[[0-9;]*m")
URL_RE      = re.compile(r"Public URL\s*:\s*(\S+)")
PASS_RE     = re.compile(r"Passphrase\s*:\s*(\S+)")

PER_COMBO_TIMEOUT = 90  # seconds


def _discover_enabled() -> tuple[list[str], list[str]]:
    """Parse deliverx.py to find currently-enabled (uncommented) tunnel and
    shortener entries. Walks the source so users who comment a provider out
    don't get a failing test for it."""
    src = DELIVERX.read_text().splitlines()

    def block_lines(start_marker: str) -> list[str]:
        out, depth, started = [], 0, False
        for line in src:
            if start_marker in line:
                started = True
                depth = line.count("[") - line.count("]")
                continue
            if not started:
                continue
            depth += line.count("[") - line.count("]")
            out.append(line)
            if depth <= 0:
                break
        return out

    tunnel_block    = block_lines("TUNNEL_PROVIDERS = [")
    shortener_block = block_lines("URL_SHORTENERS = [")

    tunnels = []
    for line in tunnel_block:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        m = re.search(r'"name":\s*"([^"]+)"', stripped)
        if m:
            tunnels.append(m.group(1))

    shorteners = []
    for line in shortener_block:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        m = re.match(r'\("([^"]+)"\s*,', stripped)
        if m:
            shorteners.append(m.group(1))

    return tunnels, shorteners


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _run_combo(tunnel: str, shortener: str, port: int) -> tuple[bool, str]:
    """Execute one full send + receive cycle. Returns (ok, message)."""
    payload = (f"deliverx-health-{tunnel}-{shortener}-{time.time()}\n".encode()
               * 50)

    with tempfile.TemporaryDirectory() as send_root, \
         tempfile.TemporaryDirectory() as recv_root:
        send_dir, recv_dir = Path(send_root), Path(recv_root)
        test_file = send_dir / "deliverx_health.bin"
        test_file.write_bytes(payload)

        env = {
            **os.environ,
            "DELIVERX_ONLY_TUNNEL":    tunnel,
            "DELIVERX_ONLY_SHORTENER": shortener,
        }

        sender = subprocess.Popen(
            [sys.executable, str(DELIVERX), "send", str(test_file),
             "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        url, passphrase = None, None
        captured: list[str] = []
        deadline = time.time() + PER_COMBO_TIMEOUT
        try:
            while time.time() < deadline and not (url and passphrase):
                line = sender.stdout.readline()
                if not line:
                    if sender.poll() is not None:
                        break
                    time.sleep(0.05)
                    continue
                clean = ANSI_RE.sub("", line)
                captured.append(clean)
                if not url:
                    m = URL_RE.search(clean)
                    if m:
                        url = m.group(1)
                if not passphrase:
                    m = PASS_RE.search(clean)
                    if m:
                        passphrase = m.group(1)
        except Exception as e:
            _kill(sender)
            return False, f"sender stdout read error: {e}\n{''.join(captured)}"

        if not url or not passphrase:
            _kill(sender)
            return False, ("did not see URL/passphrase on sender stdout\n"
                           + "".join(captured))

        # Drive the receiver: URL, passphrase, save dir, "y" to confirm
        # single-file download. A trailing newline keeps input() happy if
        # the receiver asks anything else.
        receiver_input = f"{url}\n{passphrase}\n{recv_dir}\ny\n"
        try:
            recv = subprocess.run(
                [sys.executable, str(DELIVERX), "receive"],
                input=receiver_input,
                capture_output=True,
                text=True,
                timeout=PER_COMBO_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            _kill(sender)
            return False, "receiver timed out"

        # Sender should auto-shut down after its idle grace; give it a beat.
        try:
            sender.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _kill(sender)

        downloaded = recv_dir / test_file.name
        if not downloaded.exists():
            return False, ("receiver did not save file.\n"
                           f"--- receiver stdout ---\n{recv.stdout}\n"
                           f"--- receiver stderr ---\n{recv.stderr}")
        if downloaded.read_bytes() != payload:
            return False, "downloaded bytes did not match payload"

    return True, ""


# Allocate a non-overlapping port per combination so concurrent runs (e.g.
# parallel pytest workers) don't collide. The ports are in the ephemeral
# range; conflicts are still possible but very unlikely.
_BASE_PORT = 18443


class DeliverxHealth(unittest.TestCase):
    """Generated dynamically below — see add_combination_tests()."""
    pass


def _make_test(tunnel: str, shortener: str, port: int):
    def runner(self: unittest.TestCase):
        ok, msg = _run_combo(tunnel, shortener, port)
        if not ok:
            self.fail(f"[{tunnel}] x [{shortener}] FAILED: {msg}")
    runner.__doc__ = f"send/receive over {tunnel} via {shortener}"
    return runner


def _add_combination_tests() -> int:
    tunnels, shorteners = _discover_enabled()
    if not tunnels:
        raise RuntimeError("No tunnel providers enabled in deliverx.py")
    if not shorteners:
        raise RuntimeError("No URL shorteners enabled in deliverx.py")

    count = 0
    for ti, tunnel in enumerate(tunnels):
        for si, shortener in enumerate(shorteners):
            safe_t = re.sub(r"\W+", "_", tunnel)
            safe_s = re.sub(r"\W+", "_", shortener)
            method_name = f"test_{safe_t}__{safe_s}"
            port = _BASE_PORT + ti * 32 + si
            setattr(DeliverxHealth, method_name,
                    _make_test(tunnel, shortener, port))
            count += 1
    return count


_add_combination_tests()


if __name__ == "__main__":
    unittest.main(verbosity=2)
