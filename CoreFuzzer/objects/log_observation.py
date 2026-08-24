"""Infer CN downlink NAS types from Open5GS / UERANSIM logs when UE JSON is empty."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

from objects.wire_nas import _CN_DOWNLINK_PREFERENCE, parse_nas_message_types_from_hex

# Uplink MM/SM types — not valid CN downlink ret_type
_UPLINK_TYPES = frozenset(
    {
        "registrationRequest",
        "registrationComplete",
        "deregistrationRequest",
        "serviceRequest",
        "authenticationResponse",
        "authenticationFailure",
        "identityResponse",
        "securityModeComplete",
        "securityModeReject",
        "ulNasTransport",
        "pduSessionEstablishmentRequest",
        "pduSessionModificationRequest",
        "pduSessionReleaseRequest",
    }
)

# Standalone camelCase lines in ue.log (state_learner notify_response output)
_KNOWN_RET_TYPES = frozenset(_CN_DOWNLINK_PREFERENCE) | frozenset(
    {
        "registrationReject",
        "authenticationReject",
        "serviceReject",
        "securityModeReject",
        "null_action",
    }
)

# UERANSIM debug/warning lines -> fuzzer ret_type symbol
_UE_LOG_PATTERNS = [
    (re.compile(r"Authentication Request received", re.I), "authenticationRequest"),
    (re.compile(r"Authentication Reject received", re.I), "authenticationReject"),
    (re.compile(r"Identity request received", re.I), "identityRequest"),
    (re.compile(r"Security Mode Command received", re.I), "securityModeCommand"),
    (re.compile(r"Registration accept received", re.I), "registrationAccept"),
    (re.compile(r"Registration reject received", re.I), "registrationReject"),
    (re.compile(r"Service reject received", re.I), "serviceReject"),
    (re.compile(r"Service accept received", re.I), "serviceAccept"),
    (re.compile(r"Configuration update command received", re.I), "configurationUpdateCommand"),
    (re.compile(r"Deregistration accept received", re.I), "deregistrationAccept"),
    (re.compile(r"receiveAuthenticationRequest", re.I), "authenticationRequest"),
    (re.compile(r"receiveIdentityRequest", re.I), "identityRequest"),
    (re.compile(r"receiveSecurityModeCommand", re.I), "securityModeCommand"),
    (re.compile(r"receiveRegistrationAccept", re.I), "registrationAccept"),
    (re.compile(r"receiveRegistrationReject", re.I), "registrationReject"),
    (re.compile(r"receiveAuthenticationReject", re.I), "authenticationReject"),
    (re.compile(r"receiveServiceReject", re.I), "serviceReject"),
    (re.compile(r"receiveServiceAccept", re.I), "serviceAccept"),
    (re.compile(r"receiveConfigurationUpdate", re.I), "configurationUpdateCommand"),
    (re.compile(r"receiveDeregistrationAccept", re.I), "deregistrationAccept"),
]

# Open5GS core.log — only explicit rejects (continuation types from core.log are too noisy)
_CORE_LOG_PATTERNS = [
    (re.compile(r"NAS MAC verification failed", re.I), "gmmStatus"),
    (re.compile(r"\[gmm\].*Registration reject", re.I), "registrationReject"),
    (re.compile(r"\[gmm\].*Authentication reject", re.I), "authenticationReject"),
    (re.compile(r"\[gmm\].*Service reject", re.I), "serviceReject"),
]

_HEX_IN_LOG = re.compile(r"\b([0-9A-Fa-f]{8,})\b")


class LogObserver:
    """Track log offsets and infer downlink ret_type after each fuzz send."""

    def __init__(
        self,
        ue_log: Path = Path("logs/ue.log"),
        core_log: Path = Path("logs/core.log"),
    ) -> None:
        self.ue_log = ue_log
        self.core_log = core_log
        self._ue_off = 0
        self._core_off = 0
        self._sync_offsets()

    def _file_size(self, path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _sync_offsets(self) -> None:
        self._ue_off = self._file_size(self.ue_log)
        self._core_off = self._file_size(self.core_log)

    def mark(self) -> Tuple[int, int]:
        self._ue_off = self._file_size(self.ue_log)
        self._core_off = self._file_size(self.core_log)
        return self._ue_off, self._core_off

    def _read_since(self, path: Path, offset: int) -> str:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                return f.read()
        except OSError:
            return ""

    def infer_downlink_ret_type(
        self,
        ue_off: Optional[int] = None,
        core_off: Optional[int] = None,
        include_core_log: bool = False,
    ) -> Tuple[str, str]:
        """
        Returns (ret_type, source) where source is ue_log|core_log|core_hex|"".
        Prefers CN downlink continuation types over rejects when multiple seen.
        core_log / core_hex are opt-in (diagnostics only); L1/oracle use ue paths only.
        """
        ue_chunk = self._read_since(self.ue_log, ue_off if ue_off is not None else self._ue_off)
        core_chunk = self._read_since(self.core_log, core_off if core_off is not None else self._core_off)

        ue_hits = _scan_ue_log(ue_chunk)
        if ue_hits:
            return _pick_best(ue_hits), "ue_log"

        if not include_core_log:
            return "", ""

        core_hits = _scan_core_log(core_chunk)
        if core_hits:
            return _pick_best(core_hits), "core_log"

        for hx in _HEX_IN_LOG.findall(core_chunk):
            names = [n for n in parse_nas_message_types_from_hex(hx) if n not in _UPLINK_TYPES]
            picked = _pick_best(names)
            if picked:
                return picked, "core_hex"

        return "", ""


def _scan_ue_log(chunk: str) -> list:
    found: list = []
    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped in _KNOWN_RET_TYPES:
            found.append(stripped)
        for pat, name in _UE_LOG_PATTERNS:
            if pat.search(line):
                found.append(name)
    return found


def _scan_core_log(chunk: str) -> list:
    found: list = []
    for line in chunk.splitlines():
        for pat, name in _CORE_LOG_PATTERNS:
            if pat.search(line):
                found.append(name)
    return found


def _pick_best(names: list) -> str:
    if not names:
        return ""
    downlink = [n for n in names if n not in _UPLINK_TYPES]
    if not downlink:
        return ""
    for preferred in _CN_DOWNLINK_PREFERENCE:
        if preferred in downlink:
            return preferred
    for n in reversed(downlink):
        if n not in ("null_action", "gmmStatus"):
            return n
    return downlink[-1]


def resolve_ret_type_with_logs(
    ret_type: Optional[str],
    ret_msg: Optional[str] = None,
    observer: Optional[LogObserver] = None,
    ue_off: Optional[int] = None,
    core_off: Optional[int] = None,
    include_core_log: bool = False,
) -> Tuple[str, str]:
    """Merge UE JSON, ret_msg hex, and log inference. Returns (ret_type, source)."""
    from objects.wire_nas import resolve_ret_type

    if ret_type and str(ret_type).strip():
        return str(ret_type).strip(), "ue_json"
    wired = resolve_ret_type(ret_type, ret_msg)
    if wired and wired not in _UPLINK_TYPES:
        return wired, "ret_msg_hex"
    if observer is not None:
        inferred, src = observer.infer_downlink_ret_type(
            ue_off, core_off, include_core_log=include_core_log
        )
        if inferred:
            return inferred, src
    return "", ""
