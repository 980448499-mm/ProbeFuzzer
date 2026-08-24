#!/usr/bin/env python3
"""Apply ProbeFuzzer lab tweaks to a meson-generated Open5GS sample.yaml."""
from __future__ import annotations

import sys
from pathlib import Path


def patch(text: str) -> str:
    for key in ("no_mme", "no_sgwc", "no_sgwu", "no_pcrf", "no_hss"):
        text = text.replace(f"#    {key}: true", f"    {key}: true")
        text = text.replace(f"#      {key}: true", f"      {key}: true")
    text = text.replace(
        "    ciphering_order : [ NEA0, NEA1, NEA2 ]",
        "    ciphering_order : [ NEA2, NEA1, NEA0 ]",
    )
    text = text.replace(
        """  session:
    - subnet: 10.45.0.0/16
      gateway: 10.45.0.1
    - subnet: 2001:db8:cafe::/48
      gateway: 2001:db8:cafe::1
""",
        """  session:
    - subnet: 10.45.0.0/16
      gateway: 10.45.0.1
#    - subnet: 2001:db8:cafe::/48
#      gateway: 2001:db8:cafe::1
""",
    )
    return text


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: patch_open5gs_lab_sample.py <sample.yaml>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text()), encoding="utf-8")
    print(f"patched {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
