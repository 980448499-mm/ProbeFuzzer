#!/usr/bin/env python3
"""
改进的崩溃检测模块
修复P0问题：崩溃检测假阳性

功能：
1. 进程监控：检查AMF/SMF进程是否真的崩溃
2. 分类检测：区分真实崩溃、正常拒绝、网络超时
3. 崩溃验证：保存崩溃输入，支持重放验证
"""

import subprocess
import time
import os
import json
from typing import Tuple, Optional, Dict
from enum import Enum
from datetime import datetime

class CrashType(Enum):
    """崩溃类型枚举（对齐论文 tab:probe 的 Ψ 分流类别）"""
    REAL_CRASH = "real_crash"          # G1: 进程终止 + 崩溃日志
    TIMEOUT = "timeout"                 # G3: 进程活着 + N 轮无有效响应
    NORMAL_REJECT = "normal_reject"     # G2a: 标准拒绝
    TRANSIENT = "transient"             # G2b: 非拒绝但有效 continuation
    NETWORK_ERROR = "network_error"     # G4: 探针无法连接/反复失败
    UNKNOWN = "unknown"                 # 未知情况

class CrashDetector:
    """
    崩溃检测器
    改进版本：区分真实崩溃和假阳性
    """
    
    def __init__(self, crash_log_dir: str = "./crash_reports",
                 amf_proc: str = "open5gs-amfd", smf_proc: str = "open5gs-smfd",
                 deployment: str = "native"):
        """
        初始化崩溃检测器

        Args:
            crash_log_dir: 崩溃报告存储目录
            amf_proc: AMF 进程名（native）或容器名（docker）
            smf_proc: SMF 进程名（native）或容器名（docker）
            deployment: "native" 或 "docker"
        """
        self.crash_log_dir = crash_log_dir
        self.crash_reports = []  # 存储崩溃报告
        self.crash_count = 0     # 崩溃计数
        self.deployment = deployment
        self.amf_proc = amf_proc
        self.smf_proc = smf_proc
        # 日志来源：docker 部署读容器日志，native 读文件
        if self.deployment == "docker":
            self._default_amf_log = self.amf_proc
            self._default_smf_log = self.smf_proc
        else:
            self._default_amf_log = "./logs/core.log"
            self._default_smf_log = "./logs/core.log"

        # 创建崩溃报告目录
        os.makedirs(crash_log_dir, exist_ok=True)
        os.makedirs(os.path.join(crash_log_dir, "confirmed"), exist_ok=True)
        os.makedirs(os.path.join(crash_log_dir, "false_positives"), exist_ok=True)

        # 记录进程初始状态
        self.amf_pids_before = self._get_process_pids(self.amf_proc)
        self.smf_pids_before = self._get_process_pids(self.smf_proc)

    def _get_process_pids(self, process_name: str) -> list:
        """
        获取进程/容器 ID 列表

        native: 返回进程 PID 列表；docker: 运行中返回 [container_name]，否则 []。
        """
        if self.deployment == "docker":
            try:
                result = subprocess.run(
                    ["docker", "ps", "--filter", f"name={process_name}",
                     "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=3)
                names = [n for n in result.stdout.split() if n == process_name]
                return names
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return []
        try:
            result = subprocess.run(
                ["pgrep", "-f", process_name],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                pids = []
                for pid_str in result.stdout.strip().split("\n"):
                    if not pid_str:
                        continue
                    pid = int(pid_str)
                    # 排除僵尸进程（defunct）：僵尸仍出现在进程表里，pgrep -f 会
                    # 匹配到它们，但它们已终止。若不排除，残留僵尸会让
                    # _is_process_alive 误判 AMF 仍存活（G3 而非 G1）。
                    try:
                        with open(f"/proc/{pid}/stat") as f:
                            if f.read().split()[2] == "Z":
                                continue
                    except Exception:
                        pass
                    pids.append(pid)
                return pids
            return []
        except (subprocess.TimeoutExpired, ValueError):
            return []
    
    def _is_process_alive(self, process_name: str, expected_pids: Optional[list] = None) -> Tuple[bool, list]:
        """
        检查进程是否存活
        
        Args:
            process_name: 进程名称
            expected_pids: 期望的PID列表（可选）
            
        Returns:
            (是否存活, 当前PID列表)
        """
        current_pids = self._get_process_pids(process_name)
        
        if expected_pids:
            # 如果提供了期望的PID，检查是否还在运行
            alive = any(pid in current_pids for pid in expected_pids)
        else:
            # 如果没有提供，只要有同名进程就算存活
            alive = len(current_pids) > 0
        
        return alive, current_pids
    
    def _read_log_tail(self, log_source: str) -> str:
        """读取日志尾部：docker 部署读 `docker logs`，native 读文件。"""
        if self.deployment == "docker":
            try:
                r = subprocess.run(
                    ["docker", "logs", "--tail", "300", log_source],
                    capture_output=True, text=True, timeout=6)
                return (r.stdout or "") + (r.stderr or "")
            except Exception:
                return ""
        if not os.path.exists(log_source):
            return ""
        try:
            with open(log_source, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return ""

    def _check_logs_for_crash(self, log_file: str, timeout_seconds: int = 5) -> Tuple[bool, str]:
        """
        检查日志中是否有崩溃信息（docker 部署读容器日志，native 读文件）

        Args:
            log_file: 日志文件路径（native）或容器名（docker）
            timeout_seconds: 超时时间

        Returns:
            (是否有崩溃, 崩溃信息)
        """
        log_content = self._read_log_tail(log_file)
        if not log_content:
            return False, ""

        try:
            last_lines = log_content.strip().split("\n")[-50:]
            log_joined = "\n".join(last_lines)

            # 崩溃关键词（Open5GS/C 的 FATAL/Assertion/SIGABRT + free5GC/Go 的 panic/fatal error/SIGSEGV）
            crash_keywords = [
                "Segmentation fault",
                "SIGSEGV",
                "SIGABRT",
                "core dumped",
                "Assertion",
                "FATAL",
                "fatal error",
                "panic",
                "abort",
                "terminated",
                "crash"
            ]

            for keyword in crash_keywords:
                if keyword.lower() in log_joined.lower():
                    for line in reversed(last_lines):
                        if keyword.lower() in line.lower():
                            return True, line.strip()

            return False, ""
        except Exception as e:
            return False, f"日志读取错误: {e}"
    
    def detect_amf_crash(self, probe_fn, log_file: Optional[str] = None,
                         n_rounds: int = 3) -> Tuple[bool, CrashType, Dict]:
        """
        论文 O₁ 探针（对齐 §5.1 三层模型 + tab:probe 的 Ψ 分流）。

        Args:
            probe_fn: 无参函数，返回一次 NAS 探针的响应字符串；
                      连接失败返回 "connect_failed"，超时/无响应返回 ""。
            log_file: core 日志路径（native）或容器名（docker）；None 用部署默认值。
            n_rounds: L2 探针轮数（论文 AMF 取 3）。

        Returns:
            (是否需报告, 崩溃类型, 详细信息)
        """
        if log_file is None:
            log_file = self._default_amf_log
        info = {
            "timestamp": datetime.now().isoformat(),
            "response": "",
            "crash_type": None,
            "amf_pids_before": self.amf_pids_before.copy(),
            "amf_pids_after": [],
            "log_evidence": "",
            "is_confirmed": False
        }

        # ---- L1: Process and Log Layer ----
        amf_alive, amf_pids_after = self._is_process_alive(self.amf_proc, self.amf_pids_before)
        info["amf_pids_after"] = amf_pids_after

        # G1: 进程终止 + 崩溃日志
        if not amf_alive:
            has_crash_log, log_evidence = self._check_logs_for_crash(log_file)
            info["log_evidence"] = log_evidence
            info["is_confirmed"] = has_crash_log
            if has_crash_log:
                info["crash_type"] = CrashType.REAL_CRASH.value
                return True, CrashType.REAL_CRASH, info
            # 进程终止但无崩溃日志（正常关闭），非 REAL_CRASH
            info["crash_type"] = CrashType.UNKNOWN.value
            return False, CrashType.UNKNOWN, info

        # ---- L2: NAS Service Probe Layer（N 轮 + 1s backoff）----
        responses = []
        for _ in range(n_rounds):
            try:
                out = probe_fn()
            except Exception:
                out = "connect_failed"
            responses.append(out if out else "")
            # 有效 NAS 响应：非空、非 null_action、非 connect_failed
            if responses[-1] not in ("", "null_action", "connect_failed"):
                break
            time.sleep(1.0)  # backoff

        last = responses[-1]
        info["response"] = last

        # ---- L3: Decision Fusion Layer（Ψ）----
        # G4: 探针始终无法连接
        if responses and all(r == "connect_failed" for r in responses):
            info["crash_type"] = CrashType.NETWORK_ERROR.value
            return False, CrashType.NETWORK_ERROR, info

        # G3: 进程活着 + N 轮无有效响应
        if last in ("", "null_action"):
            info["crash_type"] = CrashType.TIMEOUT.value
            return True, CrashType.TIMEOUT, info

        # G2a: 标准拒绝（*Reject 消息）
        reject_messages = [
            "registrationReject",
            "authenticationReject",
            "serviceReject",
            "securityModeReject",
            "pduSessionEstablishmentReject",
            "pduSessionModificationReject",
            "pduSessionReleaseReject",
        ]
        if last in reject_messages:
            info["crash_type"] = CrashType.NORMAL_REJECT.value
            return False, CrashType.NORMAL_REJECT, info

        # G2b: 非拒绝但有效 continuation
        info["crash_type"] = CrashType.TRANSIENT.value
        return False, CrashType.TRANSIENT, info
    
    def detect_smf_crash(self, response_sequence: list, log_file: Optional[str] = None) -> Tuple[bool, CrashType, Dict]:
        """
        检测SMF是否崩溃（改进版 - 更准确的超时检测）

        【修复】改进超时检测逻辑，区分真实崩溃和超时

        Args:
            response_sequence: 响应消息序列
            log_file: 日志文件路径（native）或容器名（docker）；None 用部署默认值。

        Returns:
            (是否崩溃, 崩溃类型, 详细信息)
        """
        if log_file is None:
            log_file = self._default_smf_log
        info = {
            "timestamp": datetime.now().isoformat(),
            "response_sequence": response_sequence,
            "crash_type": None,
            "smf_pids_before": self.smf_pids_before.copy(),
            "smf_pids_after": [],
            "log_evidence": "",
            "is_confirmed": False
        }
        
        # 检查进程状态
        smf_alive, smf_pids_after = self._is_process_alive(self.smf_proc, self.smf_pids_before)
        info["smf_pids_after"] = smf_pids_after
        
        # 情况1: 进程不存在 -> 真实崩溃
        if not smf_alive:
            has_crash_log, log_evidence = self._check_logs_for_crash(log_file)
            info["log_evidence"] = log_evidence
            info["is_confirmed"] = has_crash_log
            
            if has_crash_log:
                info["crash_type"] = CrashType.REAL_CRASH.value
                return True, CrashType.REAL_CRASH, info
            else:
                # 进程不存在但无日志，可能是正常关闭或其他原因
                info["crash_type"] = CrashType.UNKNOWN.value
                return False, CrashType.UNKNOWN, info
        
        # 【修复】情况2: 响应序列为空或全部为null_action -> 超时
        if not response_sequence or all(resp in ["null_action", "", None] for resp in response_sequence):
            info["crash_type"] = CrashType.TIMEOUT.value
            info["is_confirmed"] = False  # 超时需要进一步验证
            return True, CrashType.TIMEOUT, info
        
        # 【修复】情况3: 响应序列不完整且最后几个都是null_action -> 超时
        if len(response_sequence) > 0:
            # 检查最后几个响应是否都是null_action
            last_responses = response_sequence[-min(3, len(response_sequence)):]
            if all(resp in ["null_action", "", None] for resp in last_responses):
                info["crash_type"] = CrashType.TIMEOUT.value
                info["is_confirmed"] = False
                return True, CrashType.TIMEOUT, info
        
        # 情况4: 响应不匹配但进程还在 -> 不是崩溃，可能是协议违规
        expected_sequence = [
            "authenticationRequest",
            "securityModeCommand",
            "registrationAccept",
            "configurationUpdateCommand",
            "pduSessionEstablishmentAccept"
        ]
        
        if len(response_sequence) > 0:
            # 如果响应序列完整但内容不匹配，可能是协议违规，不是崩溃
            if len(response_sequence) >= len(expected_sequence):
                info["crash_type"] = CrashType.UNKNOWN.value
                return False, CrashType.UNKNOWN, info
        
        # 情况5: 响应序列不完整 -> 可能是超时（但需要确认进程还在）
        if len(response_sequence) < len(expected_sequence):
            # 如果进程还在，但响应不完整，可能是超时
            if smf_alive:
                info["crash_type"] = CrashType.TIMEOUT.value
                info["is_confirmed"] = False
                return True, CrashType.TIMEOUT, info
            else:
                # 进程不在且响应不完整，可能是崩溃
                info["crash_type"] = CrashType.UNKNOWN.value
                return False, CrashType.UNKNOWN, info
        
        # 一切正常
        return False, CrashType.UNKNOWN, info
    
    def save_crash_report(self, crash_info: Dict, input_data: Dict, crash_type: CrashType):
        """
        保存崩溃报告
        
        Args:
            crash_info: 崩溃信息
            input_data: 输入数据（用于重放）
            crash_type: 崩溃类型
        """
        self.crash_count += 1
        report = {
            "crash_id": self.crash_count,
            "crash_info": crash_info,
            "input_data": input_data,
            "crash_type": crash_type.value,
            "timestamp": datetime.now().isoformat()
        }
        
        # 根据类型分类存储
        if crash_type == CrashType.REAL_CRASH or crash_type == CrashType.TIMEOUT:
            report_dir = os.path.join(self.crash_log_dir, "confirmed")
        else:
            report_dir = os.path.join(self.crash_log_dir, "false_positives")
        
        report_file = os.path.join(report_dir, f"crash_{self.crash_count:04d}.json")
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.crash_reports.append(report)
        
        print(f"    📄 崩溃报告已保存: {report_file}")
        print(f"    📊 崩溃类型: {crash_type.value}")
    
    def get_statistics(self) -> Dict:
        """
        获取崩溃统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            "total_crashes": self.crash_count,
            "confirmed_crashes": 0,
            "false_positives": 0,
            "timeouts": 0,
            "real_crashes": 0
        }
        
        for report in self.crash_reports:
            crash_type = report.get("crash_type", "unknown")
            if crash_type == CrashType.REAL_CRASH.value:
                stats["real_crashes"] += 1
                stats["confirmed_crashes"] += 1
            elif crash_type == CrashType.TIMEOUT.value:
                stats["timeouts"] += 1
                stats["confirmed_crashes"] += 1
            else:
                stats["false_positives"] += 1
        
        return stats

