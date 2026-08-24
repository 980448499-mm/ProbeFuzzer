"""AMF / GMM wire-faithful Φ oracle."""
from __future__ import annotations

try:
    from objects.wire_nas import (
        NORMAL_REJECTS,
        is_cn_interesting_response,
        normalize_wire_security,
    )
except ImportError:
    from wire_nas import (  # type: ignore
        NORMAL_REJECTS,
        is_cn_interesting_response,
        normalize_wire_security,
    )


class OracleAmf:
    def __init__(self) -> None:
        # I: Initial, N: No Security Context, S: Security Context,
        # R: Registered, D: Deregistered, O: Other
        self.state = "I"
        self.allowed_plaintext = [
            "registrationRequest",
            "deregistrationRequest",
            "securityModeReject",
            "authenticationRequest",
            "authenticationResponse",
            "authenticationFailure",
            "deregistrationAccept",
            "identityResponse",
            "gmmStatus",
            "ulNasTransport",
        ]

    def check_security(self, send_type: str, sht: int, secmod: int) -> bool:
        if sht < 5:
            if sht + 1 == secmod:
                return True
            if sht == 4 and secmod == 3 and send_type == "securityModeComplete":
                return True
        return False

    def decide_state(self, fsm_state) -> None:
        states = []
        if fsm_state.paths == []:
            self.state = "I"
            return
        for path in fsm_state.paths:
            states.append(self.find_state_rec(path, "I", 0))

        if states.count(states[0]) == len(states):
            self.state = states[0]
        else:
            self.state = "O"

    def decide_state_from_path(self, path) -> None:
        """Set ω from the path actually executed this iteration (not all FSM paths)."""
        if path is None or not getattr(path, "input_symbols", None):
            self.state = "I"
            return
        self.state = self.find_state_rec(path, "I", 0)

    def find_state_rec(self, path, state, index) -> str:
        size = len(path.input_symbols)
        if state == "I":
            for i in range(index, size):
                if (
                    "registrationRequest" in path.input_symbols[i]
                    and "deregistrationRequest" not in path.input_symbols[i]
                    and path.output_symbols[i] != "registrationReject"
                    and path.output_symbols[i] != "null_action"
                ):
                    state = self.find_state_rec(path, "N", i)
                    break
                elif (
                    "identityResponse" in path.input_symbols[i]
                    and path.output_symbols[i] == "authenticationRequest"
                ):
                    state = self.find_state_rec(path, "N", i)
                    break
                elif (
                    "serviceRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "serviceReject"
                ):
                    state = self.find_state_rec(path, "D", i)
                    break
        elif state == "N":
            for i in range(index, size):
                if (
                    i + 1 != size
                    and path.output_symbols[i] == "securityModeCommand"
                    and "securityModeComplete" in path.input_symbols[i + 1]
                ):
                    state = self.find_state_rec(path, "S", i + 1)
                    break
                elif (
                    "deregistrationRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "deregistrationAccept"
                ):
                    state = self.find_state_rec(path, "D", i)
                    break
                elif (
                    "serviceRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "serviceReject"
                ):
                    state = self.find_state_rec(path, "D", i)
                    break
        elif state == "S":
            for i in range(index, size):
                if (
                    i + 1 != size
                    and path.output_symbols[i] == "registrationAccept"
                    and "registrationComplete" in path.input_symbols[i + 1]
                ):
                    state = self.find_state_rec(path, "R", i + 1)
                    break
                elif (
                    "deregistrationRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "deregistrationAccept"
                ):
                    state = self.find_state_rec(path, "D", i)
                    break
                elif (
                    "serviceRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "serviceReject"
                ):
                    state = self.find_state_rec(path, "D", i)
                    break
        elif state == "R":
            for i in range(index, size):
                if (
                    "deregistrationRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "deregistrationAccept"
                ):
                    state = self.find_state_rec(path, "D", i)
                    break
                elif (
                    "serviceRequest" in path.input_symbols[i]
                    and path.output_symbols[i] == "serviceReject"
                ):
                    state = self.find_state_rec(path, "D", i)
                    break
                elif (
                    "registrationRequest" in path.input_symbols[i]
                    and "deregistrationRequest" not in path.input_symbols[i]
                    and path.output_symbols[i] != "null_action"
                ):
                    state = self.find_state_rec(path, "S", i)
                    break
                elif (
                    "identityResponse" in path.input_symbols[i]
                    and path.output_symbols[i] == "authenticationRequest"
                ):
                    state = self.find_state_rec(path, "S", i)
                    break
                elif (
                    i + 1 != size
                    and path.output_symbols[i] == "securityModeCommand"
                    and "securityModeComplete" in path.input_symbols[i + 1]
                ):
                    state = self.find_state_rec(path, "S", i + 1)
                    break
        elif state == "D":
            for i in range(index, size):
                if (
                    "registrationRequest" in path.input_symbols[i]
                    and "deregistrationRequest" not in path.input_symbols[i]
                ):
                    if path.output_symbols[i] == "registrationAccept":
                        state = self.find_state_rec(path, "R", i)
                        break
                    elif (
                        path.output_symbols[i] != "registrationReject"
                        and path.output_symbols[i] != "null_action"
                    ):
                        state = self.find_state_rec(path, "N", i)
                        break
                elif (
                    "identityResponse" in path.input_symbols[i]
                    and path.output_symbols[i] == "authenticationRequest"
                ):
                    state = self.find_state_rec(path, "N", i)
                    break
        return state

    def _state_gate_violation(self, send_type: str, ret_type: str, sht: int) -> bool:
        if self.state == "I":
            if sht == 0:
                if send_type == "registrationRequest":
                    return False
                if send_type == "deregistrationRequest":
                    return False
                if send_type == "serviceRequest" and ret_type == "serviceReject":
                    return False
                return True
            return True
        if self.state in ("N", "O"):
            if sht == 0 and send_type in self.allowed_plaintext:
                return False
            if sht == 4 and send_type == "securityModeComplete":
                return False
            return True
        if self.state == "S":
            if sht == 2:
                if send_type == "serviceRequest" and ret_type != "serviceReject":
                    return True
                return False
            if sht == 4 and send_type == "securityModeComplete":
                return False
            return True
        if self.state == "R":
            if sht == 2:
                return False
            if sht == 4 and send_type == "securityModeComplete":
                return False
            return True
        if self.state == "D":
            if sht == 0 or sht == 2:
                if send_type == "registrationRequest":
                    return False
                if send_type == "deregistrationRequest":
                    return False
                if send_type == "serviceRequest" and ret_type == "serviceReject":
                    return False
                return True
            return True
        raise Exception("OracleAmf: Invalid state!")

    def query_message_legacy(self, send_type: str, ret_type: str, sht: int, secmod: int) -> bool:
        if ret_type == "" or ret_type == "gmmStatus":
            return False
        if not self.check_security(send_type, sht, secmod):
            return True
        return self._state_gate_violation(send_type, ret_type, sht)

    def query_message(
        self,
        send_type: str,
        ret_type: str,
        sht: int,
        secmod: int,
        new_msg: str = None,
        wire_mode: bool = True,
    ) -> bool:
        if ret_type == "" or ret_type == "gmmStatus" or ret_type == "null_action":
            return False

        if not wire_mode:
            return self.query_message_legacy(send_type, ret_type, sht, secmod)

        wire_sht, _wire_sec, _meta = normalize_wire_security(new_msg, sht, secmod)

        if ret_type in NORMAL_REJECTS:
            return False

        if not is_cn_interesting_response(ret_type):
            return False

        # Common legitimate MM continuations that may be exchanged in PLAINTEXT
        # during the (re-)authentication flow. These are genuine continuations, so
        # the state gate's "plaintext in S/R is a violation" rule is too aggressive
        # for them and is suppressed here — but ONLY when actually plaintext
        # (wire_sht == 0). A protected form (sht != 0) of these messages in state
        # I/N is exactly the V4 security-context violation and must NOT be whitelisted.
        #
        # Intentionally NOT whitelisted (plaintext form is a real NAS security-context
        # enforcement violation per TS 24.501 §4.4.4.3, and the state gate already
        # accepts their protected form):
        #   - deregistrationRequest -> deregistrationAccept
        #   - securityModeComplete   -> registrationAccept
        #   - registrationComplete   -> configurationUpdateCommand
        if wire_sht == 0 and (send_type, ret_type) in (
            ("identityResponse", "configurationUpdateCommand"),
            ("identityResponse", "identityRequest"),
            ("identityResponse", "authenticationRequest"),
            ("authenticationFailure", "authenticationRequest"),
            ("authenticationFailure", "authenticationReject"),
            ("registrationRequest", "authenticationRequest"),
            ("registrationRequest", "identityRequest"),
            ("authenticationResponse", "securityModeCommand"),
        ):
            return False

        return self._state_gate_violation(send_type, ret_type, wire_sht)
