#!/usr/bin/env python3
"""Minimal reproduction for the ProbeFuzzer semantic oracle (Phi).

Validates that Phi fires on a NAS security-context enforcement bypass and stays
silent on legitimate flows. This is the Phi-side half of the Path-1 experiment;
the Open5GS-side half is the fault injection in ``open5gs/src/amf/gmm-sm.c``
gated by OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST.

The clean, unambiguous violation is a plaintext (sht=0) SERVICE REQUEST after a
security context is established: per 3GPP TS 24.501 §4.4.4.3 a service request
has no "initial message" exception, so it must always be integrity-protected.
A plaintext REGISTRATION REQUEST with 5GS registration type "initial" is NOT a
violation (it is the legitimate re-registration flow), so Phi must not flag the
re-authentication it triggers.

Run from the CoreFuzzer directory:

    python3 repro_phi_violation.py

No Open5GS/UERANSIM required: this exercises the oracle directly.
"""
from __future__ import annotations

from objects.oracle_amf import OracleAmf


def check(o: OracleAmf, state: str, send: str, ret: str, sht: int, secmod: int,
          new_msg: str) -> bool:
    o.state = state
    return o.query_message(send, ret, sht, secmod, new_msg=new_msg, wire_mode=True)


def main() -> None:
    o = OracleAmf()

    # Wire sht comes from the hex header (7E 00 -> sht=0 plaintext, 7E 02 -> sht=2).
    plain_reg = "7E004179000D0199F9070000000000000000741001002E04F0F0F0F02F020101700000530100"
    plain_svc = "7E004C000007F40040C00003535002B67E"
    protected_svc = "7E024C000007F40040C00003535002B67E"

    cases = [
        # (label, state, send_type, ret_type, sht, secmod, new_msg, expect)
        # --- service request: the clean, unambiguous bypass surface ---
        ("bypass: plaintext service request accepted (R, svc->svcAccept)", "R",
         "serviceRequest", "serviceAccept", 0, 2, plain_svc, True),
        ("correct reject: plaintext service request (R, svc->svcReject)", "R",
         "serviceRequest", "serviceReject", 0, 2, plain_svc, False),
        ("legitimate protected service request (R, svc->svcAccept, sht=2)", "R",
         "serviceRequest", "serviceAccept", 2, 2, protected_svc, False),
        # --- registration request ---
        ("legitimate re-auth: plaintext INITIAL registration (R, reg->authReq)", "R",
         "registrationRequest", "authenticationRequest", 0, 2, plain_reg, False),
        ("bypass: plaintext registration completed w/o re-auth (R, reg->regAccept)", "R",
         "registrationRequest", "registrationAccept", 0, 2, plain_reg, True),
        ("legitimate initial registration (I, reg->authReq, sht=0)", "I",
         "registrationRequest", "authenticationRequest", 0, 1, plain_reg, False),
    ]

    print("=" * 72)
    print("Phi oracle reproduction — NAS security-context enforcement")
    print("=" * 72)
    ok = True
    for label, state, send, ret, sht, secmod, new_msg, expect in cases:
        got = check(o, state, send, ret, sht, secmod, new_msg)
        status = "OK " if got == expect else "FAIL"
        if got != expect:
            ok = False
        print(f"[{status}] {label}")
        print(f"       state={state} send={send} ret={ret} sht={sht} secmod={secmod}"
              f" -> Phi={got} (expected {expect})")

    print("=" * 72)
    print("ALL PASS" if ok else "SOME CASES FAILED")
    print("=" * 72)

    if ok:
        print("""
Interpretation
--------------
Phi flags the two unambiguous bypasses (plaintext service request accepted, and
plaintext registration completed without re-authentication) and stays silent on
the legitimate flows, including the plaintext INITIAL registration that triggers
a normal re-authentication. This is the oracle-side evidence for a real PV_Phi.

End-to-end reproduction (requires built Open5GS + UERANSIM):
  1. Rebuild Open5GS with the fault injection in gmm-sm.c (already patched).
  2. Start the AMF with the service-request fault enabled:
        OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST=1 ./install/bin/open5gs-amfd
  3. Run the fuzzer with bypass seeds:
        cd CoreFuzzer && python3 core_fuzzer_dueling.py sample.yaml
     RUN_BYPASS_SEEDS defaults to true, so plain_svc_after_sec is sent whenever
     the oracle state is S/R.
  4. Observe fuzzing_stats['violations'] increment and wire_phi_hits.csv /
     phi_violations_*.csv record the deduplicated PV_Phi entries.
""")


if __name__ == "__main__":
    main()
