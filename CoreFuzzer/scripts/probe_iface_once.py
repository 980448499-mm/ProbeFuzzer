#!/usr/bin/env python3
"""One-shot check of N2-activate, PFCP modify, and same-assoc NGAP NAS."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from objects.iface_probes import (  # noqa: E402
    UPF_PFCP,
    classify_ngap,
    gsm_nas,
    live_pids,
    load_seed,
    n2_setup_rsp_transfer,
    ngap_reg_then_ul,
    pfcp_est_then_modify,
    sbi_create_sm_context,
    sbi_modify,
    sbi_modify_n2,
)


def main() -> None:
    print("live", {k: v for k, v in live_pids().items() if v})
    print("n2xfer", n2_setup_rsp_transfer().hex())
    r = sbi_create_sm_context()
    print("CREATE", r["status"], r.get("location"), (r.get("body") or "")[:120])
    loc = r.get("location") or ""
    if r["status"] == 201 and loc:
        import time as _t
        _t.sleep(1.5)
        murl = loc.rstrip("/") + "/modify"
        a = sbi_modify_n2(murl, n2_setup_rsp_transfer())
        print("N2ACT", a["status"], (a.get("body") or "")[:200])
        d = sbi_modify(murl, b'{"upCnxState":"DEACTIVATED"}')
        print("DEACT", d["status"], (d.get("body") or "")[:200])
        rel = sbi_modify(murl, b'{"release":true}')
        print("REL", rel["status"], (rel.get("body") or "")[:120])
    est = load_seed("pfcp/type_50_311.bin")
    mod = load_seed("pfcp/type_52_46.bin")
    a, s, m = pfcp_est_then_modify(est, mod, UPF_PFCP, 0xA50000AA)
    print("PFCP assoc", len(a), "t", a[1] if a else None)
    print("PFCP sess", len(s), "t", s[1] if s else None, s[:16].hex() if s else "")
    print("PFCP mod", len(m), "t", m[1] if m else None, m[:16].hex() if m else "")
    ini = load_seed("ngap/initial_ue.bin")
    ul = load_seed("ngap/ul_nas.bin")
    rxs, rxu, rxul = ngap_reg_then_ul(ini, ul)
    print("NGAP setup", classify_ngap(rxs))
    print("NGAP ue", classify_ngap(rxu), rxu[:20].hex() if rxu else "")
    print("NGAP ul", classify_ngap(rxul), rxul[:20].hex() if rxul else "")


if __name__ == "__main__":
    main()
