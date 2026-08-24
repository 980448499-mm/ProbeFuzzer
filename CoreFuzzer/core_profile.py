"""Core-network profile abstraction.

Lets the same ProbeFuzzer code run against Open5GS, free5GC, or OAI by
parameterizing process/container names, AMF address, start/stop commands, FSM
paths, and state-cleanup behavior. Select a profile via the CORE env var
(defaults to ``open5gs``):

    CORE=free5gc python3 core_fuzzer_dueling.py sample.yaml
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

PROFILE_DIR = Path(__file__).resolve().parent / "core_profiles"


@dataclass
class CoreProfile:
    name: str
    deployment: str                      # "native" | "docker"
    processes: Dict[str, str]            # role -> process/container name
    amf_ngap_host: str
    amf_ngap_port: int
    log_paths: Dict[str, str]            # role -> log file (relative to CoreFuzzer)
    start_cmd: List[str]                 # full argv to start the core
    kill_cmd: List[str]                  # full argv to stop the core
    fsm_path: str
    fsm_sm_path: str
    mongodb_cleanup: bool = False
    ue_config: str = "open5gs-ue.yaml"
    gnb_config: str = "open5gs-gnb.yaml"
    ue_port: int = 45678
    imsi_base: int = 999700000000001
    env: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, name: str) -> "CoreProfile":
        path = PROFILE_DIR / f"{name}.yaml"
        if not path.exists():
            raise ValueError(f"unknown core profile: {name} (missing {path})")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**data)

    def proc(self, role: str) -> str:
        return self.processes.get(role, "")

    def log_path(self, role: str) -> Optional[str]:
        return self.log_paths.get(role)

    def resolve(self, cmd: List[str]) -> List[str]:
        """Expand {VAR} placeholders in a command from the environment."""
        out = []
        for tok in cmd:
            out.append(tok.format(**os.environ))
        return out

    def resolved_start_cmd(self) -> List[str]:
        return self.resolve(self.start_cmd)

    def resolved_kill_cmd(self) -> List[str]:
        return self.resolve(self.kill_cmd)

    def resolved_log_path(self, role: str = "core") -> Optional[str]:
        p = self.log_path(role)
        if not p:
            return None
        return p.format(**os.environ)


def current_profile() -> CoreProfile:
    import os
    name = os.getenv("CORE", "open5gs").strip().lower()
    return CoreProfile.load(name)
