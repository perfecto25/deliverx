#!/usr/bin/env python3
"""Render the authentication-flow sequence diagram to docs/auth_flow.png.

Re-run whenever the flow changes. Output is committed alongside the source
so README.md can reference it without requiring a Mermaid renderer.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.patches as patches
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "auth_flow.png"

PARTICIPANTS = [
    ("Receiver",            "#FFE2E2"),
    ("Shortener",           "#FFF1CC"),
    ("Tunnel host",         "#D7ECFF"),
    ("Sender (HTTP server)", "#D6F3DD"),
]

# (from_idx, to_idx, label, dashed)
MESSAGES = [
    (0, 1, "GET /<short-id>",                   False),
    (1, 0, "301 Location: tunnel URL",          True),
    (0, 2, "GET /unlock?passphrase=...",        False),
    (2, 3, "forward",                           False),
    (3, 2, "302 Location: /?t=TOKEN",           True),
    (2, 0, "302",                               True),
    (0, 2, "GET /?t=TOKEN  (or /browse/...)",   False),
    (2, 3, "forward",                           False),
    (3, 0, "streamed file",                     True),
]

NOTE = "stream ends → completed++   idle 5s → auto-shutdown"


def main() -> None:
    n           = len(PARTICIPANTS)
    col_spacing = 4.0
    top         = 1.0
    msg_step    = 1.0
    bottom      = top - msg_step * (len(MESSAGES) + 2)

    fig_w = 2 + col_spacing * (n - 1) + 2
    fig_h = 1.4 + msg_step * (len(MESSAGES) + 2)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    ax.set_xlim(-1, col_spacing * (n - 1) + 1)
    ax.set_ylim(bottom - 0.6, top + 1.2)
    ax.set_axis_off()

    xs = [i * col_spacing for i in range(n)]

    # Participant boxes (top + bottom) and lifelines.
    for x, (name, color) in zip(xs, PARTICIPANTS):
        for y in (top + 0.5, bottom):
            box = patches.FancyBboxPatch(
                (x - 1.2, y - 0.25), 2.4, 0.5,
                boxstyle="round,pad=0.02",
                linewidth=1.2,
                edgecolor="#333",
                facecolor=color,
            )
            ax.add_patch(box)
            ax.text(x, y, name, ha="center", va="center",
                    fontsize=10, fontweight="bold")
        ax.plot([x, x], [top + 0.25, bottom + 0.25],
                color="#888", linewidth=1, linestyle=(0, (3, 3)))

    # Messages.
    for i, (a, b, label, dashed) in enumerate(MESSAGES):
        y = top - msg_step * (i + 1)
        x_a, x_b = xs[a], xs[b]
        style = "dashed" if dashed else "solid"
        ax.annotate(
            "",
            xy=(x_b, y), xytext=(x_a, y),
            arrowprops=dict(
                arrowstyle="->",
                linestyle=style,
                linewidth=1.4,
                color="#222",
                shrinkA=2, shrinkB=2,
            ),
        )
        # Label centered above the arrow line.
        x_mid = (x_a + x_b) / 2
        ax.text(x_mid, y + 0.14, label, ha="center", va="bottom",
                fontsize=9, color="#222")

    # Note over Sender.
    note_y    = bottom + 0.4
    note_x    = xs[-1]
    note_w    = 4.4
    note_box  = patches.FancyBboxPatch(
        (note_x - note_w / 2, note_y - 0.3), note_w, 0.6,
        boxstyle="round,pad=0.04",
        linewidth=1,
        edgecolor="#888",
        facecolor="#FFF8DC",
    )
    ax.add_patch(note_box)
    ax.text(note_x, note_y, NOTE, ha="center", va="center",
            fontsize=8.5, style="italic", color="#444")

    plt.title("deliverx — receiver authentication flow",
              fontsize=12, pad=14)
    plt.tight_layout()
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
