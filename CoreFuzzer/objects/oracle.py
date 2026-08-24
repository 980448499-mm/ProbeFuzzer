"""Unified oracle entry: AMF (GMM) + SMF (PDU session) routing."""
from __future__ import annotations

from objects.oracle_amf import OracleAmf
from objects.oracle_smf import OracleSmf

# Backward-compatible alias used by FSM State objects
Oracle = OracleAmf

SM_SYMBOLS = frozenset(
    {
        "PDUSessionEstablishmentRequest",
        "PDUSessionAuthenticationComplete",
        "PDUSessionModificationRequest",
        "PDUSessionModificationComplete",
        "PDUSessionModificationCommandReject",
        "PDUSessionReleaseRequest",
        "PDUSessionReleaseComplete",
        "gsmStatus",
        "ulNasTransport",
    }
)


def component_for_send_type(send_type: str) -> str:
    if send_type in SM_SYMBOLS:
        return "smf"
    return "amf"


def query_component_violation(
    component: str,
    amf_oracle: OracleAmf,
    smf_oracle: OracleSmf,
    send_type: str,
    ret_type: str,
    sht: int,
    secmod: int,
    *,
    new_msg: str = None,
    wire_mode: bool = True,
    mm_registered: bool = False,
    sm_state=None,
) -> bool:
    if component == "smf":
        smf_oracle.set_mm_registered(mm_registered)
        if sm_state is not None:
            smf_oracle.decide_state(sm_state)
        return smf_oracle.query_message(
            send_type, ret_type, sht, secmod, new_msg=new_msg, wire_mode=wire_mode
        )
    return amf_oracle.query_message(
        send_type, ret_type, sht, secmod, new_msg=new_msg, wire_mode=wire_mode
    )
