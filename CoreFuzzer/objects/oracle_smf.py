"""SMF / PDU session wire-faithful Φ oracle."""
from __future__ import annotations

try:
    from objects.wire_nas import (
        SM_CONTINUATION,
        SM_NORMAL_REJECTS,
        is_sm_cn_interesting_response,
        normalize_wire_security,
    )
except ImportError:
    from wire_nas import (  # type: ignore
        SM_CONTINUATION,
        SM_NORMAL_REJECTS,
        is_sm_cn_interesting_response,
        normalize_wire_security,
    )


class OracleSmf:
    """Session-level oracle: I idle, A active, R releasing, E error."""

    def __init__(self) -> None:
        self.session_state = "I"
        self.mm_registered = False

    def set_mm_registered(self, registered: bool) -> None:
        self.mm_registered = bool(registered)

    def decide_state(self, fsm_state) -> None:
        if fsm_state is None or fsm_state.paths == []:
            self.session_state = "I"
            return
        states = [self.find_state_rec(path, "I", 0) for path in fsm_state.paths]
        if states.count(states[0]) == len(states):
            self.session_state = states[0]
        else:
            self.session_state = "E"

    def decide_state_from_path(self, path) -> None:
        if path is None or not getattr(path, "input_symbols", None):
            self.session_state = "I"
            return
        self.session_state = self.find_state_rec(path, "I", 0)

    def find_state_rec(self, path, state, index) -> str:
        size = len(path.input_symbols)
        if state == "I":
            for i in range(index, size):
                if (
                    "PDUSessionEstablishmentRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "pduSessionEstablishmentAccept"
                ):
                    return self.find_state_rec(path, "A", i)
        elif state == "A":
            for i in range(index, size):
                if (
                    "PDUSessionReleaseRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "pduSessionReleaseCommand"
                ):
                    return self.find_state_rec(path, "R", i)
                if (
                    "PDUSessionReleaseComplete" in path.input_symbols[i]
                    and path.output_symbols[i] == "null_action"
                ):
                    return self.find_state_rec(path, "E", i)
                if (
                    "PDUSessionModificationCommandReject" in path.input_symbols[i]
                    and path.output_symbols[i] == "null_action"
                ):
                    return self.find_state_rec(path, "E", i)
        elif state == "R":
            for i in range(index, size):
                if path.output_symbols[i] == "null_action":
                    return self.find_state_rec(path, "I", i)
                if (
                    "PDUSessionEstablishmentRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "pduSessionEstablishmentAccept"
                ):
                    return self.find_state_rec(path, "A", i)
        elif state == "E":
            for i in range(index, size):
                if path.output_symbols[i] == "gmmStatus":
                    continue
                if (
                    "PDUSessionEstablishmentRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "pduSessionEstablishmentAccept"
                ):
                    return self.find_state_rec(path, "A", i)
        return state

    def _session_gate_violation(self, send_type: str, ret_type: str, sht: int) -> bool:
        if not self.mm_registered:
            if ret_type in SM_CONTINUATION:
                return True
            return False

        if self.session_state == "I":
            if send_type == "PDUSessionEstablishmentRequest":
                if ret_type == "pduSessionEstablishmentAccept":
                    return False
            # gmmStatus / null_action 在无会话时属正常拒绝
            if ret_type in ("gmmStatus", "null_action"):
                return False
            if ret_type in (
                "pduSessionEstablishmentAccept",
                "pduSessionModificationCommand",
                "pduSessionReleaseCommand",
            ):
                return True
            return False

        if self.session_state == "A":
            if send_type in (
                "PDUSessionModificationRequest",
                "PDUSessionModificationComplete",
                "PDUSessionModificationCommandReject",
                "PDUSessionReleaseRequest",
                "PDUSessionReleaseComplete",
                "PDUSessionEstablishmentRequest",
            ):
                if ret_type in SM_CONTINUATION or ret_type.endswith("Command"):
                    # V3: 会话 Active 时，网络自发释放（UE 未发 release request）
                    if ret_type == "pduSessionReleaseCommand" and send_type != "PDUSessionReleaseRequest":
                        return True
                    return False
            if ret_type in ("pduSessionEstablishmentAccept", "pduSessionModificationCommand"):
                return False
            if ret_type == "pduSessionReleaseCommand" and send_type != "PDUSessionReleaseRequest":
                return True
            return False

        if self.session_state in ("R", "E"):
            if ret_type in SM_CONTINUATION and ret_type != "gmmStatus":
                return True
            return False

        return False

    def query_message(
        self,
        send_type: str,
        ret_type: str,
        sht: int,
        secmod: int,
        new_msg: str = None,
        wire_mode: bool = True,
    ) -> bool:
        if ret_type == "" or ret_type == "null_action":
            return False

        if ret_type in SM_NORMAL_REJECTS:
            return False

        if not is_sm_cn_interesting_response(ret_type):
            return False

        wire_sht, _wire_sec, _meta = normalize_wire_security(new_msg, sht, secmod)
        # SM NAS is carried integrity-protected once MM context exists
        if self.mm_registered and wire_sht == 0 and send_type.startswith("PDUSession"):
            pass  # suspicious wire form, still evaluate CN continuation

        return self._session_gate_violation(send_type, ret_type, wire_sht)
