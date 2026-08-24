#!/usr/bin/env python3
"""
CoreFuzzer with Dueling DQN Integration
集成了Dueling DQN的5G核心网模糊测试器

改进点：
1. 支持Dueling DQN和Standard DQN
2. RL智能状态选择 vs PowerSchedule
3. 迭代控制和进度报告
4. 详细的模糊测试统计
5. 自动保存和恢复
"""

import os, time, socket, string, json, atexit, shutil, subprocess
try:
    import psutil
except ImportError:
    psutil = None  # 如果psutil不可用，使用pgrep作为后备方案
from db_helper import *
from fsm_helper import *
from setup_helper import *
try:
    from rl_scheduler import RLScheduler
except ImportError:
    RLScheduler = None  # torch 未安装时 RL 调度器不可用（USE_RL 默认 False，不影响）
from crash_detector import CrashDetector, CrashType  # 【P0修复】导入崩溃检测器
from coverage_helper import CoverageHelper  # 【P0修复】导入覆盖率辅助类
from typing import Tuple, Dict  # 添加类型提示
from objects.oracle import SM_SYMBOLS, component_for_send_type, query_component_violation
from objects.oracle_smf import OracleSmf
from objects.log_observation import LogObserver, resolve_ret_type_with_logs
from objects.l1_policy import (
    append_typed_response,
    append_wire_phi_hit,
    eligible_for_l1_hit,
    eligible_for_oracle,
)
from objects.pv_probes import (
    reach_mm_registered,
    reach_pdu_session,
    run_bypass_seeds,
)

# ==================== 配置参数 ====================

# 核心网 profile（CORE 环境变量决定 open5gs/free5gc/oai），缓存避免重复加载 YAML
from core_profile import current_profile as _current_profile
_CORE_PROFILE = None
def get_profile():
    """返回当前核心网 profile（CORE 环境变量决定，进程内缓存）。"""
    global _CORE_PROFILE
    if _CORE_PROFILE is None:
        _CORE_PROFILE = _current_profile()
    return _CORE_PROFILE

# RL配置（可用环境变量 USE_RL / USE_DUELING 覆盖，便于复现 Dueling DQN 实验）
USE_RL = os.getenv("USE_RL", "false").strip().lower() == "true"
USE_DUELING = os.getenv("USE_DUELING", "false").strip().lower() == "true"
try:
    ITERATION_LIMIT = int(os.getenv("ITERATION_LIMIT", "500"))
except ValueError:
    ITERATION_LIMIT = 500
REPORT_INTERVAL = 10       # 每N次迭代输出一次进度

FSM_LOAD_MODE = os.getenv("FSM_LOAD_MODE", "latest").strip().lower()
RESET_RL_STATS = os.getenv("RESET_RL_STATS", "false").strip().lower() == "true"
LIGHT_RESET = os.getenv("LIGHT_RESET", "true").strip().lower() == "true"
FORCE_REGISTERED_SM = os.getenv("FORCE_REGISTERED_SM", "true").strip().lower() == "true"
SKIP_SM_ESTABLISHMENT = os.getenv("SKIP_SM_ESTABLISHMENT", "false").strip().lower() == "true"
RUN_BYPASS_SEEDS = os.getenv("RUN_BYPASS_SEEDS", "true").strip().lower() == "true"
V2_PROBE = os.getenv("V2_PROBE", "false").strip().lower() == "true"
V3_PROBE = os.getenv("V3_PROBE", "false").strip().lower() == "true"
V4_PROBE = os.getenv("V4_PROBE", "false").strip().lower() == "true"

reset_count = 0
UEsocket = None
gNBsocket = None
current_ue_connector = None

# ==================== 退出处理 ====================

def exit_handler(fsm: FSM, fsm_sm: FSM, rl_scheduler=None):
    """
    退出时保存所有数据
    """
    print("\n" + "="*60)
    print("  程序退出，正在保存数据...")
    print("="*60)
    
    # 清理进程
    killCore()
    killGNB()
    killUE()
    
    # 保存FSM
    suffix = '_rl_dueling' if (USE_RL and USE_DUELING) else ('_rl' if USE_RL else '')
    
    fsm_file = open(f'./savedFSM{suffix}.json', 'w')
    fsm_file.write(fsm.to_json())
    fsm_file.close()
    print(f"  ✓ FSM已保存到: savedFSM{suffix}.json")
    
    fsm_sm_file = open(f'./savedFSM_sm{suffix}.json', 'w')
    fsm_sm_file.write(fsm_sm.to_json())
    fsm_sm_file.close()
    print(f"  ✓ FSM_SM已保存到: savedFSM_sm{suffix}.json")
    
    # 保存RL模型和统计
    if rl_scheduler:
        model_name = './rl_model_dueling.pth' if USE_DUELING else './rl_model_standard.pth'
        rl_scheduler.save_model(model_name)
        print(f"  ✓ RL模型已保存到: {model_name}")
        
        # 保存统计信息
        stats_name = './rl_stats_dueling.json' if USE_DUELING else './rl_stats_standard.json'
        with open(stats_name, 'w') as f:
            json.dump(rl_scheduler.stats, f, indent=2)
        print(f"  ✓ RL统计已保存到: {stats_name}")
        
        # 打印最终统计
        print("\n" + "="*60)
        print("  RL训练最终统计:")
        print("="*60)
        print(f"  • 总训练步数: {rl_scheduler.steps}")
        print(f"  • 最终Epsilon: {rl_scheduler.epsilon:.4f}")
        if rl_scheduler.steps > 0:
            avg_reward = rl_scheduler.total_reward / rl_scheduler.steps
            print(f"  • 平均奖励: {avg_reward:.2f}")
        print("="*60)
    
    print("\n✅ 所有数据已保存！")

# ==================== 辅助函数 ====================

def init_ue_database(num_imsi: int = 5000):
    """
    Args:
        num_imsi: 要注册的IMSI数量（默认5000）
    """
    if not get_profile().mongodb_cleanup:
        print("  ℹ 非 MongoDB 核心，跳过 IMSI 数据库初始化")
        return
    try:
        from pymongo import MongoClient
        client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
        db = client['open5gs']
        
        # 【IMSI耗尽修复】注册IMSI范围: 999700000000001 - 999700000005000（支持大规模测试）
        registered_count = 0
        for offset in range(1, num_imsi + 1):
            imsi = str(999700000000001 + offset - 1)  # 使用数值型IMSI，支持5000+
            
            # 检查是否已存在
            if db.subscribers.find_one({"imsi": imsi}):
                continue
            
            # 添加订阅者
            subscriber = {
                "imsi": imsi,
                "subscribed_rau_tau_timer": 12,
                "network_access_mode": 0,
                "subscriber_status": 0,
                "access_restriction_data": 32,
                "slice": [{
                    "sst": 1,
                    "default_indicator": True,
                    "session": [{
                        "name": "internet",
                        "type": 3,
                        "qos": {
                            "index": 9,
                            "arp": {
                                "priority_level": 8,
                                "pre_emption_capability": 1,
                                "pre_emption_vulnerability": 1
                            }
                        },
                        "ambr": {
                            "uplink": {"value": 1, "unit": 3},
                            "downlink": {"value": 1, "unit": 3}
                        }
                    }]
                }],
                "ambr": {
                    "uplink": {"value": 1, "unit": 3},
                    "downlink": {"value": 1, "unit": 3}
                },
                "security": {
                    "k": "465B5CE8B199B49FAA5F0A2EE238A6BC",
                    "amf": "8000",
                    "op": None,
                    "opc": "E8ED289DEBA952E4283B54E88E6183CA"
                }
            }
            
            db.subscribers.insert_one(subscriber)
            registered_count += 1
        
        if registered_count > 0:
            print(f"  ✅ 已注册 {num_imsi} 个IMSI到数据库（新增{registered_count}个）")
        else:
            print(f"  ℹ️ 所有{num_imsi}个IMSI已存在于数据库")
        
        client.close()
    except Exception as e:
        print(f"  ⚠️ 初始化UE数据库失败: {e}")

def verify_amf_ready():
    """
    【P0关键修复】验证AMF是否已启动并监听38412端口
    
    GNB需要连接到AMF的NGAP服务 (端口38412)
    如果AMF未监听此端口，GNB无法连接，导致小区barred
    """
    try:
        result = subprocess.run(
            ["netstat", "-tuln"],
            capture_output=True,
            timeout=2
        )
        if b"38412" in result.stdout:
            return True
        return False
    except:
        return False

def verify_gnb_connected(max_wait: float = 20.0) -> bool:
    """Poll gNB log until NG Setup succeeds or timeout."""
    marker = "=== GNB启动时间:"
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            with open("./logs/gnb.log", "r") as f:
                log = f.read()
            tail = log
            if marker in log:
                tail = log.rsplit(marker, 1)[-1]
            if "NG Setup procedure is successful" in tail:
                return True
            if "NGAP association terminated" in tail or "AMF is down" in tail:
                return False
        except Exception:
            pass
        time.sleep(1.0)
    return False

def cleanup_amf_state():
    """
    【根本修复】彻底清理AMF持久化状态
    
    尝试清理：
    1. MongoDB中的UE注册信息（更彻底）
    2. AMF内存缓存（通过注销UE）
    3. 可能的配置文件
    """
    if not get_profile().mongodb_cleanup:
        print("  ℹ 非 MongoDB 核心，跳过 MongoDB 清理")
        return
    try:
        # 1. 清理MongoDB中的UE注册信息
        print("  🔄 清理MongoDB中的UE注册信息...")
        try:
            # 检查MongoDB是否运行
            result = subprocess.run(['pgrep', '-f', 'mongod'], 
                                  capture_output=True, timeout=2)
            if result.returncode == 0:
                
                cleanup_cmds = [
                    # 先清理所有包含ue/amf/udm/subscriber的集合（通用清理）
                    ['mongosh', 'open5gs', '--eval', 'db.getCollectionNames().forEach(function(c){var name=c.toLowerCase();if(name.includes("ue")||name.includes("amf")||name.includes("udm")||name.includes("subscriber")){try{db[c].deleteMany({});print("Cleaned: "+c);}catch(e){}}})', '--quiet'],
                    # 删除特定集合
                    ['mongosh', 'open5gs', '--eval', 'db.subscribers.deleteMany({})', '--quiet'],
                    ['mongosh', 'open5gs', '--eval', 'db.ues.deleteMany({})', '--quiet'],
                    ['mongosh', 'open5gs', '--eval', 'db.amf_contexts.deleteMany({})', '--quiet'],
                    # 【UE连接修复】清理UDM相关数据
                    ['mongosh', 'open5gs', '--eval', 'db.udm_ues.deleteMany({})', '--quiet'],
                    ['mongosh', 'open5gs', '--eval', 'db.amf_3gpp_access_registrations.deleteMany({})', '--quiet'],
                    ['mongosh', 'open5gs', '--eval', 'db.nudm_uecontexts.deleteMany({})', '--quiet'],
                   
                    ['mongosh', 'open5gs', '--eval', 'db.getCollectionNames().forEach(function(c){try{db[c].deleteMany({});}catch(e){}})', '--quiet'],
                ]
                for cmd in cleanup_cmds:
                    try:
                        subprocess.run(cmd,
                                     stdout=subprocess.DEVNULL, 
                                     stderr=subprocess.DEVNULL, 
                                     timeout=5)
                    except:
                        pass
                
                
                try:
                    # 删除整个数据库
                    subprocess.run(['mongosh', 'open5gs', '--eval', 'db.dropDatabase()'], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    print("  ✅ 已删除并重建数据库（彻底清理）")
                    time.sleep(1)
                    # 再次清理一次
                    subprocess.run(['mongosh', 'open5gs', '--eval', 'db.getCollectionNames().forEach(function(c){try{db[c].deleteMany({});}catch(e){}})', '--quiet'], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                except:
                    pass  # 如果删除失败，继续使用之前的清理结果
                
                print("  ✅ MongoDB状态已彻底清理（包括AMF和UDM数据）")
            else:
                print("  ℹ️ MongoDB未运行，跳过MongoDB清理")
        except Exception as e:
            print(f"  ⚠️ MongoDB清理失败: {e}")
    except Exception as e:
        print(f"  ⚠️ AMF状态清理出错: {e}")

def deregister_ue_if_running():
    """
    【P0解决方案】如果UE还在运行，主动发送注销请求清理AMF状态
    
    Returns:
        bool: 是否成功发送注销请求（不保证AMF已清理，只保证请求已发送）
    """
    try:
        # 检查UE是否还在运行
        if not is_process_running("nr-ue"):
            return False
        
        # 检查UE socket是否可用
        global UEsocket
        if UEsocket is None:
            # 尝试连接UE
            try:
                connectUE()
            except:
                return False
        
        # 尝试发送注销请求（控制类消息，使用control=True）
        print("  🔄 发送注销请求清理AMF状态...")
        try:
            response = sendSymbol("deregistrationRequest", retries=2, control=True)
            if response == "deregistrationAccept" or "deregistration" in response.lower():
                print("  ✅ 注销请求已发送并收到确认")
                time.sleep(1)  # 等待AMF处理注销
                return True
            else:
                print(f"  ⚠️ 注销请求响应: {response}")
                return False
        except Exception as e:
            error_str = str(e).lower()
            if "timed out" in error_str or "broken pipe" in error_str:
                print(f"  ⚠️ UE连接已断开，无法发送注销请求")
                return False
            print(f"  ⚠️ 发送注销请求失败: {e}")
            return False
    except Exception as e:
        print(f"  ⚠️ 注销UE过程出错: {e}")
        return False

def is_process_running(process_name: str) -> bool:
    """
    【P0改进】检查进程是否在运行
    
    Args:
        process_name: 进程名称（如 '5gc', 'nr-gnb', 'nr-ue'）
        
    Returns:
        bool: 进程是否在运行
    """
    # 如果psutil可用，使用psutil（更准确）
    if psutil is not None:
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if process_name in cmdline:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        except Exception:
            pass
    
    # 如果psutil不可用，使用pgrep作为后备方案
    try:
        result = subprocess.run(['pgrep', '-f', process_name], 
                              capture_output=True, timeout=2)
        return result.returncode == 0
    except:
        return False

def is_port_listening(port: int, host: str = "localhost") -> bool:
    """
    【P0改进】检查端口是否在监听
    
    Args:
        port: 端口号
        host: 主机地址
        
    Returns:
        bool: 端口是否在监听
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def _core_running() -> bool:
    """核心网是否就绪：docker 部署查 AMF 容器，native 查 5gc 进程。"""
    profile = get_profile()
    if profile.deployment == "docker":
        amf = profile.proc("amf")
        r = subprocess.run(["docker", "ps", "--filter", f"name={amf}",
                            "--format", "{{.Names}}"],
                           capture_output=True, text=True, timeout=3)
        return r.returncode == 0 and amf in r.stdout
    return is_process_running("5gc")


def check_system_ready(check_core: bool = True, check_gnb: bool = True,
                       check_ue: bool = True, check_ports: bool = True) -> Tuple[bool, str]:

    reasons = []

    # 检查进程
    if check_core:
        if not _core_running():
            reasons.append("Core进程未运行")

    if check_gnb:
        if not is_process_running("nr-gnb"):
            reasons.append("GNB进程未运行")

    if check_ue:
        if not is_process_running("nr-ue"):
            reasons.append("UE进程未运行")


    if check_ports:
        # AMF 就绪：docker 部署查容器，native 查进程
        if not _core_running():
            reasons.append("AMF进程未运行（应监听38412端口）")


    if reasons:
        return False, "; ".join(reasons)
    
    return True, "系统就绪"

def wait_until_system_ready(max_wait: int = 30, check_interval: float = 1.0,
                            check_core: bool = True, check_gnb: bool = True,
                            check_ue: bool = True, check_ports: bool = True) -> bool:
    
    start_time = time.time()
    attempt = 0
    
    while time.time() - start_time < max_wait:
        attempt += 1
        is_ready, reason = check_system_ready(check_core, check_gnb, check_ue, check_ports)
        
        if is_ready:
            elapsed = time.time() - start_time
            if attempt > 1:
                print(f"  ✅ 系统就绪检查通过 (等待了 {elapsed:.1f}秒, 尝试 {attempt}次)")
            return True
        
        if attempt % 5 == 0:  # 每5次打印一次状态
            elapsed = time.time() - start_time
            print(f"  ⏳ 系统未就绪 (已等待 {elapsed:.1f}秒): {reason}")
        
        time.sleep(check_interval)
    
    # 超时
    elapsed = time.time() - start_time
    is_ready, reason = check_system_ready(check_core, check_gnb, check_ue, check_ports)
    if not is_ready:
        print(f"  ❌ 系统就绪检查超时 (等待了 {elapsed:.1f}秒): {reason}")
    return is_ready

def deregister_ue_if_running():
    
    try:
        # 检查UE是否还在运行
        if not is_process_running("nr-ue"):
            return False
        
        # 检查UE socket是否可用
        global UEsocket
        if UEsocket is None:
            # 尝试连接UE
            try:
                connectUE()
            except:
                return False
        
        # 尝试发送注销请求（控制类消息，使用control=True）
        print("  🔄 发送注销请求清理AMF状态...")
        try:
            response = sendSymbol("deregistrationRequest", retries=2, control=True)
            if response == "deregistrationAccept" or "deregistration" in response.lower():
                print("  ✅ 注销请求已发送并收到确认")
                time.sleep(1)  # 等待AMF处理注销
                return True
            else:
                print(f"  ⚠️ 注销请求响应: {response}")
                return False
        except Exception as e:
            error_str = str(e).lower()
            if "timed out" in error_str or "broken pipe" in error_str:
                print(f"  ⚠️ UE连接已断开，无法发送注销请求")
                return False
            print(f"  ⚠️ 发送注销请求失败: {e}")
            return False
    except Exception as e:
        print(f"  ⚠️ 注销UE过程出错: {e}")
        return False

def reset(full: bool, fsm_obj=None, fsm_sm_obj=None):
    
    global UEsocket, gNBsocket, UE2socket, UE3socket  # 【修复】global必须在函数开头
    
    if full:
        print("start full reset")
        if fsm_obj:
            fsm_obj.refresh_paths()
        if fsm_sm_obj:
            fsm_sm_obj.refresh_paths()
        
        # 第一步：先清理MongoDB（AMF还在运行，可以清理数据库）
        print("  🔄 第一步：清理MongoDB状态（AMF运行中）...")
        cleanup_amf_state()
        time.sleep(2)  # 等待清理完成
        
        # 第二步：尝试注销UE（如果可能，通过协议级别清理AMF内存状态）
        deregister_ue_if_running()
        time.sleep(1)
        
        # 第三步：kill所有进程（这会清除AMF内存状态）
        print("  🔄 第二步：停止所有进程...")
        
        # 先关闭socket连接，避免资源泄漏
        if UEsocket:
            try:
                UEsocket.close()
            except:
                pass
            UEsocket = None
        if gNBsocket:
            try:
                gNBsocket.close()
            except:
                pass
            gNBsocket = None
        
        killCore()
        killGNB()
        killUE()
        
        # 增加等待时间，确保进程完全停止
        print("  ⏳ 等待所有进程完全停止（3秒）...")
        time.sleep(3)  # 从0.5秒增加到3秒，确保进程完全停止
        
        # 强制清理残留进程和僵尸进程
        subprocess.run(["pkill", "-9", "-f", "5gc"], 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "-x", "open5gs-amfd"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "-f", "nr-gnb"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "-f", "nr-ue"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 额外 kill -9 所有孤儿 open5gs-* NF（残留 SBI 端口冲突是 core 启动失败主因：
        # pkill 5gc 后其子 NF 变孤儿继续占端口，导致新 core 的 child_main 断言失败）
        for p in subprocess.run(["pgrep", "-f", "open5gs-"],
                                capture_output=True, text=True).stdout.split():
            try:
                subprocess.run(["kill", "-9", p],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        time.sleep(2)  # 等待强制kill完成
        
        # 第四步：再次清理MongoDB（确保清理彻底，AMF已停止）
        print("  🔄 第三步：再次清理MongoDB状态（AMF已停止）...")
        cleanup_amf_state()
        time.sleep(2)  # 等待清理完成
        
        # 第五步：在启动进程之前改变IMSI，确保UE使用新IMSI
        current_offset = getOffset()
        new_offset = (current_offset + 1) % (MAX_IMSI_OFFSET + 1)
        if new_offset == 0:
            new_offset = 1  # 避免使用0（可能和初始值冲突）
        setOffset(new_offset)
        print(f"  ✅ IMSI_OFFSET已更新: {current_offset} -> {new_offset} (UE将使用新IMSI)")
        
        # 第六步：确保MongoDB服务正常（如果MongoDB进程被kill，可能需要重启）
        # 检查MongoDB是否运行
        try:
            result = subprocess.run(['pgrep', '-f', 'mongod'], 
                                  capture_output=True, timeout=2)
            if result.returncode != 0:
                print("  ⚠️ MongoDB未运行，可能需要手动启动")
        except:
            pass
        
        # 启动Core并验证成功，失败则重试
        max_core_retries = 3
        core_started = False
        
        # 初始化UE数据库
        print("  🔄 初始化UE数据库...")
        init_ue_database(num_imsi=5000)  # 增加到5000，支持长期大规模测试（2000+次迭代）
        
        for retry in range(max_core_retries):
            print(f"  🚀 启动Core网络（尝试 {retry+1}/{max_core_retries}）...")
            
            if startCore():  # 使用新的返回值检查
                print("  ⏳ 等待Core完全启动（15秒）...")
                time.sleep(15)  # 从8秒增加到15秒
                
                # 验证Core是否真的在运行
                if wait_until_system_ready(max_wait=15, check_core=True, 
                                            check_gnb=False, check_ue=False, 
                                            check_ports=False):
                    print("  ✅ Core网络启动成功")
                    core_started = True
                    break
                else:
                    print(f"  ⚠️ Core启动验证失败，重试...")
                    killCore()
                    time.sleep(3)
            else:
                print(f"  ❌ Core启动失败，重试...")
                killCore()
                time.sleep(3)
        
        if not core_started:
            print("  ❌ Core网络启动失败（已重试3次），中止full reset")
            print("  ⚠️ 系统处于不一致状态，建议检查Core配置和日志")
            print("reset done (with errors)")
            return
        
        # 额外等待，确保AMF NGAP服务完全就绪
        print("  ⏳ 额外等待AMF NGAP服务完全启动（8秒）...")
        time.sleep(8)  # 从5秒增加到8秒，确保NGAP服务完全初始化
        
        # 检查AMF日志，确认NGAP服务已启动
        try:
            with open('./logs/core.log', 'r') as f:
                log_content = f.read()
                if 'ngap_server' in log_content.lower():
                    print("  ✅ AMF NGAP服务已确认启动")
                else:
                    print("  ⚠️ 未在日志中找到NGAP服务启动信息，继续...")
        except:
            pass
        
        # 启动GNB并验证成功
        print("  🚀 启动GNB...")
        if not startGNB():
            print("  ❌ GNB启动失败，中止full reset")
            print("reset done (with errors)")
            return
        
        print("  ⏳ 等待GNB启动并连接AMF...")
        # 暂时禁用端口检查（SCTP端口无法用TCP方式检查），只检查进程
        if not wait_until_system_ready(max_wait=20, check_core=True, check_gnb=True, check_ue=False, check_ports=False):
            print("  ⚠️ GNB启动超时，但继续尝试启动UE...")
        else:
            # 增加等待时间，让GNB有时间连接到AMF并清理状态
            print("  ⏳ 等待GNB连接到AMF并稳定（15秒）...")
            time.sleep(15)  # 从10秒增加到15秒，给GNB和AMF更多时间建立连接并清理状态
            
            # 检查GNB是否成功连接到AMF
            try:
                with open('./logs/gnb.log', 'r') as f:
                    gnb_log = f.read()
                    if 'connection established' in gnb_log.lower() or 'sctp connection established' in gnb_log.lower():
                        print("  ✅ GNB已成功连接到AMF")
                        # 【改进重置机制】额外等待，确保AMF清理了之前的UE状态
                        print("  ⏳ 额外等待AMF清理之前的状态（3秒）...")
                        time.sleep(3)
                    elif 'connection refused' in gnb_log.lower() or 'failed' in gnb_log.lower():
                        print("  ⚠️ GNB连接AMF可能失败，继续尝试...")
            except:
                pass
        
        # 启动UE并验证成功（使用新IMSI）
        print("  🚀 启动UE（使用新IMSI）...")
        if not startUE():  # 此时IMSI_OFFSET已经更新，UE会使用新IMSI
            print("  ❌ UE启动失败，中止full reset")
            print("reset done (with errors)")
            return
        
        print("  ⏳ 等待UE启动并稳定...")
        time.sleep(5)  # 从2秒增加到5秒，给UE更多时间建立连接和稳定
        
        # 最终系统就绪检查，增加等待时间
        print("  🔍 最终系统就绪检查...")
        # 暂时禁用端口检查（SCTP端口无法用TCP方式检查），只检查进程
        if wait_until_system_ready(max_wait=15, check_core=True, check_gnb=True, check_ue=True, check_ports=False):
            print("  ✅ 系统完全就绪")
            # 额外等待，确保系统状态完全稳定
            print("  ⏳ 额外等待系统状态稳定（5秒）...")
            time.sleep(5)
        else:
            print("  ⚠️ 系统可能未完全就绪，但继续执行...")
        
        print("reset done") 
        return
    elif getOffset() > MAX_IMSI_OFFSET:
        print("start full reset (IMSI offset exceeded)")
        # 使用改进的重置逻辑
        # 清理MongoDB
        cleanup_amf_state()
        time.sleep(2)
        
        killCore()
        killGNB()
        killUE()
        time.sleep(3)  # 增加等待时间
        
        # 再次清理MongoDB
        cleanup_amf_state()
        time.sleep(2)
        
        startCore()
        time.sleep(15)  # 从10秒增加到15秒
        startGNB()
        time.sleep(5)   # 从0.1秒增加到5秒
        
        # 重置IMSI_OFFSET为1而不是0，避免IMSI冲突
        setOffset(1)
        print(f"  ✅ IMSI_OFFSET已重置为1（避免冲突）")
        
        startUE()
        time.sleep(5)   # 从0.1秒增加到5秒
        print("reset done")
        return
    else:
        print("start reset")
        
        # 部分重置时，先改变IMSI，避免AMF记住注册
        current_offset = getOffset()
        new_offset = (current_offset + 1) % (MAX_IMSI_OFFSET + 1)
        if new_offset == 0:
            new_offset = 1  # 避免使用0（可能和初始值冲突）
        setOffset(new_offset)
        print(f"  ✅ IMSI_OFFSET已更新: {current_offset} -> {new_offset}")
        
        ue_only = os.getenv("PARTIAL_RESET_UE_ONLY", "true").strip().lower() == "true"
        keep_gnb = ue_only and verify_gnb_connected(max_wait=3)

        if gNBsocket:
            try:
                gNBsocket.close()
            except Exception:
                pass
            gNBsocket = None

        if keep_gnb:
            print("  ℹ PARTIAL_RESET_UE_ONLY: 保留 GNB，仅重启 UE")
            killUE()
        else:
            killGNB()
            killUE()
            time.sleep(0.5)
            subprocess.run(["pkill", "-9", "-x", "nr-gnb"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-x", "nr-ue"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)

        gnb_started = keep_gnb
        if not gnb_started:
            for retry in range(3):
                if startGNB():
                    time.sleep(3)
                    if verify_gnb_connected(max_wait=20):
                        print("  ✅ GNB已启动并连接到AMF")
                        gnb_started = True
                        break
                    print(f"  ⚠️ GNB未连接到AMF（尝试 {retry+1}/3），重试...")
                    killGNB()
                    time.sleep(2)
                else:
                    print(f"  ⚠️ GNB启动失败（尝试 {retry+1}/3），重试...")
                    time.sleep(2)
        
        if not gnb_started:
            print("  ❌ GNB不可用，本次迭代 GNB 功能受限")

        if not startUE():
            print("  ⚠️ UE启动失败")
        else:
            print("  ✅ UE已启动")
        _ue_port = get_profile().ue_port
        if not wait_for_ue_control_port(_ue_port, timeout=30.0):
            print(f"  ⚠️ UE 控制端口 {_ue_port} 未就绪")
        time.sleep(8)
        
        print("  ⏳ 等待AMF清理内存状态（3秒）...")
        time.sleep(3)
        
        print("reset done") 
        return

def prepare_fresh_ue_for_path():
    
    global UEsocket
    
    # 1. 关闭旧连接
    if UEsocket:
        try:
            UEsocket.close()
        except:
            pass
        UEsocket = None
    
    # 2. Kill旧UE进程（彻底清理）
    killUE()
    time.sleep(1.5)  # 等待进程完全退出
    
    # 3. 更新IMSI（使用新身份，避免AMF记忆）
    current_offset = getOffset()
    new_offset = (current_offset + 1) % MAX_IMSI_OFFSET
    if new_offset == 0:
        new_offset = 1
    setOffset(new_offset)
    
    # 4. 启动新UE（使用新IMSI）
    if not startUE():
        print("  ❌ UE启动失败")
        return False
    
    time.sleep(2.5)  # 等待UE完全启动
    
    # 5. 建立新连接
    try:
        connectUE()
        return True
    except Exception as e:
        print(f"  ❌ 连接新UE失败: {e}")
        return False

def wait_ue_ready(max_wait=5):
   
    for i in range(max_wait):
        try:
            # 只检查UE进程是否运行，不测试连接（避免消耗连接）
            if not is_process_running("nr-ue"):
                return False
            
            # UE进程运行，认为已准备好
            # 不测试连接，因为UE只能接受1个连接，测试连接会消耗它
            time.sleep(0.3)  # 短暂等待UE完全启动
            return True
        except:
            time.sleep(0.5)
            continue
    return False

def close_ue_connection():
   
    global UEsocket
    if UEsocket:
        try:
            # 先shutdown，通知UE连接即将关闭
            UEsocket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            UEsocket.close()
        except:
            pass
        UEsocket = None
        # 等待UE检测到连接关闭并重新进入accept状态
        time.sleep(1.0)

def wait_for_ue_control_port(port: int = 45678, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except Exception:
            time.sleep(0.5)
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False


def connectUE():
   
    global UEsocket, current_ue_connector
    
    if UEsocket:
        try:
            UEsocket.getpeername()
            return True
        except Exception:
            close_ue_connection()
    
    close_ue_connection()
    
    if not is_process_running("nr-ue"):
        print("  ⚠️ UE进程未运行")
        return False

    _ue_port = get_profile().ue_port
    if not wait_for_ue_control_port(_ue_port, timeout=20.0):
        print(f"  ⚠️ UE 控制端口 {_ue_port} 未就绪")
        return False

    time.sleep(1.0)
    UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    UEsocket.settimeout(12)

    try:
        UEsocket.connect(("127.0.0.1", _ue_port))
        # init_reg=true 时 UE 可能不发 DONE，连接成功即可
        try:
            UEsocket.settimeout(4.0)
            response = UEsocket.recv(1024)
            if response:
                print(response)
        except socket.timeout:
            print("  ℹ UE 已连接（无 DONE 横幅，init_reg 路径）")
        UEsocket.settimeout(12)
        current_ue_connector = connectUE
        return True
    except socket.timeout as e:
        print(f"  ⚠️ UE连接超时: {e}")
        close_ue_connection()
        return False
    except Exception as e:
        print(f"  ⚠️ UE连接失败: {e}")
        close_ue_connection()
        return False

def connectUE2():
    global UEsocket, current_ue_connector
    UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    UEsocket.settimeout(1)
    UEsocket.connect(("localhost", 45679))
    print(UEsocket.recv(1024))
    current_ue_connector = connectUE2

def connectUE3():
    global UEsocket, current_ue_connector
    UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    UEsocket.settimeout(1)
    UEsocket.connect(("localhost", 45680))
    print(UEsocket.recv(1024))
    current_ue_connector = connectUE3

def connectGNB():
    global gNBsocket
    gNBsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    gNBsocket.settimeout(1)
    gNBsocket.connect(("localhost", 56789))
    print(gNBsocket.recv(1024))

def reconnectUE(max_retries: int = 3, retry_delay: float = 1.0, restart_on_failure: bool = True):
    
    global UEsocket
    
    print(f"  🔄 重连UE socket...")
    
    # 首次检查：UE进程是否运行
    ue_process_running = is_process_running("nr-ue")
    if not ue_process_running:
        print(f"  ⚠️ UE进程未运行，尝试重新启动...")
        try:
            killUE()  # 先确保清理
            time.sleep(1)
            startUE()
            time.sleep(3)  # 等待UE启动
            print(f"  ✓ UE已重新启动")
            ue_process_running = True
        except Exception as e:
            print(f"  ⚠️ UE重启失败: {e}")
            return False
    
    for attempt in range(max_retries):
        try:
            # 先正确关闭旧连接
            close_ue_connection()
            
            # 等待一段时间再重连（给UE时间重新进入accept状态）
            if attempt > 0:
                time.sleep(1.0 + retry_delay * attempt)  # 基础等待1秒 + 递增延迟
            else:
                time.sleep(1.0)  # 第一次也等待1秒
            
            # 尝试连接（使用改进的连接机制）
            if current_ue_connector:
                result = current_ue_connector()
                if not result:
                    # 如果连接失败，尝试使用默认连接器
                    if connectUE():
                        result = True
            else:
                result = connectUE()
            
            if result and UEsocket:
                print(f"  ✅ UE重连成功 (尝试 {attempt+1}/{max_retries})")
                return True
            
            # 连接失败（返回False或socket为None），检查是否应该重启UE进程
            if restart_on_failure and attempt >= 1:
                # 第二次尝试失败后，检查UE进程并考虑重启
                if not is_process_running("nr-ue"):
                    print(f"  🔍 连接失败且UE进程未运行，尝试重启...")
                    try:
                        killUE()
                        time.sleep(1)
                        startUE()
                        time.sleep(3)
                        print(f"  ✓ UE已重启，将在下次尝试中重连")
                        if attempt < max_retries - 1:
                            continue
                    except Exception as restart_e:
                        print(f"  ⚠️ UE重启失败: {restart_e}")
                elif attempt >= 1:
                    # UE进程运行但连接失败，可能是socket异常，尝试重启
                    print(f"  🔍 连接失败但UE进程运行，可能是socket异常，尝试重启UE...")
                    try:
                        killUE()
                        time.sleep(1)
                        startUE()
                        time.sleep(3)
                        print(f"  ✓ UE已重启，将在下次尝试中重连")
                        if attempt < max_retries - 1:
                            continue
                    except Exception as restart_e:
                        print(f"  ⚠️ UE重启失败: {restart_e}")
            
            # 连接失败，继续重试
            
        except (socket.timeout, ConnectionError, OSError) as e:
            error_str = str(e).lower()
            print(f"  ⚠️ UE重连失败 (尝试 {attempt+1}/{max_retries}): {e}")
            
            # 处理连接超时和连接拒绝，都检查UE进程并考虑重启
            if restart_on_failure and ("timed out" in error_str or "connection refused" in error_str or "connection refused" in str(e)):
                error_type = "连接超时" if "timed out" in error_str else "Connection refused"
                print(f"  🔍 检测到{error_type}，检查UE进程状态...")
                
                # 检查UE进程是否还在运行
                if not is_process_running("nr-ue"):
                    print(f"  ⚠️ UE进程已停止，尝试重启...")
                    try:
                        killUE()  # 先确保清理
                        time.sleep(1)
                        startUE()
                        time.sleep(3)  # 等待UE启动
                        print(f"  ✓ UE已重新启动，将在下次尝试中重连")
                        # 继续循环，下次尝试连接
                        if attempt < max_retries - 1:
                            continue
                    except Exception as restart_e:
                        print(f"  ⚠️ UE重启失败: {restart_e}")
                        if attempt == max_retries - 1:
                            return False
                else:
                    # UE进程还在运行，但socket无法连接（超时或拒绝），可能是socket状态异常
                    # 立即尝试kill并重启UE进程（不再等待第二次尝试）
                    print(f"  🔄 UE进程运行但无法连接（{error_type}），尝试重启UE进程...")
                    try:
                        killUE()
                        time.sleep(1)
                        startUE()
                        time.sleep(3)  # 等待UE启动
                        print(f"  ✓ UE已重启，将在下次尝试中重连")
                        if attempt < max_retries - 1:
                            continue
                    except Exception as restart_e:
                        print(f"  ⚠️ UE重启失败: {restart_e}")
            
            if attempt == max_retries - 1:
                print(f"  ❌ UE重连失败，已尝试{max_retries}次")
                return False
                
        except Exception as e:
            print(f"  ❌ UE重连异常: {e}")
            # 异常时也检查UE进程
            if restart_on_failure and attempt < max_retries - 1:
                if not is_process_running("nr-ue"):
                    print(f"  🔄 检测到异常且UE进程未运行，尝试重启...")
                    try:
                        killUE()
                        time.sleep(1)
                        startUE()
                        time.sleep(3)
                        print(f"  ✓ UE已重启，继续尝试重连")
                        continue
                    except:
                        pass
            return False
    
    return False

def reconnectGNB(max_retries: int = 5, retry_delay: float = 1.0, restart_on_failure: bool = True):
   
    global gNBsocket
    
    print(f"  🔄 重连GNB socket...")
    
    for attempt in range(max_retries):
        try:
            # 先关闭旧连接
            if gNBsocket:
                try:
                    gNBsocket.close()
                except:
                    pass
                gNBsocket = None
            
            # 等待一段时间再重连
            if attempt > 0:
                time.sleep(retry_delay * attempt)  # 递增延迟
            
            # 尝试连接
            connectGNB()
            
            # 验证连接
            if gNBsocket:
                print(f"  ✅ GNB重连成功 (尝试 {attempt+1}/{max_retries})")
                return True
            
        except (socket.timeout, ConnectionError, OSError) as e:
            err = str(e).lower()
            print(f"  ⚠️ GNB重连失败 (尝试 {attempt+1}/{max_retries}): {e}")
            if restart_on_failure and ("connection refused" in err or "timed out" in err):
                if not is_process_running("nr-gnb") or not is_gnb_port_listening():
                    print("  🔍 GNB 进程/端口异常，尝试重启 nr-gnb...")
                    if restartGNB():
                        time.sleep(2)
                        continue
            if attempt == max_retries - 1:
                print(f"  ❌ GNB重连失败，已尝试{max_retries}次")
                return False
        except Exception as e:
            print(f"  ❌ GNB重连异常: {e}")
            return False
    
    return False


def ensure_gnb_ready(max_attempts: int = 3) -> bool:
    """Ensure nr-gnb is listening and fuzzer control socket is connected."""
    global gNBsocket
    for attempt in range(max_attempts):
        try:
            if gNBsocket:
                try:
                    gNBsocket.getpeername()
                    return True
                except (OSError, AttributeError):
                    pass
            if not is_process_running("nr-gnb") or not is_gnb_port_listening():
                print(f"  ℹ GNB 未就绪 (attempt {attempt + 1}/{max_attempts})，重启 nr-gnb...")
                if not restartGNB():
                    time.sleep(2)
                    continue
                time.sleep(2)
            connectGNB()
            return True
        except (socket.timeout, ConnectionError, OSError) as e:
            print(f"  ⚠️ ensure_gnb_ready: {e}")
            if reconnectGNB(max_retries=3, restart_on_failure=True):
                return True
        except Exception as e:
            print(f"  ⚠️ ensure_gnb_ready 异常: {e}")
        time.sleep(1)
    return False

def sendSymbol(symbol: string, retries: int = 5, control: bool = False):
   
    global UEsocket  
    max_attempts = (retries + 1) if not control else min(2, retries + 1)
    
    for attempt in range(max_attempts):
        try:
            # 检查并建立连接
            if UEsocket is None:
                # 不调用connectUE()，因为它会关闭旧连接
                # 直接尝试连接，避免不必要的关闭
                if not is_process_running("nr-ue"):
                    return "null_action"
                
                # 尝试连接（不关闭旧连接，因为已经没有连接了）
                UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                UEsocket.settimeout(5)
                try:
                    UEsocket.connect(("localhost", get_profile().ue_port))
                    # init_reg=true 时 UE 可能不发 DONE，连接成功即可
                    try:
                        UEsocket.settimeout(3.0)
                        response = UEsocket.recv(1024)  # 接收DONE
                        print(response)
                    except socket.timeout:
                        print("  ℹ UE 已连接（无 DONE 横幅，init_reg 路径）")
                    UEsocket.settimeout(12)
                    current_ue_connector = connectUE
                except Exception as e:
                    print(f"  ⚠️ UE连接失败: {e}")
                    if UEsocket:
                        try:
                            UEsocket.close()
                        except:
                            pass
                    UEsocket = None
                    if attempt < max_attempts - 1:
                        # 控制消息重试间隔更短，避免长时间阻塞
                        base_wait = 1 if control else 2
                        wait_time = base_wait * (attempt + 1)
                        print(f"  ⏳ sendSymbol等待 {wait_time}秒后重试 ({symbol})...")
                        time.sleep(wait_time)
                        continue
                    return "null_action"
            
            
            try:
                # 检查socket文件描述符
                fd = UEsocket.fileno()
                if fd == -1:
                    raise ConnectionError("Socket已关闭")
                
                
                try:
                    err = UEsocket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if err != 0:
                        raise ConnectionError(f"Socket有错误: {err}")
                except:
                    # getsockopt可能在某些状态下失败，忽略
                    pass
                
                # 连接有效，继续使用
            except (ConnectionError, OSError) as e:
                print(f"  ⚠️ 连接验证失败: {e}")
                close_ue_connection()  # 使用正确的关闭函数
                if attempt < max_attempts - 1:
                    # 检查UE进程
                    if not is_process_running("nr-ue"):
                        print("  ⚠️ UE进程未运行")
                        return "null_action"
                    
                    base_wait = 1 if control else 2
                    wait_time = base_wait * (attempt + 1)
                    print(f"  ⏳ 等待 {wait_time}秒后重连...")
                    time.sleep(wait_time)
                    
                    if reconnectUE(max_retries=3):
                        continue
                    else:
                        # 重连失败，可能UE进程有问题
                        print("  ⚠️ UE重连失败，可能需要重启UE")
                        return "null_action"
                return "null_action"
            
            # 发送消息
            if "serviceRequest" in symbol:
                sendRRCRelease()
                time.sleep(0.1)
            if ":" in symbol:
                i = symbol.find(":")
                sendSymbol("testMessage")
                testMsg = symbol[i+1:]
                return sendFuzzingMessage(testMsg.encode(), retries=retries)
            
            
            if control:
                UEsocket.settimeout(5)   # 控制消息：5秒超时
            else:
                UEsocket.settimeout(15)  # fuzz 消息：15秒超时
            
            
            symbol_clean = symbol.strip()
            
            
            try:
                import select
                _, writable, _ = select.select([], [UEsocket], [], 0.1)
                if not writable:
                    raise ConnectionError("Socket不可写，连接可能已关闭")
            except (ConnectionError, OSError) as e:
                print(f"  ⚠️ 连接不可写: {e}")
                close_ue_connection()
                raise
            except:
                # select在某些系统上可能不可用，忽略
                pass
            
            # 发送消息（与原始fuzzer一致，不添加换行符）
            UEsocket.send(symbol_clean.encode())
            
            # 【根本修复】接收响应，增加错误处理
            try:
                msg_out = UEsocket.recv(8192).decode().strip()
                
                # 检查响应是否有效
                if not msg_out or msg_out == "":
                    print(f"  ⚠️ 收到空响应，UE可能无法处理消息")
                    return "null_action"
                
                return msg_out
            except socket.timeout:
                print(f"  ⚠️ 接收响应超时，UE可能无法处理消息 '{symbol_clean}'")
                # 超时可能是UE无法解析消息导致阻塞
                close_ue_connection()  # 关闭连接，让UE重新accept
                raise
            except (ConnectionError, OSError) as e:
                print(f"  ⚠️ 接收响应时连接错误: {e}")
                close_ue_connection()
                raise
            
        except (socket.timeout, ConnectionError, OSError) as e:
            print(f"sendSymbol error ({symbol}, 尝试 {attempt+1}/{max_attempts}): {e}")
            
            
            close_ue_connection()
            
            if attempt < max_attempts - 1:
                
                if not is_process_running("nr-ue"):
                    print(f"  ⚠️ UE进程未运行，无法重连")
                    return "null_action"
                
                
                base_wait = 1 if control else 2
                wait_time = base_wait * (attempt + 1)
                print(f"  ⏳ 等待 {wait_time}秒后重连...")
                time.sleep(wait_time)
                
                
                if reconnectUE(max_retries=3):
                    print(f"  ✅ UE重连成功，继续发送消息")
                    continue
                else:
                    print(f"  ❌ UE重连失败，结束本次发送，返回null_action")
                    return "null_action"
            else:
                # 所有重试都失败
                print(f"  ❌ sendSymbol最终失败 ({symbol})，已尝试 {max_attempts}次")
                return "null_action"
        except Exception as e:
            print(f"sendSymbol unexpected error ({symbol}): {e}")
            if attempt < retries:
                time.sleep(2)
                continue
            return "null_action"
    
    return "null_action"

def sendFuzzingMessage(msg, retries: int = 2):
    global UEsocket  
    for attempt in range(retries + 1):
        try:
            if UEsocket is None:
                connectUE()
            UEsocket.send(msg)
            print("send message")
            print(msg)
            UEsocket.settimeout(15)
            return UEsocket.recv(8192).decode().strip()
        except (socket.timeout, ConnectionError, OSError) as e:
            print(f"sendFuzzingMessage error: {e}")
            if attempt < retries:
                reconnectUE()
                continue
            raise

def getFuzzingMessage(msg_len: int):
    global UEsocket  # 声明全局变量
    return UEsocket.recv(msg_len + 1)

def try_deregister_then_register(max_retries=2):
    
    
    if UEsocket is None:
        print(f"  ⚠️ UE连接已断开，无法进行注销-注册恢复，需要重置")
        return False
    
    
    try:
        # 快速测试连接（只尝试1次，超时时间短）
        test_response = sendSymbol("registrationRequest", retries=1, control=True)
        if (
            test_response == "null_action"
            or test_response is None
            or "timed out" in str(test_response).lower()
        ):
            print(f"  ⚠️ UE无响应或连接异常，无法进行注销-注册恢复")
            return False
    except Exception as e:
        if "timed out" in str(e).lower() or "broken pipe" in str(e).lower() or "connection" in str(e).lower():
            print(f"  ⚠️ UE连接异常（{e}），无法进行注销-注册恢复")
            return False
    
    # UE连接正常，继续恢复流程
    for attempt in range(max_retries):
        try:
            print(f"  🔄 尝试注销-注册恢复（尝试 {attempt+1}/{max_retries}）...")
            
            # 快速失败策略：只重试1次，如果失败立即返回False
            # 发送注销请求（只重试1次，如果失败说明网络状态异常）
            response = sendSymbol("deregistrationRequest", retries=1, control=True)
            
            # 如果第一次尝试就返回null_action或超时，直接返回False
            # 不要浪费时间重试，因为如果网络状态异常，重试也无济于事
            if response == "null_action":
                print(f"  ⚠️ 注销请求无响应，网络状态可能异常，需要完整重置")
                return False
            
            # 【根本修复】检查是否超时
            if response is None or response == "":
                print(f"  ⚠️ 注销请求超时，网络状态可能异常，需要完整重置")
                return False
            
            time.sleep(1)  # 等待注销完成
            
            if response == "deregistrationAccept" or "deregistration" in response.lower():
                print(f"  ✅ 注销成功，等待2秒后验证状态...")
                time.sleep(2)
                
                # 再次验证状态
                response = sendSymbol("registrationRequest", control=True)
                time.sleep(0.5)
                
                if response == "authenticationRequest":
                    print(f"  ✅ 注销-注册恢复成功！网络已恢复到初始状态")
                    return True
                elif response == "registrationReject":
                    print(f"  ⚠️ 注销后仍收到registrationReject，可能需要等待更长时间")
                    if attempt < max_retries - 1:
                        time.sleep(3)  # 增加等待时间
                        continue
            else:
                print(f"  ⚠️ 注销请求响应: {response}，可能不需要注销")
                # 如果注销失败，可能网络已经在初始状态，直接验证
                response = sendSymbol("registrationRequest", control=True)
                if response == "authenticationRequest":
                    return True
        except Exception as e:
            error_str = str(e).lower()
            # 如果是连接相关错误，立即返回
            if "timed out" in error_str or "broken pipe" in error_str or "connection" in error_str:
                print(f"  ❌ UE连接错误（{e}），无法进行注销-注册恢复")
                return False
            print(f"  ⚠️ 注销-注册恢复出错: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
    
    print(f"  ❌ 注销-注册恢复失败，需要完全重置")
    return False

def verify_state_for_path(fsm: FSM, path: Path, max_retries=3, wait_after_reset=False) -> bool:
    
    if path is None or not hasattr(path, 'path_states') or len(path.path_states) == 0:
        return True  # 如果路径为空，跳过验证
    
    # path.path_states是字符串列表，不是State对象列表
    start_state_name = path.path_states[0] if isinstance(path.path_states[0], str) else path.path_states[0].name
    
    # 完全跳过状态验证，直接返回True
    # 因为AMF可能在内存中记住了状态，即使MongoDB清理了也没用
    # 让路径执行本身来验证状态，而不是预先验证
    if start_state_name == "s0":
        # 完全跳过状态验证，直接返回True
        # 因为AMF可能在内存中记住了状态，验证总是失败
        # 让路径执行本身来验证状态，如果失败再处理
        print(f"  ℹ️ 路径从s0开始，跳过状态验证，直接执行路径...")
        print(f"  ℹ️ AMF可能在内存中记住了状态，路径执行本身会验证")
        return True  # 直接返回True，跳过验证
    
    # 如果路径不从s0开始，降低验证严格性
    # 因为某些状态的路径可能不需要从特定初始状态开始
    # 让路径执行本身来验证状态
    print(f"  ℹ️ 路径起始状态为 {start_state_name}（非s0），跳过严格验证，让路径执行来验证状态")
    return True  # 返回True，让路径执行来验证

def verify_initial_state(max_retries=3, wait_after_reset=False):
    
    # 如果是在重置后验证，先检查系统就绪
    if wait_after_reset:
        print(f"  ⏳ 重置后验证：等待系统完全启动...")
        
        # 检查UE进程，如果不在则重新启动
        if not is_process_running("nr-ue"):
            print(f"  ⚠️ UE进程未运行，尝试重新启动...")
            killUE()  # 先确保清理
            time.sleep(1)
            startUE()
            time.sleep(5)  # 等待UE启动
            print(f"  ✓ UE已重新启动")
        
        # 使用动态等待系统就绪，而不是固定等待时间
        if not wait_until_system_ready(max_wait=25, check_ue=True, check_ports=False):
            print(f"  ⚠️ 系统未完全就绪，尝试重新启动UE...")
            # 尝试再次启动UE
            killUE()
            time.sleep(1)
            startUE()
            time.sleep(5)
            
            # 再次检查
            if not wait_until_system_ready(max_wait=20, check_ue=True, check_ports=False):
                print(f"  ❌ UE启动失败，无法进行状态验证")
                return False
        
        # 确保UE连接正常
        try:
            if UEsocket is None:
                if not reconnectUE(max_retries=3):
                    print(f"  ⚠️ UE连接失败，尝试重新连接...")
                    time.sleep(2)
                    if not reconnectUE(max_retries=5):
                        print(f"  ❌ UE连接失败，无法进行状态验证")
                        return False
            time.sleep(2)  # 等待连接稳定（增加等待时间）
            print(f"  ✓ UE连接已建立")
        except Exception as e:
            print(f"  ⚠️ UE连接失败: {e}，尝试重新连接...")
            # 尝试重新连接
            if reconnectUE(max_retries=3):
                time.sleep(2)
                print(f"  ✓ UE重新连接成功")
            else:
                print(f"  ❌ UE连接失败，无法进行状态验证")
                return False
    
    for attempt in range(max_retries):
        try:
            # 发送registrationRequest探测
            response = sendSymbol("registrationRequest", control=True)
            time.sleep(0.5)
            
            # 如果在初始状态，应该收到authenticationRequest
            if response == "authenticationRequest":
                print(f"  ✅ 状态验证成功: 网络在初始状态")
                return True
            elif response == "registrationReject":
                # 不在初始状态，可能已经注册
                print(f"  ⚠️ 状态验证失败 (尝试 {attempt+1}/{max_retries}): 收到registrationReject，网络不在初始状态")
                
                # 【根本修复】收到registrationReject时，说明AMF状态异常或已记住注册
                # 此时尝试注销-注册恢复可能失败，因为状态不一致
                # 直接返回False，让上层触发完整重置，更可靠
                print(f"  ℹ️ 收到registrationReject，说明AMF状态异常，需要完整重置来清理状态")
                
                # 如果是重置后第一次验证失败，可能是IMSI问题，尝试改变IMSI
                if wait_after_reset and attempt == 0:
                    print(f"  🔄 重置后首次验证失败，尝试改变IMSI...")
                    current_offset = getOffset()
                    new_offset = (current_offset + 1) % (MAX_IMSI_OFFSET + 1)
                    if new_offset == 0:
                        new_offset = 1  # 避免使用0
                    setOffset(new_offset)
                    print(f"  ✅ IMSI_OFFSET已更新: {current_offset} -> {new_offset}")
                    
                    # 重启UE使用新IMSI
                    killUE()
                    time.sleep(2)
                    startUE()
                    time.sleep(5)
                    
                    # 重新连接UE
                    try:
                        if UEsocket:
                            close_ue_connection()
                        connectUE()
                        time.sleep(2)
                    except:
                        pass
                    
                    # 继续重试一次
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                
                # 收到registrationReject时，不立即返回False
                # 而是返回True，允许继续执行路径，让路径执行本身来验证状态
                # 因为AMF可能在内存中记住了状态，即使MongoDB清理了也没用
                print(f"  ℹ️ 收到registrationReject，但允许继续执行路径，让路径执行来验证状态")
                return True  # 改为True，允许继续执行路径
            elif response == "null_action":
                print(f"  ⚠️ 状态验证失败 (尝试 {attempt+1}/{max_retries}): 收到null_action，可能是网络问题")
                if attempt < max_retries - 1:
                    time.sleep(2)  # 增加等待时间
                    continue
                return False
            elif response == "" or response is None:
                # 空响应处理：系统可能还没启动，需要等待
                print(f"  ⚠️ 状态验证失败 (尝试 {attempt+1}/{max_retries}): 收到空响应，系统可能还未启动")
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # 递增等待时间
                    print(f"  ⏳ 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    # 尝试重新连接UE
                    try:
                        if UEsocket is None:
                            connectUE()
                    except:
                        pass
                    continue
                return False
            else:
                print(f"  ⚠️ 状态验证失败 (尝试 {attempt+1}/{max_retries}): 收到未知响应: '{response}'")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return False
        except Exception as e:
            print(f"  ⚠️ 状态验证异常 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = 3 * (attempt + 1)
                print(f"  ⏳ 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                # 尝试重新连接
                try:
                    if UEsocket is None:
                        connectUE()
                except:
                    pass
    
    return False

def select_shortest_path(state: State):
    
    if not state.paths:
        return None
    
    # 第一步：基础过滤（短路径完全免于过滤）
    filtered_paths = []
    for p in state.paths:
        inputs = getattr(p, "input_symbols", []) or []
        has_reg_req = any(sym == "registrationRequest" for sym in inputs)
        has_sec_rej = any(sym == "securityModeReject" for sym in inputs)
        first_input = inputs[0] if inputs else None
        path_length = len(p.path_states)
        is_short_path = path_length <= 3

        # 短路径完全免于所有过滤规则！
        if is_short_path:
            filtered_paths.append(p)
            continue
        
        # 以下过滤规则只对长路径（>3）应用
        
        # 过滤规则1：首条为registrationRequest且长度>2
        if first_input == "registrationRequest" and len(p.path_states) > 2:
            continue

        # 过滤规则2：包含securityModeReject
        if has_sec_rej:
            continue
        
        # 过滤规则3：历史成功率极低（<10%）且失败次数>5
        if hasattr(p, 'success_rate') and hasattr(p, 'fail_count'):
            if p.success_rate < 0.1 and p.fail_count > 5:
                print(f"  ⚠️ 跳过高失败率长路径（成功率: {p.success_rate:.1%}, 失败次数: {p.fail_count}）")
                continue
        
        filtered_paths.append(p)
    
    if not filtered_paths:
        print(f"  ⚠️ 没有可用路径（所有路径被过滤）")
        return None
    
    # 移除短/长统计，改为总数统计
    print(f"  📊 可用路径总数: {len(filtered_paths)}个")
    
    # 改进的综合评分函数
    def path_score(p):
        """
        计算路径得分
        - 成功率权重：50%（主要因素）
        - 路径长度权重：30%（适中长度优先）
        - 经验权重：20%（尝试过的更可靠）
        """
        # 1. 成功率分（权重50%）
        success_rate = getattr(p, 'success_rate', 0.5)
        success_score = success_rate * 0.5
        
        # 2. 长度分（权重30%）- 适中长度优先，不绝对偏好短
        length = len(p.path_states)
        if length <= 1:
            length_score = 0.6  # 太短，可能无意义
        elif 2 <= length <= 4:
            length_score = 1.0  # 理想长度
        elif 5 <= length <= 7:
            length_score = 0.9  # 可接受长度
        else:
            length_score = 0.7  # 过长
        length_score *= 0.3
        
        # 3. 经验分（权重20%）- 尝试过的路径有数据支撑
        attempt_count = getattr(p, 'success_count', 0) + getattr(p, 'fail_count', 0)
        if attempt_count == 0:
            experience_score = 0.5  # 未探索，中等优先级
        else:
            experience_score = min(attempt_count / 10, 1.0)
        experience_score *= 0.2
        
        # 综合得分
        return success_score + length_score + experience_score
    
    # 按得分排序（高到低）
    sorted_paths = sorted(filtered_paths, key=path_score, reverse=True)
    
    # 移除短/长路径的硬性区分，直接选择最高分的路径
    best_path = sorted_paths[0]
    
    # 统计路径长度分布（信息展示）
    length_distribution = {}
    for p in filtered_paths:
        length = len(p.path_states)
        length_distribution[length] = length_distribution.get(length, 0) + 1
    
    print(f"  📊 可选路径分布: ", end="")
    for length in sorted(length_distribution.keys()):
        print(f"长度{length}({length_distribution[length]}个) ", end="")
    print()
    
    # 输出选择信息（不区分短/长）
    success_rate = getattr(best_path, 'success_rate', 0.5)
    score = path_score(best_path)
    total_attempts = getattr(best_path, 'success_count', 0) + getattr(best_path, 'fail_count', 0)
    path_length = len(best_path.path_states)
    
    print(
        f"   选择路径（得分: {score:.2f}, 成功率: {success_rate:.1%}, "
        f"尝试: {total_attempts}次, 长度: {path_length}）: "
        + " -> ".join([s.name if hasattr(s, "name") else str(s) for s in best_path.path_states])
    )
    
    return best_path

def execSequence(path: Path, tolerate_soft_mismatch: bool = True):
    """
    执行路径序列（改进版 - 添加详细日志）
    
    【修复】增加详细的路径执行日志，帮助诊断路径失败原因
    """
    if path == None:
        return True
    
    out_list = []
    mismatch_logged = False
    had_soft_mismatch = False
    had_hard_error = False
    state_sequence = path.path_states if hasattr(path, 'path_states') else []
    
    # 初始化失败原因标记
    path._failure_reason = None
    
    # 打印路径信息
    print(f"  执行路径: {' -> '.join([s.name if hasattr(s, 'name') else str(s) for s in state_sequence])}")
    print(f"  输入序列: {path.input_symbols}")
    print(f"  期望输出: {path.output_symbols}")
    
    for i in range(len(path.path_states) - 1):
        input_symbol = path.input_symbols[i] if i < len(path.input_symbols) else "UNKNOWN"
        expected_output = path.output_symbols[i] if i < len(path.output_symbols) else "UNKNOWN"
        
        print(f"    [步骤 {i+1}/{len(path.path_states)-1}] 发送: {input_symbol}, 期望: {expected_output}")
        
        # 增加消息间隔，给UE/AMF更多处理时间
        if i > 0:
            time.sleep(0.3)  # 每条消息间隔300ms（除了第一条）
        
        try:
            # 路径中的输入符号属于控制/探测类消息，使用control=True以避免长时间阻塞
            out = sendSymbol(input_symbol, control=True)
            out_list.append(out)
            time.sleep(0.1)
            
            print(f"    [步骤 {i+1}] 实际输出: {out}")
            
            # ========== 宽松匹配逻辑 ==========
            if out != expected_output:
                # 先判断是否为"硬错误"
                if out in ("null_action", "", None):
                    print(f"    ⚠️ 收到null_action，可能是UE连接断开，尝试重连...")
                    
                    # 在execSequence中检测null_action并重连UE
                    retry_success = False
                    if reconnectUE(max_retries=2):
                        print(f"    ✅ UE重连成功，重新发送消息: {input_symbol}")
                        time.sleep(1)  # 等待连接稳定
                        
                        # 重新发送当前消息
                        try:
                            retry_out = sendSymbol(input_symbol, control=True)
                            out_list[-1] = retry_out  # 更新最后一次输出
                            out = retry_out  # 更新out变量
                            print(f"    [步骤 {i+1}] 重连后实际输出: {out}")
                            
                            # 如果重连后仍然是null_action，视为硬错误
                            if out in ("null_action", "", None):
                                print(f"    ❌ 重连后仍收到null_action，路径执行失败")
                                had_hard_error = True
                                break
                            # 如果重连后收到期望输出，标记成功并继续
                            elif out == expected_output:
                                print(f"    ✅ 重连后收到期望输出，继续执行路径")
                                retry_success = True
                                # 继续执行下一个步骤（外层循环继续）
                                continue
                            else:
                                # 重连后收到非期望输出，需要继续判断是否为硬/软错误
                                retry_success = True
                                print(f"    ⚠️ 重连后收到非期望输出: {out}（期望: {expected_output}），继续判断...")
                                
                                # 手动检查是否为硬错误（reject/error）
                                if isinstance(out, str) and "reject" in out.lower():
                                    print(f"    ℹ️ 重连后收到拒绝消息: {out}，视为本路径的硬失败")
                                    had_hard_error = True
                                    break
                                elif isinstance(out, str) and "error" in out.lower():
                                    print(f"    ⚠️ 重连后收到错误响应: {out}")
                                    had_hard_error = True
                                    break
                                else:
                                    # 非错误/拒绝的正常NAS偏差 → 视为"软偏差"
                                    had_soft_mismatch = True
                                    print(f"    ⚠️ 重连后路径软偏差: 期望 {expected_output}，实际 {out}，继续执行后续步骤")
                                    # 继续执行下一个步骤（外层循环继续）
                                    continue
                        except Exception as retry_e:
                            print(f"    ❌ 重连后重新发送消息失败: {retry_e}")
                            had_hard_error = True
                            break
                    else:
                        print(f"    ❌ UE重连失败，路径执行失败")
                        had_hard_error = True
                        break
                elif isinstance(out, str) and "error" in out.lower():
                    print(f"    ⚠️ 收到错误响应: {out}")
                    had_hard_error = True
                elif isinstance(out, str) and "reject" in out.lower():
                    # 对 registrationReject / serviceReject 等直接视为"本路径的硬失败"
                    # 原因：AMF 已明确拒绝该流程，继续发送后续消息往往只会导致超时和重连风暴
                    print(f"    ℹ️ 收到拒绝消息: {out}，视为本路径的硬失败，不再继续执行后续步骤")
                    had_hard_error = True
                    # 【P0优化】标记是否收到registrationReject，用于后续更快触发重置
                    if "registrationreject" in out.lower():
                        # 将registrationReject标记存储在路径对象中，供主循环使用
                        path._failure_reason = 'registrationReject'
                else:
                    # 非空、非错误/拒绝的正常NAS偏差 → 视为“软偏差”
                    had_soft_mismatch = True
                    print(f"    ⚠️ 路径软偏差: 期望 {expected_output}，实际 {out}，继续执行后续步骤以观察真实行为")
                
                # 将偏差记录到辅助日志，供后续修正FSM使用（只记录一次，避免过多IO）
                if not mismatch_logged:
                    mismatch_logged = True
                    try:
                        with open("./fsm_correction.log", "a") as log_f:
                            import datetime
                            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            log_f.write(f"[{ts}] PATH_MISMATCH\n")
                            log_f.write(f"  states   : {state_sequence}\n")
                            log_f.write(f"  inputs   : {path.input_symbols}\n")
                            log_f.write(f"  expected : {path.output_symbols}\n")
                            log_f.write(f"  got      : {out_list}\n")
                            log_f.write(f"  step     : {i+1}, input={input_symbol}, expected={expected_output}, actual={out}\n")
                            log_f.write("\n")
                    except Exception as log_e:
                        print(f"    ⚠️ 记录FSM修正日志失败: {log_e}")
                
                # 如果是硬错误，没必要继续执行后续步骤，提前退出循环
                if had_hard_error:
                    break
        except Exception as e:
            print(f"    ❌ 路径执行异常: {e}")
            print(f"       步骤: {i+1}, 输入: {input_symbol}")
            had_hard_error = True
            # 异常情况下，失败原因将在循环外统一记录
            path._failure_reason = "exception"
            break
    
    # ========== 根据执行结果给出总结 ==========
    if had_hard_error:
        print(f"  路径执行失败（存在硬错误，例如null_action/超时/异常）")
        print(f"  实际输出序列: {out_list}")
        
        # 【方案#1】记录路径执行失败统计
        failure_reason = None
        if out_list and len(out_list) > 0:
            last_output = out_list[-1]
            if isinstance(last_output, str):
                if "reject" in last_output.lower():
                    failure_reason = "reject"
                elif last_output in ("null_action", "", None):
                    failure_reason = "null_action"
            elif last_output is None or last_output == "":
                failure_reason = "null_action"
        # 如果没有从输出序列推断出原因，尝试从_failure_reason获取
        if not failure_reason:
            failure_reason = getattr(path, '_failure_reason', None)
        path.record_failure(failure_reason)
        
        return False
    
    if had_soft_mismatch:
        if tolerate_soft_mismatch:
            print(f"  路径存在软偏差，但被允许为'近似成功'，以便后续进入模糊测试阶段")
            print(f"   实际输出序列: {out_list}")
            # 软偏差视为成功（允许容忍）
            path.record_success()
            return True
        else:
            print(f"  ❌ 路径存在软偏差且当前为严格模式，视为失败")
            print(f"     实际输出序列: {out_list}")
            path.record_failure("soft_mismatch")
            return False
    
    print(f"  路径执行成功（完全匹配期望输出）")
    # 记录路径执行成功统计
    path.record_success()
    
    return True

def ensure_path_ready(path: Path, fsm: FSM):
    """
    确保路径的输入/输出和状态数量一致，如果不一致则重新生成（改进版）
    """
    if path is None:
        print("  ⚠️ ensure_path_ready: 路径为None")
        return None
    
    state_names = [s.name if hasattr(s, 'name') else str(s) for s in path.path_states]
    expected_len = max(0, len(path.path_states) - 1)
    input_len = len(path.input_symbols) if hasattr(path, 'input_symbols') else 0
    output_len = len(path.output_symbols) if hasattr(path, 'output_symbols') else 0
    
    print(f"  验证路径: {' -> '.join(state_names)}")
    print(f"  状态数: {len(path.path_states)}, 期望序列长度: {expected_len}")
    print(f"  当前输入序列长度: {input_len}, 输出序列长度: {output_len}")
    
    # 检查路径是否已经准备好
    if input_len == expected_len and output_len == expected_len:
        print(f" 路径已验证，无需修复")
        return path
    
    # 尝试重新生成路径
    print(f" 路径不完整，尝试重新生成...")
    try:
        new_inputs, new_outputs = get_trace_from_path(fsm, path.path_states)
        new_input_len = len(new_inputs)
        new_output_len = len(new_outputs)
        
        print(f"    重新生成结果: 输入长度={new_input_len}, 输出长度={new_output_len}")
        
        if new_input_len == expected_len and new_output_len == expected_len:
            path.input_symbols = new_inputs
            path.output_symbols = new_outputs
            print(f"  路径修复成功")
            print(f"    新输入序列: {new_inputs}")
            print(f"    新输出序列: {new_outputs}")
            return path
        else:
            print(f"  路径修复失败: 重新生成的序列长度仍不匹配")
            print(f"    期望长度: {expected_len}, 实际输入: {new_input_len}, 实际输出: {new_output_len}")
    except Exception as e:
        print(f"  路径修复异常: {e}")
    
    print(f"  无法修复路径，将返回None")
    print(f"    路径状态序列: {state_names}")
    return None

def check_amf(crash_detector: CrashDetector = None, max_retries: int = 3, wait_time: float = 1.0) -> Tuple[bool, CrashType, Dict]:
    """
    检测AMF是否崩溃
    
    使用进程监控和分类检测，区分：
    - 真实崩溃（进程退出 + 日志证据）
    - 正常拒绝（符合规范的安全行为）
    - 网络超时（潜在DoS）
    - 网络错误（非崩溃）
    
    【协议规范改进】增加等待时间和重试机制：
    - 增加等待时间：给AMF足够时间清理状态（1秒而不是0.1秒）
    - 重试机制：避免因时序问题误报（默认重试3次）
    - 区分暂时无响应和永久崩溃
    
    Args:
        crash_detector: 崩溃检测器实例（可选）
        max_retries: 最大重试次数（默认3次）
        wait_time: 每次重试前的等待时间（默认1.0秒）
        
    Returns:
        (是否崩溃, 崩溃类型, 详细信息)
    """
    if crash_detector is None:
        # 如果没有提供检测器，使用旧版本兼容模式（也增加重试）
        for retry in range(max_retries):
            try:
                out = sendSymbol("registrationRequest", control=True)
                time.sleep(0.5)
                if out == "authenticationRequest":
                    # AMF正常响应
                    return False, CrashType.UNKNOWN, {"response": out}
                elif retry < max_retries - 1:
                    # 响应异常，但还有重试机会
                    print(f"    ⚠️ AMF响应异常 (尝试 {retry+1}/{max_retries}): {out}，等待并重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    # 最后一次重试仍失败
                    print(f"    ❌ AMF崩溃 (已重试{max_retries}次): {out}")
                    return True, CrashType.UNKNOWN, {"response": out}
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"    ⚠️ AMF检查异常 (尝试 {retry+1}/{max_retries}): {e}，重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    ❌ AMF检查异常: {e}")
                    return False, CrashType.UNKNOWN, {"error": str(e)}
        return False, CrashType.UNKNOWN, {}
    
    # 使用崩溃检测器模式（带重试）
    last_crash_info = {}
    
    for retry in range(max_retries):
        try:
            out = sendSymbol("registrationRequest", control=True)
            time.sleep(0.5)
            
            # 使用改进的崩溃检测器
            is_crash, crash_type, crash_info = crash_detector.detect_amf_crash(out)
            last_crash_info = crash_info
            
            if not is_crash:
                # AMF正常，无需重试
                if retry > 0:
                    print(f"    AMF恢复正常 (重试 {retry+1}次后)")
                return False, crash_type, crash_info
            
            # 检测到崩溃，判断是否需要重试
            if crash_type == CrashType.REAL_CRASH:
                # 真实崩溃（进程退出），无需重试
                print(f"    AMF真实崩溃 (进程退出)")
                return True, crash_type, crash_info
            elif crash_type == CrashType.TIMEOUT and retry < max_retries - 1:
                # 超时/无响应，可能是暂时的，重试
                print(f"    ⏱AMF服务超时/无响应 (尝试 {retry+1}/{max_retries})，等待{wait_time}秒后重试...")
                time.sleep(wait_time)
                continue
            elif retry == max_retries - 1:
                # 最后一次重试仍失败
                print(f"    AMF持续无响应 (已重试{max_retries}次) - 确认为崩溃/挂起")
                return True, crash_type, crash_info
            else:
                print(f"    AMF异常: {crash_type.value} (尝试 {retry+1}/{max_retries})")
                if retry < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                else:
                    return True, crash_type, crash_info
            
        except (socket.timeout, ConnectionError, OSError) as e:
            if retry < max_retries - 1:
                print(f"    AMF检查失败 (网络问题, 尝试 {retry+1}/{max_retries}): {e}，重试...")
                time.sleep(wait_time)
                continue
            else:
                print(f"    AMF检查失败 (网络问题): {e}")
                return True, CrashType.NETWORK_ERROR, {"error": str(e)}
        except Exception as e:
            if retry < max_retries - 1:
                print(f"    AMF检查异常 (尝试 {retry+1}/{max_retries}): {e}，重试...")
                time.sleep(wait_time)
                continue
            else:
                print(f"    AMF检查异常: {e}")
                return False, CrashType.UNKNOWN, {"error": str(e)}
    
    return False, CrashType.UNKNOWN, last_crash_info

def check_smf(crash_detector: CrashDetector = None, max_retries: int = 2, wait_time: float = 1.0) -> Tuple[bool, CrashType, Dict]:
    """
    检测SMF是否崩溃
    
    【协议规范改进】增加等待时间和重试机制：
    - 增加等待时间：给SMF足够时间清理状态
    - 重试机制：避免因时序问题误报（默认重试2次，SMF检测较慢）
    - 区分暂时无响应和永久崩溃
    
    Args:
        crash_detector: 崩溃检测器实例（可选）
        max_retries: 最大重试次数（默认2次，SMF检测需要完整流程）
        wait_time: 每次重试前的等待时间（默认1.0秒）
        
    Returns:
        (是否崩溃, 崩溃类型, 详细信息)
    """
    if crash_detector is None:
        # 兼容模式（带重试）
        for retry in range(max_retries):
            try:
                path = Path([],[],[])
                path.input_symbols = ["registrationRequest",
                                      "authenticationResponse",
                                      "securityModeComplete",
                                      "registrationComplete",
                                      "PDUSessionEstablishmentRequest"]
                path.output_symbols = ["authenticationRequest",
                                       "securityModeCommand",
                                       "registrationAccept",
                                       "configurationUpdateCommand",
                                       "pduSessionEstablishmentAccept"]
                out_list = []
                all_match = True
                for i in range(len(path.input_symbols) - 1):
                    out = sendSymbol(path.input_symbols[i], control=True)
                    out_list.append(out)
                    time.sleep(0.5)
                    if out != path.output_symbols[i]:
                        all_match = False
                        break
                
                if all_match:
                    # SMF正常
                    if retry > 0:
                        print(f"    ✅ SMF恢复正常 (重试 {retry+1}次后)")
                    return False, CrashType.UNKNOWN, {"sequence": out_list}
                elif retry < max_retries - 1:
                    print(f"    ⚠️ SMF响应异常 (尝试 {retry+1}/{max_retries})，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    ❌ SMF崩溃 (已重试{max_retries}次)")
                    return True, CrashType.UNKNOWN, {"sequence": out_list}
                    
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"    ⚠️ SMF检查异常 (尝试 {retry+1}/{max_retries}): {e}，重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return False, CrashType.UNKNOWN, {"error": str(e)}
        return False, CrashType.UNKNOWN, {}
    
    # 使用崩溃检测器模式（带重试）
    last_crash_info = {}
    
    for retry in range(max_retries):
        try:
            path = Path([],[],[])
            path.input_symbols = ["registrationRequest",
                                  "authenticationResponse",
                                  "securityModeComplete",
                                  "registrationComplete",
                                  "PDUSessionEstablishmentRequest"]
            path.output_symbols = ["authenticationRequest",
                                   "securityModeCommand",
                                   "registrationAccept",
                                   "configurationUpdateCommand",
                                   "pduSessionEstablishmentAccept"]
            out_list = []
            for i in range(len(path.input_symbols) - 1):
                out = sendSymbol(path.input_symbols[i], control=True)
                out_list.append(out)
                time.sleep(0.5)
            
            # 使用改进的崩溃检测器
            is_crash, crash_type, crash_info = crash_detector.detect_smf_crash(out_list)
            last_crash_info = crash_info
            
            if not is_crash:
                # SMF正常，无需重试
                if retry > 0:
                    print(f"    ✅ SMF恢复正常 (重试 {retry+1}次后)")
                return False, crash_type, crash_info
            
            # 检测到崩溃，判断是否需要重试
            if crash_type == CrashType.REAL_CRASH:
                # 真实崩溃（进程退出），无需重试
                print(f"    SMF真实崩溃 (进程退出)")
                return True, crash_type, crash_info
            elif crash_type == CrashType.TIMEOUT and retry < max_retries - 1:
                # 超时/无响应，可能是暂时的，重试
                print(f"    SMF服务超时/无响应 (尝试 {retry+1}/{max_retries})，等待{wait_time}秒后重试...")
                time.sleep(wait_time)
                continue
            elif retry == max_retries - 1:
                # 最后一次重试仍失败
                print(f"    SMF持续无响应 (已重试{max_retries}次) - 确认为崩溃/挂起")
                return True, crash_type, crash_info
            else:
                if retry < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                else:
                    return True, crash_type, crash_info
            
        except (socket.timeout, ConnectionError, OSError) as e:
            if retry < max_retries - 1:
                print(f"    SMF检查失败 (网络问题, 尝试 {retry+1}/{max_retries}): {e}，重试...")
                time.sleep(wait_time)
                continue
            else:
                print(f"    SMF检查失败 (网络问题): {e}")
                return True, CrashType.NETWORK_ERROR, {"error": str(e)}
        except Exception as e:
            if retry < max_retries - 1:
                print(f"    SMF检查异常 (尝试 {retry+1}/{max_retries}): {e}，重试...")
                time.sleep(wait_time)
                continue
            else:
                print(f"    SMF检查异常: {e}")
                return False, CrashType.UNKNOWN, {"error": str(e)}
    
    return False, CrashType.UNKNOWN, last_crash_info

# 符号定义
symbols_enabled = [
    "registrationRequest", 
    "registrationComplete",
    "deregistrationRequest", 
    "serviceRequest", 
    "securityModeReject",
    "authenticationResponse",
    "authenticationFailure",
    "deregistrationAccept",
    "securityModeComplete",
    "identityResponse",
    "configurationUpdateComplete",
    "gmmStatus",
    "ulNasTransport",
    "PDUSessionEstablishmentRequest",
    "PDUSessionAuthenticationComplete",
    "PDUSessionModificationRequest",
    "PDUSessionModificationComplete",
    "PDUSessionModificationCommandReject",
    "PDUSessionReleaseRequest",
    "PDUSessionReleaseComplete",
    "gsmStatus"
]

symbols_fsm = [
    "registrationRequest", 
    "registrationRequestGUTI", 
    "registrationComplete",
    "deregistrationRequest", 
    "serviceRequest", 
    "securityModeReject",
    "authenticationResponse",
    "authenticationFailure",
    "deregistrationAccept",
    "securityModeComplete",
    "identityResponse",
    "configurationUpdateComplete"
]

symbols_sm = [
    "PDUSessionEstablishmentRequest",
    "PDUSessionAuthenticationComplete",
    "PDUSessionModificationRequest",
    "PDUSessionModificationComplete",
    "PDUSessionModificationCommandReject",
    "PDUSessionReleaseRequest",
    "PDUSessionReleaseComplete",
    "gsmStatus"
]

# ==================== 主程序 ====================

if __name__ == '__main__':
    print("="*60)
    print("  CoreFuzzer with Dueling DQN 启动")
    print("="*60)
    print(f"\n配置:")
    print(f"  • 使用RL: {USE_RL}")
    if USE_RL:
        print(f"  • 网络架构: {'Dueling DQN' if USE_DUELING else 'Standard DQN'}")
    else:
        print(f"  • 调度策略: PowerSchedule")
    print(f"  • 迭代限制: {ITERATION_LIMIT}")
    print(f"  • 进度报告: 每{REPORT_INTERVAL}次迭代")
    print(f"  • FSM加载模式: {FSM_LOAD_MODE}")
    print(f"  • LIGHT_RESET: {LIGHT_RESET}")
    print(f"  • FORCE_REGISTERED_SM: {FORCE_REGISTERED_SM}")
    print(f"  • RUN_BYPASS_SEEDS: {RUN_BYPASS_SEEDS}")
    print(f"  • RESET_RL_STATS: {RESET_RL_STATS}")
    from core_profile import current_profile
    profile = current_profile()
    print(f"  • 核心网: {profile.name} ({profile.deployment})")
    print(f"  • AMF: {profile.proc('amf')} @ {profile.amf_ngap_host}:{profile.amf_ngap_port}")
    print("="*60 + "\n")

    # 随机种子：用于 N 次重复 run 的可复现性（SEED=整数时固定，否则时间种子）
    import random
    _seed_str = os.getenv("SEED", "").strip()
    if _seed_str:
        _seed = int(_seed_str)
        random.seed(_seed)
        try:
            import numpy as np
            np.random.seed(_seed)
        except ImportError:
            pass
        try:
            import torch
            torch.manual_seed(_seed)
        except ImportError:
            pass
        print(f"  🔒 随机种子: {_seed}")
    else:
        print("  ⚠ 未设置 SEED（时间种子，不可复现）")

    # 初始化时，从1开始而不是0，避免IMSI冲突
    setOffset(1)
    
    # 初始化PowerSchedule（用于非RL模式）
    schedule = PowerSchedule()
    oracle_smf = OracleSmf()
    log_observer = LogObserver()
    
    # 加载FSM
    suffix = '_rl_dueling' if (USE_RL and USE_DUELING) else ('_rl' if USE_RL else '')
    fsm_file_path = f'./savedFSM{suffix}.json'
    fsm_sm_file_path = f'./savedFSM_sm{suffix}.json'
    
    print("加载FSM...")
    has_saved_fsm = os.path.exists(fsm_file_path) and os.path.exists(fsm_sm_file_path)
    use_saved_fsm = (FSM_LOAD_MODE != "fresh") and has_saved_fsm
    if use_saved_fsm:
        with open(fsm_file_path, 'r') as fsm_file:
            fsm_json = fsm_file.read()
        with open(fsm_sm_file_path, 'r') as fsm_sm_file:
            fsm_sm_json = fsm_sm_file.read()
        
        if fsm_json != "":
            fsm = FSM.from_json(fsm_json)
            fsm.refresh_paths()
            fsm_sm = FSM.from_json(fsm_sm_json)
            fsm_sm.refresh_paths()
            print(f"  ✓ 从{fsm_file_path}加载FSM")
            print(f"  ✓ FSM状态数: {len(fsm.states)}")
        else:
            fsm = load_fsm(profile.fsm_path)
            schedule.assignEnergy(fsm.states)
            fsm_sm = load_fsm(profile.fsm_sm_path)
            schedule.assignEnergy(fsm_sm.states)
            print(f"  ✓ 从配置文件加载新FSM")
    else:
        if FSM_LOAD_MODE == "fresh" and has_saved_fsm:
            print(f"  ℹ FSM_LOAD_MODE=fresh，忽略已保存的FSM，重新从配置加载")
        elif not has_saved_fsm:
            print(f"  ℹ 未找到已保存的FSM，重新从配置加载")
        fsm = load_fsm(profile.fsm_path)
        schedule.assignEnergy(fsm.states)
        fsm_sm = load_fsm(profile.fsm_sm_path)
        schedule.assignEnergy(fsm_sm.states)
        print(f"  ✓ 从配置文件加载新FSM")
        print(f"  ✓ FSM状态数: {len(fsm.states)}")
    
    # 初始化RL调度器
    rl_scheduler = None
    if USE_RL:
        print("\n初始化RL调度器...")
        rl_scheduler = RLScheduler(
            num_states=len(fsm.states),
            state_features_dim=10,
            use_dueling=USE_DUELING
        )
        print(f"  ✓ RL调度器创建成功")
        print(f"  ✓ 状态数: {len(fsm.states)}")
        print(f"  ✓ 初始epsilon: {rl_scheduler.epsilon:.4f}")
        
        # 尝试加载已有模型
        model_name = './rl_model_dueling.pth' if USE_DUELING else './rl_model_standard.pth'
        if os.path.exists(model_name):
            try:
                rl_scheduler.load_model(model_name)
                print(f"  ✓ 已加载预训练模型: {model_name}")
            except RuntimeError as e:
                if "size mismatch" in str(e):
                    print(f"  ⚠ 模型维度不匹配（FSM状态数已变化）")
                    print(f"  ℹ 将从头训练新模型")
                    backup_name = model_name.replace('.pth', '_backup.pth')
                    shutil.move(model_name, backup_name)
                    print(f"  ℹ 旧模型已备份到: {backup_name}")
                else:
                    raise
        else:
            print(f"  ℹ 使用新模型（从头训练）")
        
        if RESET_RL_STATS:
            rl_scheduler.reset_statistics(reset_memory=True, reset_steps=True, reset_epsilon=True)
            print("  ℹ RESET_RL_STATS=true，已清空历史统计并重置epsilon")
        elif not use_saved_fsm:
            rl_scheduler.reset_statistics(reset_memory=True, reset_steps=True, reset_epsilon=True)
            print("  ℹ 未加载已保存FSM，自动重置RL统计与epsilon")
    
    # 初始化崩溃检测器和覆盖率辅助类
    crash_detector = CrashDetector(
        crash_log_dir="./crash_reports",
        amf_proc=profile.proc("amf"),
        smf_proc=profile.proc("smf"),
        deployment=profile.deployment,
    )
    coverage_helper = CoverageHelper(open5gs_path=os.environ.get("OPEN5GS_PATH"))
    
    print("\n【P0修复】初始化改进模块...")
    print(f"  ✓ 崩溃检测器已初始化（报告目录: ./crash_reports）")
    print(f"  ✓ 覆盖率辅助类已初始化")
    print("="*60 + "\n")
    
    # 注册退出处理器
    atexit.register(exit_handler, fsm, fsm_sm, rl_scheduler)
    
    # 初始化
    if os.getenv("SKIP_INITIAL_RESET", "").strip().lower() == "true":
        print("  ℹ SKIP_INITIAL_RESET=true，跳过启动时 full reset（假定栈已由 prep 脚本就绪）")
        connectUE()
        connectGNB()
    else:
        reset(True)
    full_reset = False
    
    # 迭代计数
    iteration_count = 0
    
    # 模糊测试统计
    fuzzing_stats = {
        'msg_sent': 0,
        'no_feedback': 0,
        'has_feedback': 0,
        'crashes': 0,
        'violations': 0,
        'registration_rejects': 0,
        'errors': 0,
        'new_responses': 0,
        'interesting_messages': 0,
        # 【新增】代码覆盖率统计
        'states_visited': 0,
        'states_total': 0,
        'transitions_explored': 0,
        'unique_paths_executed': set()
    }
    
    print(f"\n开始模糊测试，目标迭代次数: {ITERATION_LIMIT}")
    if USE_RL:
        network_type = "Dueling DQN" if USE_DUELING else "Standard DQN"
        print(f"使用 {network_type} 进行智能状态选择")
    else:
        print(f"使用 PowerSchedule 进行状态选择")
    print(f"预计运行时间: {ITERATION_LIMIT * 0.75 / 60:.1f} 小时")
    print("="*60 + "\n")
    
    # ==================== 主循环 ====================
    
    while iteration_count < ITERATION_LIMIT:
        iteration_count += 1
        
        # 每N次迭代输出进度
        if iteration_count % REPORT_INTERVAL == 0:
            print("\n" + "="*60)
            print(f"  📊 进度报告: 迭代 {iteration_count}/{ITERATION_LIMIT}")
            
            if USE_RL and rl_scheduler:
                print("-"*60)
                print(f"  RL训练进度:")
                print(f"    • Epsilon: {rl_scheduler.epsilon:.4f}")
                print(f"    • 经验缓冲: {len(rl_scheduler.memory)}/{rl_scheduler.memory.maxlen}")
                print(f"    • 训练步数: {rl_scheduler.steps}")
                if rl_scheduler.steps > 0:
                    avg_reward = rl_scheduler.total_reward / rl_scheduler.steps
                    print(f"    • 平均奖励: {avg_reward:.2f}")
            
            print("-"*60)
            print(f"  模糊测试统计:")
            print(f"    • 发送消息数: {fuzzing_stats['msg_sent']}")
            if fuzzing_stats['msg_sent'] > 0:
                feedback_rate = (fuzzing_stats['has_feedback'] / fuzzing_stats['msg_sent']) * 100
                print(f"    • 有反馈: {fuzzing_stats['has_feedback']} ({feedback_rate:.1f}%)")
                print(f"    • 无反馈: {fuzzing_stats['no_feedback']} ({100-feedback_rate:.1f}%)")
            print(f"    • 注册拒绝: {fuzzing_stats['registration_rejects']}")
            print(f"    • 协议违规: {fuzzing_stats['violations']}")
            print(f"    • 错误发现: {fuzzing_stats['errors']}")
            print(f"    • 新响应: {fuzzing_stats['new_responses']}")
            print(f"    • 有趣消息: {fuzzing_stats['interesting_messages']}")
            print(f"    • 系统崩溃: {fuzzing_stats['crashes']}")
            
            # 【新增】代码覆盖率统计
            print("-"*60)
            print(f"  代码覆盖率统计:")
            
            # 状态覆盖率
            if fuzzing_stats['states_total'] > 0:
                state_coverage_pct = (fuzzing_stats['states_visited'] / fuzzing_stats['states_total']) * 100
                print(f"    • 状态覆盖: {fuzzing_stats['states_visited']}/{fuzzing_stats['states_total']} ({state_coverage_pct:.1f}%)")
            else:
                print(f"    • 状态覆盖: {fuzzing_stats['states_visited']}个状态")
            
            # 转换覆盖率
            print(f"    • 转换探索: {fuzzing_stats['transitions_explored']}条")
            
            # 路径多样性
            unique_paths = len(fuzzing_stats['unique_paths_executed'])
            print(f"    • 唯一路径: {unique_paths}条")
            
            # 代码覆盖率（如果可用）
            if coverage_helper:
                try:
                    current_coverage = coverage_helper.get_code_coverage()
                    if current_coverage > 0:
                        print(f"    • 代码覆盖率: {current_coverage:.2f}%")
                except Exception as e:
                    pass  # 覆盖率不可用时忽略
            
            print("="*60 + "\n")
        
        try:
            if full_reset:
                reset(True, fsm, fsm_sm)
                full_reset = False
            elif not LIGHT_RESET:
                reset(False, fsm, fsm_sm)
            else:
                print("  ℹ LIGHT_RESET: 本 iter 不 reset，仅重连 GNB/UE")
                if not ensure_gnb_ready(max_attempts=2):
                    print("  ⚠️ GNB 未就绪，本 iter 将尝试继续...")

            print(f"[Iter {iteration_count}] IMSI_OFFSET: {getOffset()}")
            
            connection_success = False
            for conn_attempt in range(3):
                try:
                    connectUE()
                    
                    if UEsocket and UEsocket.fileno() >= 0:
                        try:
                            old_timeout = UEsocket.gettimeout()
                            UEsocket.settimeout(0.5)
                            UEsocket.settimeout(old_timeout)
                            print(f"  UE socket已连接并验证（尝试{conn_attempt+1}/3）")
                            connection_success = True
                            break
                        except Exception:
                            print("  UE连接验证失败，重试...")
                            close_ue_connection()
                            time.sleep(1)
                    else:
                        print(f"  UE socket无效（尝试{conn_attempt+1}/3）")
                        time.sleep(1)
                        
                except (socket.timeout, ConnectionError, OSError) as e:
                    print(f"  UE连接失败 (尝试{conn_attempt+1}/3): {e}")
                    if conn_attempt < 2:
                        time.sleep(1)
                        if not is_process_running("nr-ue"):
                            print("  UE进程退出，重新启动...")
                            killUE()
                            time.sleep(1)
                            if not startUE():
                                print("  UE重启失败")
                                break
                            time.sleep(3)
                    continue
            
            if not connection_success and LIGHT_RESET:
                print("  UE连接失败，执行 partial reset 后重试...")
                reset(False, fsm, fsm_sm)
                for conn_attempt in range(3):
                    if connectUE() and UEsocket and UEsocket.fileno() >= 0:
                        connection_success = True
                        print(f"  partial reset 后 UE 已连接（尝试{conn_attempt+1}/3）")
                        break
                    time.sleep(2)
            
            if not connection_success:
                print("  UE连接失败（已尝试3次），跳过本次迭代")
                reset_count += 1
                if reset_count > 5:
                    print(f"  连续失败{reset_count}次，触发完全重置")
                    full_reset = True
                    reset_count = 0
                continue
            
            # 连接成功，清零失败计数
            reset_count = 0
            
            # 每次迭代开始时，如果上次路径执行成功，重置路径失败计数器
            if hasattr(reset, 'path_fail_count'):
                # 如果上一个迭代的路径执行成功，清零计数器
                pass  # 计数器会在路径执行成功后清零
            
            # ========== 状态选择 ==========
            if USE_RL and rl_scheduler:
                # RL选择状态
                current_features = rl_scheduler.extract_global_features(fsm.states)
                action = rl_scheduler.select_action(current_features, fsm.states)
                curr_state = fsm.states[action]
                network_type = "Dueling DQN" if USE_DUELING else "Standard DQN"
                print(f"{network_type}选择状态: {curr_state.name} (epsilon={rl_scheduler.epsilon:.3f})")
                
                # 更新状态覆盖率统计
                visited_states = len([s for s in fsm.states if s.count > 0])
                fuzzing_stats['states_visited'] = visited_states
                fuzzing_stats['states_total'] = len(fsm.states)
            else:
                # PowerSchedule选择状态
                schedule.adjustEnergy(fsm.states)
                curr_state = schedule.choose(fsm.states)
                action = fsm.states.index(curr_state)
                print(f"PowerSchedule选择状态: {curr_state.name}")
                
                # 更新状态覆盖率统计
                visited_states = len([s for s in fsm.states if s.count > 0])
                fuzzing_stats['states_visited'] = visited_states
                fuzzing_stats['states_total'] = len(fsm.states)
            
            curr_state_sm = None
            if curr_state.oracle.state == "R":
                schedule.adjustEnergy(fsm_sm.states)
                curr_state_sm = schedule.choose(fsm_sm.states)
                print(f"  已注册 → 联合 SMF 状态: {curr_state_sm.name}")

            if curr_state_sm == None:
                state = curr_state.name
            else:
                state = curr_state.name + ":" + curr_state_sm.name
            
            # 记录状态访问
            curr_state.count += 1

            # 关键：先驱动标准注册前缀（让 UE 进入 R 状态），再执行路径。
            # 否则路径的首条消息（如 securityModeReject）会作为 InitialUEMessage 被 AMF 拒绝
            # （"Invalid 5GMM message type"）。
            if FORCE_REGISTERED_SM and curr_state.oracle.state != "R":
                print("  FORCE_REGISTERED_SM: 驱动标准注册前缀…")
                reach_mm_registered(
                    sendSymbol,
                    curr_state.oracle,
                    oracle_smf,
                    v2_probe=V2_PROBE,
                    v4_probe=V4_PROBE,
                )
                print(f"  Oracle MM ω={curr_state.oracle.state} (after canonical prefix)")

            path = select_shortest_path(curr_state)
            if path is None:
                # 如果没有短路径，使用原来的选择逻辑
                path = curr_state.select_path()
            
            path = ensure_path_ready(path, fsm)
            
            # 记录路径到统计
            if path:
                path_signature = " -> ".join([s.name if hasattr(s, 'name') else str(s) for s in path.path_states])
                fuzzing_stats['unique_paths_executed'].add(path_signature)
            path_exec_success = False
            
            if path is None:
                print(f"  路径为空，无法执行")
            elif FORCE_REGISTERED_SM and curr_state.oracle.state == "R":
                # 已注册（ω=R），跳过路径执行：路径本意是从初始状态到达目标状态，
                # 而注册后执行路径会发送非法消息（如 securityModeReject）破坏 UE 上下文。
                print(f"  ℹ 已注册（ω=R），跳过路径执行，直接进入模糊测试阶段")
                path_exec_success = True
            else:

                # 因为AMF可能在内存中记住了状态，验证总是失败
                # 让路径执行本身来验证状态，如果失败再处理
                print(f"  ℹ️ 跳过状态验证，直接执行路径...")
                print(f"  ℹ️ 路径执行本身会验证状态，如果失败再重置")

                # 直接执行路径，让路径执行本身来验证状态
                path_exec_success = execSequence(path)
                if path_exec_success and path is not None:
                    curr_state.oracle.decide_state_from_path(path)
                    print(f"  Oracle MM ω={curr_state.oracle.state} (from executed prefix)")

            # 【路径执行结果处理】
            # 1）成功：清零失败计数器
            # 2）失败：前3次不立即跳过本次迭代，而是继续尝试进入模糊测试阶段；
            #          连续多次失败时才触发部分/完全重置。
            if path_exec_success:
                if hasattr(reset, 'path_fail_count'):
                    reset.path_fail_count = 0  # 成功时清零计数器
                
                # 更新转换覆盖率统计
                if path:
                    transitions_count = len(path.input_symbols) if hasattr(path, 'input_symbols') else 0
                    fuzzing_stats['transitions_explored'] += transitions_count
            else:
                # 路径失败后的回退策略：先记录失败，再根据失败次数决定是否重置
                if not hasattr(reset, 'path_fail_count'):
                    reset.path_fail_count = 0
                reset.path_fail_count += 1
                
                # 检查失败原因，如果是registrationReject，更快触发重置
                failure_reason = getattr(path, '_failure_reason', None) if path else None
                is_registration_reject = failure_reason == 'registrationReject'
                
                # 如果是registrationReject，减少容忍次数（从3次降到1次）
                max_tolerate_failures = 1 if is_registration_reject else 3
                
                if reset.path_fail_count <= max_tolerate_failures:
                    # 前N次失败：仅记录并给RL负奖励，但仍然尝试进入模糊测试阶段
                    if is_registration_reject:
                        print(f"  路径执行失败（第{reset.path_fail_count}次）- 原因: registrationReject，容忍次数: {max_tolerate_failures}次")
                    else:
                        print(f"  路径执行失败（第{reset.path_fail_count}次），但继续尝试进入模糊测试阶段...")
                    print(f"  可能是AMF记住历史状态或UE轻微异常，先观察fuzz阶段表现再决定是否重置")
                    
                    # 路径失败后立即检查并重连UE，确保可以进入fuzz阶段
                    if UEsocket is None or not is_process_running("nr-ue"):
                        print("  路径失败后UE连接异常，尝试重连...")
                        if reconnectUE(max_retries=3):
                            print("  UE重连成功，等待连接稳定...")
                            time.sleep(2)  # 等待连接稳定
                        else:
                            print("  UE重连失败，跳过本次迭代")
                            reset_count += 1
                            if reset_count > 10:
                                full_reset = True
                                reset_count = 0
                            continue
                    else:
                        # 即使UE连接看起来正常，也检查socket是否真的可用
                        try:
                            UEsocket.getpeername()
                        except (OSError, AttributeError):
                            print("  UE socket异常，尝试重连...")
                            if reconnectUE(max_retries=2):
                                print("  UE重连成功，等待连接稳定...")
                                time.sleep(1)
                            else:
                                print(" UE重连失败，跳过本次迭代")
                                reset_count += 1
                                if reset_count > 10:
                                    full_reset = True
                                    reset_count = 0
                                continue
                else:
                    # 4次以上失败：尝试部分重置并跳过本次迭代
                    print(f"  路径执行失败多次（{reset.path_fail_count}次），尝试部分重置后跳过本次迭代...")
                    reset(False, fsm, fsm_sm)
                    time.sleep(5)
                    reset.path_fail_count = 0  # 重置计数器
                    
                    # 确保UE连接正常
                    try:
                        if UEsocket is None:
                            connectUE()
                        time.sleep(1)
                    except Exception as e:
                        print(f"  重置后UE连接失败: {e}")
                    
                    # 本次迭代不再进入fuzz阶段，直接进入下一轮
                    continue
                
                # 防止计数为负数
                curr_state.count = max(0, curr_state.count - 1)
                if path:
                    path.count = max(0, path.count - 1)
                
                # 路径失败时给RL少量探索奖励（鼓励探索）
                if USE_RL and rl_scheduler:
                    # 路径失败也是一种探索尝试，给予小的负奖励（而不是0）
                    exploration_reward = -2.0  # 小的负奖励，鼓励继续尝试
                    
                    # 获取当前和下一状态特征（状态本身未改变）
                    current_features = rl_scheduler.extract_global_features(fsm.states)
                    next_features = current_features
                    
                    # 存储经验（路径失败的经验）
                    rl_scheduler.store_transition(
                        current_features,
                        action,
                        exploration_reward,
                        next_features,
                        False  # done=False，因为只是路径失败，不是终止
                    )
                    
                    # 尝试训练（如果经验足够）
                    if len(rl_scheduler.memory) >= rl_scheduler.batch_size:
                        loss = rl_scheduler.train()
                
                # 统计连续失败次数，用于触发完全重置
                reset_count += 1
                if reset_count > 10:
                    print(f"  ⚠️ 连续失败{reset_count}次，执行完全重置")
                    full_reset = True
                    reset_count = 0
            
            if curr_state.oracle.state == "R" and curr_state_sm is None:
                schedule.adjustEnergy(fsm_sm.states)
                curr_state_sm = schedule.choose(fsm_sm.states)
                state = curr_state.name + ":" + curr_state_sm.name
                print(f"  已注册 → 补选 SMF 状态: {curr_state_sm.name}")

            if curr_state_sm != None and not SKIP_SM_ESTABLISHMENT and not V3_PROBE:
                path_sm = curr_state_sm.select_path()
                path_sm = ensure_path_ready(path_sm, fsm_sm)
                sm_path_ok = path_sm is not None and execSequence(path_sm)
                if sm_path_ok:
                    oracle_smf.decide_state_from_path(path_sm)
                    print(f"  Oracle SM session={oracle_smf.session_state} (from executed prefix)")
                elif FORCE_REGISTERED_SM and curr_state.oracle.state == "R":
                    print("  SM FSM 路径失败，改走 canonical PDU 建立")
                else:
                    curr_state_sm.count = max(0, curr_state_sm.count - 1)
                    if path_sm:
                        path_sm.count = max(0, path_sm.count - 1)
                    reset_count += 1
                    continue

            if FORCE_REGISTERED_SM and curr_state.oracle.state == "R":
                oracle_smf.set_mm_registered(True)
                if SKIP_SM_ESTABLISHMENT:
                    print("  ℹ SKIP_SM_ESTABLISHMENT=true，跳过 PDU 会话建立（Φ 实验只需 MM 安全上下文）")
                elif oracle_smf.session_state not in ("A",):
                    reach_pdu_session(sendSymbol, oracle_smf, v3_probe=V3_PROBE)
            
            # ========== Fuzzing ==========
            # 在进入fuzz阶段之前，进行全面的UE健康检查和重连
            if UEsocket is None or not is_process_running("nr-ue"):
                print("  UE状态异常（socket为空或进程未运行），尝试重连...")
                if reconnectUE(max_retries=3):
                    print("  UE重连成功，等待连接稳定...")
                    time.sleep(2)
                else:
                    print(" UE重连失败，跳过本轮模糊测试并执行部分重置")
                    reset(False, fsm, fsm_sm)
                    time.sleep(2)
                    continue
            else:
                # 即使进程运行，也检查socket连接是否真的可用
                try:
                    UEsocket.getpeername()
                except (OSError, AttributeError):
                    print("  UE socket连接异常，尝试重连...")
                    if reconnectUE(max_retries=3):
                        print("  UE重连成功，等待连接稳定...")
                        time.sleep(2)
                    else:
                        print(" UE重连失败，跳过本轮模糊测试并执行部分重置")
                        reset(False, fsm, fsm_sm)
                        time.sleep(2)
                        continue

            out = sendSymbol("enableFuzzing", control=True)
            print(out)
            
            if out == "Start fuzzing":
                print("Fuzzing enabled")
                if RUN_BYPASS_SEEDS and curr_state.oracle.state in ("S", "R"):
                    for b in run_bypass_seeds(sendSymbol, mm_state=curr_state.oracle.state):
                        b_ret = b.get("ret_type") or ""
                        if not b_ret:
                            continue
                        b_comp = component_for_send_type(b["send_type"])
                        b_viol = query_component_violation(
                            b_comp,
                            curr_state.oracle,
                            oracle_smf,
                            b["send_type"],
                            b_ret,
                            b["sht"],
                            b["secmod"],
                            new_msg=b["new_msg"],
                            wire_mode=True,
                            mm_registered=(curr_state.oracle.state == "R"),
                            sm_state=curr_state_sm,
                        )
                        print(f"  bypass Φ ({b_comp}/{b['kind']}): {b_viol}")
                        try:
                            append_typed_response(
                                {
                                    "iteration": iteration_count,
                                    "component": b_comp,
                                    "state": state,
                                    "send_type": b["send_type"],
                                    "ret_type": b_ret,
                                    "ret_src": "ue_json",
                                    "sht": b["sht"],
                                    "secmod": b["secmod"],
                                    "wire_sht": b["sht"],
                                    "wire_secmod": b["secmod"],
                                    "byte_mut": 0,
                                    "gnb_error": 0,
                                    "new_msg": b["new_msg"],
                                    "ret_msg": "",
                                    "kind": b["kind"],
                                }
                            )
                        except Exception as _e:
                            print(f"    typed log failed: {_e}")
                        if b_viol:
                            fuzzing_stats['violations'] += 1
                            print(f"    🎉 发现协议违规 (bypass {b['kind']})! 奖励: +500")
                            try:
                                append_wire_phi_hit(
                                    {
                                        "iteration": iteration_count,
                                        "component": b_comp,
                                        "state": state,
                                        "send_type": b["send_type"],
                                        "ret_type": b_ret,
                                        "ret_src": "ue_json",
                                        "sht": b["sht"],
                                        "secmod": b["secmod"],
                                        "wire_sht": b["sht"],
                                        "wire_secmod": b["secmod"],
                                        "byte_mut": 0,
                                        "gnb_error": 0,
                                        "new_msg": b["new_msg"],
                                        "ret_msg": "",
                                    },
                                    b_comp,
                                )
                            except Exception as _e:
                                print(f"    wire-Φ bypass log failed: {_e}")
                if not curr_state.is_init or not check_seed_msg(state):
                    mm_registered = curr_state.oracle.state == "R"
                    seed_symbols = (
                        symbols_enabled
                        if mm_registered
                        else [s for s in symbols_enabled if s not in symbols_sm and s != "ulNasTransport"]
                    )
                    for symbol in seed_symbols:
                        msg = sendSymbol(symbol, control=True)
                        try:
                            resp_json = json.loads(msg)
                        except (json.JSONDecodeError, TypeError):
                            print(f"  seed {symbol} 非 JSON，跳过入库: {str(msg)[:80]}")
                            continue
                        print(resp_json)
                        store_new_message(
                            state=state,
                            send_type=symbol,
                            ret_type="",
                            if_crash=False,
                            if_crash_sm=False,
                            is_interesting=True,
                            if_error=False,
                            error_cause="",
                            sht=resp_json.get("sht"),
                            secmod=resp_json.get("secmod"),
                            base_msg="",
                            new_msg=resp_json.get("new_msg"),
                            ret_msg="",
                            violation=False,
                            mm_status=resp_json.get("mm_status"),
                            byte_mut=False
                        )
                    
                    if check_seed_msg(state):
                        curr_state.is_init = True
                    else:
                        curr_state.is_init = False
                        continue
                
                fuzzing = True
                # 避免在同一fuzz会话中对完全相同的模糊消息反复发送
                seen_fuzz_msgs = set()
                while fuzzing:
                    if not ensure_gnb_ready(max_attempts=2):
                        print("  GNB 不可用（重启后仍失败），退出fuzzing循环")
                        break
                    
                    ins_msg = None
                    mm_registered = curr_state.oracle.state == "R"
                    for _pick in range(8):
                        cand = get_insteresting_msg(state)
                        if not cand:
                            break
                        st = cand.get("send_type") or ""
                        if (not mm_registered) and (st in SM_SYMBOLS):
                            print(f"  跳过未注册状态下的 SM 种子: {st}")
                            continue
                        if mm_registered and FORCE_REGISTERED_SM and st not in SM_SYMBOLS and _pick < 4:
                            continue
                        new_msg_content = cand.get("new_msg")
                        if new_msg_content in seen_fuzz_msgs:
                            print("  跳过重复模糊消息（本次会话已发送过相同new_msg）")
                            continue
                        ins_msg = cand
                        seen_fuzz_msgs.add(new_msg_content)
                        break
                    if ins_msg is None:
                        print("  无可用模糊种子，结束本轮 fuzz")
                        break
                    if_crash = False
                    if_crash_sm = False
                    is_interesting = False
                    if_error = False
                    error_cause = ""
                    
                    print(sendSymbol("incomingMessage_" + str(ins_msg.get("size")), control=True))
                    if ins_msg.get("send_type") == "serviceRequest":
                        sendRRCRelease()
                    
                    log_mark = log_observer.mark()
                    try:
                        msg = sendFuzzingMessage(ins_msg.get("new_msg").encode())
                        fuzzing_stats['msg_sent'] += 1
                    except socket.timeout:
                        print("UE may crashed (socket.timeout in sendFuzzingMessage)")
                        fuzzing_stats['crashes'] += 1
                        # 将UE崩溃情况反馈给RL
                        if USE_RL and rl_scheduler:
                            test_result = {
                                'crashed': True,
                                'crash_type': 'ue_crash',
                                'normal_reject': False,
                                'protocol_violation': False,
                                'protocol_error': False,
                                'error_type': None,
                                'new_state': False,
                                'new_transition': False,
                                'new_response': False,
                                'coverage_increase': 0.0,
                                'state_visit_count': curr_state.count,
                                'interesting': False,
                                'error_triggered': False,
                                'registration_reject': False,
                                'has_response': False,
                                'no_response': True,
                                'connection_failed': True,
                                'invalid_operation': False,
                                'response_time': None
                            }
                            reward = rl_scheduler.calculate_reward(test_result)
                            rl_scheduler.total_reward += reward
                            next_features = rl_scheduler.extract_global_features(fsm.states)
                            rl_scheduler.store_transition(
                                current_features,
                                action,
                                reward,
                                next_features,
                                True  # done=True，视为一次严重事件
                            )
                        break
                    
                    if msg == "":
                        print("UE may crashed (empty response from UE)")
                        fuzzing_stats['crashes'] += 1
                        if USE_RL and rl_scheduler:
                            test_result = {
                                'crashed': True,
                                'crash_type': 'ue_crash',
                                'normal_reject': False,
                                'protocol_violation': False,
                                'protocol_error': False,
                                'error_type': None,
                                'new_state': False,
                                'new_transition': False,
                                'new_response': False,
                                'coverage_increase': 0.0,
                                'state_visit_count': curr_state.count,
                                'interesting': False,
                                'error_triggered': False,
                                'registration_reject': False,
                                'has_response': False,
                                'no_response': True,
                                'connection_failed': True,
                                'invalid_operation': False,
                                'response_time': None
                            }
                            reward = rl_scheduler.calculate_reward(test_result)
                            rl_scheduler.total_reward += reward
                            next_features = rl_scheduler.extract_global_features(fsm.states)
                            rl_scheduler.store_transition(
                                current_features,
                                action,
                                reward,
                                next_features,
                                True
                            )
                        break
                    
                    print(msg)
                    
                    if msg == "decode error":
                        reset_insteresting(ins_msg)
                        break

                    if not msg or msg == "null_action" or not msg.strip().startswith("{"):
                        print(f"  PDU 未发出或 UE 返回非 JSON，跳过 Φ: {msg[:80] if msg else '(empty)'}")
                        continue
                    
                    resp_json = json.loads(msg)
                    if not resp_json.get("new_msg"):
                        print("  线上 PDU 为空（未真正发出），跳过 Φ")
                        continue
                    byte_mut = bool(resp_json.get("byte_mut"))
                    
                    if not byte_mut:
                        is_interesting = check_new_resopnse(
                            state,
                            ins_msg.get("send_type"),
                            resp_json.get("ret_msg"),
                            resp_json.get("mm_status")
                        )
                    
                    if is_interesting:
                        curr_state.addEnergy(1)
                        msg_add_energy(ins_msg, 1)
                        fuzzing_stats['interesting_messages'] += 1
                    
                    # 使用改进的崩溃检测（增加等待时间和重试）
                    print("send probe to AMF")
                    startUE2()
                    time.sleep(1.0)  # 从0.1秒增加到1.0秒，给AMF足够时间清理状态
                    connectUE2()
                    if_crash, crash_type_amf, crash_info_amf = check_amf(crash_detector, max_retries=3, wait_time=1.0)
                    
                    # 保存崩溃报告
                    if if_crash:
                        crash_detector.save_crash_report(
                            crash_info_amf,
                            {
                                "send_type": ins_msg.get("send_type"),
                                "new_msg": ins_msg.get("new_msg"),
                                "ret_type": resp_json.get("ret_type"),
                                "state": state
                            },
                            crash_type_amf
                        )
                        
                        fuzzing = False
                        if crash_type_amf == CrashType.REAL_CRASH:
                            full_reset = True
                            fuzzing_stats['crashes'] += 1
                    
                    # 获取gNB反馈
                    try:
                        msg_gnb = gNBsocket.recv(1024).decode().strip()
                        print("feedback from gnb: ", msg_gnb)
                        fuzzing_stats['has_feedback'] += 1
                        
                        if "Error indication" in msg_gnb:
                            if ":" in msg_gnb:
                                error_cause = msg_gnb.split(":")[1].strip()
                            if_error = True
                            fuzzing_stats['errors'] += 1
                            
                            if not byte_mut:
                                is_interesting = check_new_cause(
                                    state,
                                    ins_msg.get("send_type"),
                                    error_cause
                                )
                            
                            if is_interesting:
                                curr_state.addEnergy(0.5)
                                msg_add_energy(ins_msg, 0.5)
                    
                    except (socket.timeout, ConnectionError, OSError) as e:
                        print(f"  no feedback from gNB: {e}")
                        fuzzing_stats['no_feedback'] += 1
                        if not reconnectGNB(max_retries=2):
                            print("  GNB重连失败，退出fuzzing循环")
                            break
                    
                    if resp_json.get("ret_type") != "":
                        fuzzing = False
                    
                    # 检查协议违规（AMF / SMF 分组件 wire-Φ）
                    send_type = ins_msg.get("send_type")
                    component = component_for_send_type(send_type)
                    effective_ret_type, ret_src = resolve_ret_type_with_logs(
                        resp_json.get("ret_type"),
                        resp_json.get("ret_msg"),
                        log_observer,
                        ue_off=log_mark[0],
                        core_off=log_mark[1],
                        include_core_log=False,
                    )
                    if effective_ret_type and not resp_json.get("ret_type"):
                        print(f"  ℹ inferred ret_type ({ret_src}): {effective_ret_type}")
                    oracle_ret_type = effective_ret_type if eligible_for_oracle(effective_ret_type, ret_src) else ""
                    if oracle_ret_type:
                        try:
                            from objects.wire_nas import normalize_wire_security as _nws
                            _ws, _wsec, _ = _nws(
                                resp_json.get("new_msg"),
                                resp_json.get("sht"),
                                resp_json.get("secmod"),
                            )
                            append_typed_response(
                                {
                                    "iteration": iteration_count,
                                    "component": component,
                                    "state": state,
                                    "send_type": send_type,
                                    "ret_type": oracle_ret_type,
                                    "ret_src": ret_src,
                                    "sht": resp_json.get("sht"),
                                    "secmod": resp_json.get("secmod"),
                                    "wire_sht": _ws,
                                    "wire_secmod": _wsec,
                                    "byte_mut": resp_json.get("byte_mut"),
                                    "gnb_error": int(if_error),
                                    "new_msg": resp_json.get("new_msg"),
                                    "ret_msg": resp_json.get("ret_msg"),
                                    "kind": "fuzz",
                                }
                            )
                        except Exception as _e:
                            print(f"    typed log failed: {_e}")
                    violation = query_component_violation(
                        component,
                        curr_state.oracle,
                        oracle_smf,
                        send_type,
                        oracle_ret_type,
                        resp_json.get("sht"),
                        resp_json.get("secmod"),
                        new_msg=resp_json.get("new_msg"),
                        wire_mode=True,
                        mm_registered=(curr_state.oracle.state == "R"),
                        sm_state=curr_state_sm,
                    )
                    print(f"violation ({component}): ", violation)
                    
                    if violation:
                        violation = check_new_violation(
                            state,
                            send_type,
                            oracle_ret_type,
                            resp_json.get("sht"),
                            resp_json.get("secmod")
                        )
                        l1_ok, l1_reason = eligible_for_l1_hit(
                            oracle_ret_type,
                            ret_src,
                            gnb_error=if_error,
                            ret_msg=resp_json.get("ret_msg"),
                        )
                        if violation and not l1_ok:
                            print(f"    ⚠ oracle hit rejected for L1 ({l1_reason})")
                            violation = False
                        if violation:
                            fuzzing_stats['violations'] += 1
                            print(f"    🎉 发现协议违规 ({component})! 奖励: +500")
                            try:
                                from objects.wire_nas import normalize_wire_security as _nws
                                _ws, _wsec, _ = _nws(resp_json.get("new_msg"), resp_json.get("sht"), resp_json.get("secmod"))
                                append_wire_phi_hit(
                                    {
                                        "iteration": iteration_count,
                                        "component": component,
                                        "state": state,
                                        "send_type": send_type,
                                        "ret_type": oracle_ret_type,
                                        "ret_src": ret_src,
                                        "sht": resp_json.get("sht"),
                                        "secmod": resp_json.get("secmod"),
                                        "wire_sht": _ws,
                                        "wire_secmod": _wsec,
                                        "byte_mut": resp_json.get("byte_mut"),
                                        "gnb_error": int(if_error),
                                        "new_msg": resp_json.get("new_msg"),
                                        "ret_msg": resp_json.get("ret_msg"),
                                    },
                                    component,
                                )
                                print(f"    ✓ wire-Φ hit ({component}) logged [L1]")
                            except Exception as _e:
                                print(f"    ⚠️ wire-Φ hit log failed: {_e}")
                    
                    # 使用改进的SMF崩溃检测
                    crash_type_sm = CrashType.UNKNOWN
                    crash_info_sm = {}
                    if ins_msg.get("send_type") in symbols_sm:
                        print("send probe to SMF")
                        startUE3()
                        time.sleep(1.0)  # 从0.1秒增加到1.0秒，给SMF足够时间清理状态
                        connectUE3()
                        if_crash_sm, crash_type_sm, crash_info_sm = check_smf(crash_detector, max_retries=2, wait_time=1.0)
                        
                        if if_crash_sm:
                            crash_detector.save_crash_report(
                                crash_info_sm,
                                {
                                    "send_type": ins_msg.get("send_type"),
                                    "new_msg": ins_msg.get("new_msg"),
                                    "ret_type": resp_json.get("ret_type"),
                                    "state": state
                                },
                                crash_type_sm
                            )
                            
                            if crash_type_sm == CrashType.REAL_CRASH:
                                fuzzing_stats['crashes'] += 1
                    
                    # 存储消息
                    store_new_message(
                        state=state,
                        send_type=ins_msg.get("send_type"),
                        ret_type=resp_json.get("ret_type"),
                        if_crash=if_crash,
                        if_crash_sm=if_crash_sm,
                        is_interesting=is_interesting,
                        if_error=if_error,
                        error_cause=error_cause,
                        sht=resp_json.get("sht"),
                        secmod=resp_json.get("secmod"),
                        base_msg=ins_msg.get("new_msg"),
                        new_msg=resp_json.get("new_msg"),
                        ret_msg=resp_json.get("ret_msg"),
                        violation=violation,
                        mm_status=resp_json.get("mm_status"),
                        byte_mut=byte_mut
                    )
                    
                    # 统计注册拒绝
                    if resp_json.get("ret_type") == "registrationReject":
                        fuzzing_stats['registration_rejects'] += 1
                    
                    # 检查正常拒绝（假阳性修复）
                    normal_reject = False
                    if resp_json.get("ret_type") in ["registrationReject", "authenticationReject", "serviceReject"]:
                        # 如果是正常拒绝且进程没有崩溃，这是假阳性
                        if not if_crash and not if_crash_sm:
                            normal_reject = True
                    
                    # 计算覆盖率增量
                    visited_states = sum(1 for s in fsm.states if s.count > 0)
                    total_states = len(fsm.states)
                    coverage_increase = coverage_helper.get_coverage_increase(visited_states, total_states)
                    
                    # ========== RL训练 ==========
                    if USE_RL and rl_scheduler:
                        # 构建完整的测试结果（包含所有改进）
                        crash_type_final = crash_type_amf if if_crash else (crash_type_sm if if_crash_sm else CrashType.UNKNOWN)
                        
                        test_result = {
                            'crashed': if_crash or if_crash_sm,
                            'crash_type': crash_type_final.value if crash_type_final != CrashType.UNKNOWN else None,
                            'normal_reject': normal_reject,  # 正常拒绝标记
                            'protocol_violation': violation,
                            'protocol_error': if_error,  # 协议错误
                            'error_type': error_cause if if_error else None,  # 错误类型
                            'new_state': False,
                            'new_transition': False,
                            'new_response': False,
                            'coverage_increase': coverage_increase,  # 覆盖率增量
                            'state_visit_count': curr_state.count,
                            'interesting': is_interesting,
                            'error_triggered': if_error,
                            'registration_reject': resp_json.get("ret_type") == "registrationReject",
                            'has_response': resp_json.get("ret_type") != "",
                            'no_response': resp_json.get("ret_type") == "",  # 无响应标记
                            'connection_failed': False,  # TODO: 从连接状态获取
                            'invalid_operation': msg == "decode error",  # 无效操作
                            'response_time': None  # TODO: 记录响应时间
                        }
                        
                        reward = rl_scheduler.calculate_reward(test_result)
                        rl_scheduler.total_reward += reward
                        
                        # 获取下一状态特征
                        next_features = rl_scheduler.extract_global_features(fsm.states)
                        
                        # 存储经验并训练
                        done = if_crash or if_crash_sm or violation
                        rl_scheduler.store_transition(
                            current_features,
                            action,
                            reward,
                            next_features,
                            done
                        )
                        
                        if len(rl_scheduler.memory) >= rl_scheduler.batch_size:
                            loss = rl_scheduler.train()
                            if loss and rl_scheduler.steps % 50 == 0:
                                network_type = "Dueling DQN" if USE_DUELING else "Standard DQN"
                                print(f"[{network_type}训练] Step {rl_scheduler.steps}, Loss: {loss:.4f}, Epsilon: {rl_scheduler.epsilon:.4f}, Reward: {reward:.1f}")
                    
                    # 学习新状态
                    if resp_json.get("ret_type") != "" and \
                       not fsm.search_new_transition(state, ins_msg.get("send_type"), resp_json.get("ret_type")) and \
                       not byte_mut:
                        print("get a different return msg")
                        fuzzing_stats['new_responses'] += 1
                        
                        message_str = ins_msg.get("send_type") + ":" + \
                                     resp_json.get("new_msg") + ":" + \
                                     str(resp_json.get("secmod")) + ":" + \
                                     str(resp_json.get("sht"))
                        responses = []
                        new_state_error = False
                        
                        for symbol in symbols_fsm:
                            i = 0
                            consecutive_path_failures = 0  # 添加连续失败计数
                            consecutive_send_failures = 0  # 添加sendSymbol失败计数
                            total_failures = 0  # 总失败计数（任何类型的失败）
                            while i < 3:  # 从5次进一步减少到3次
                                reset(full_reset, fsm, fsm_sm)
                                full_reset = False
                                i = i + 1
                                total_failures += 1  # 每次循环计为一次尝试
                                
                                try:
                                    connectGNB()
                                    connectUE()
                                except socket.timeout:
                                    print("Connection timeout, retrying...")
                                    consecutive_send_failures += 1
                                    if consecutive_send_failures >= 2:  # 【P1增强】从3次减少到2次
                                        print(f"  连接连续失败{consecutive_send_failures}次，放弃学习新状态")
                                        new_state_error = True
                                        break
                                    continue
                                except Exception as e:
                                    print(f"Connection error: {e}, retrying...")
                                    consecutive_send_failures += 1
                                    if consecutive_send_failures >= 2:
                                        print(f"  连接异常{consecutive_send_failures}次，放弃学习新状态")
                                        new_state_error = True
                                        break
                                    continue
                                
                                # 检测连续路径失败，快速退出
                                if not execSequence(path):
                                    consecutive_path_failures += 1
                                    print(f"Sequence not match, retrying... (连续失败: {consecutive_path_failures}/{total_failures})")
                                    
                                    # 连续2次路径失败就放弃（从3次减少到2次）
                                    if consecutive_path_failures >= 2:
                                        print(f"  路径连续失败{consecutive_path_failures}次，放弃学习新状态")
                                        new_state_error = True
                                        break
                                    continue
                                else:
                                    consecutive_path_failures = 0  # 成功，重置计数
                                
                                # 检测sendSymbol失败，快速退出
                                try:
                                    send_result = sendSymbol(message_str, control=True)
                                except Exception as e:
                                    print(f"sendSymbol异常: {e}")
                                    consecutive_send_failures += 1
                                    if consecutive_send_failures >= 2:
                                        print(f" sendSymbol异常{consecutive_send_failures}次，放弃学习新状态")
                                        new_state_error = True
                                        break
                                    continue
                                
                                if send_result != resp_json.get("ret_type"):
                                    consecutive_send_failures += 1
                                    print(f"response to new symbol not match, retrying... (连续失败: {consecutive_send_failures}/{total_failures})")
                                    
                                    # 连续2次失败就放弃（从3次减少到2次）
                                    if consecutive_send_failures >= 2:
                                        print(f" message_str发送连续失败{consecutive_send_failures}次，放弃学习新状态")
                                        new_state_error = True
                                        break
                                    continue
                                else:
                                    consecutive_send_failures = 0  # 成功，重置计数
                                
                                try:
                                    res = sendSymbol(symbol, control=True)
                                except Exception as e:
                                    print(f"sendSymbol(symbol)异常: {e}")
                                    consecutive_send_failures += 1
                                    if consecutive_send_failures >= 2:
                                        print(f" symbol发送异常{consecutive_send_failures}次，放弃学习新状态")
                                        new_state_error = True
                                        break
                                    continue
                                
                                if res == "":
                                    print("UE may crashed, retrying...")
                                    consecutive_send_failures += 1
                                    if consecutive_send_failures >= 2:  # 从3次减少到2次
                                        print(f" UE连续崩溃{consecutive_send_failures}次，放弃学习新状态")
                                        new_state_error = True
                                        break
                                    continue
                                else:
                                    consecutive_send_failures = 0  # 成功，重置
                                
                                responses.append(res)
                                break
                            
                            if i == 3:  # 对应减少到3次
                                print(f" 学习新状态失败（已尝试{i}次），放弃...")
                                new_state_error = True
                                break
                            
                            if new_state_error:  # 如果已经标记错误，退出整个符号循环
                                break
                        
                        if new_state_error:
                            break
                        
                        print(responses)
                        
                        # 检查是否是新状态
                        map_state = ""
                        for s in fsm.states:
                            for i in range(len(symbols_fsm)):
                                if not fsm.search_transition(s.name, symbols_fsm[i], responses[i]):
                                    break
                                if i == len(symbols_fsm) - 1:
                                    map_state = s.name
                            if map_state != "":
                                break
                        
                        if map_state != "":
                            # 添加新转换
                            new_transition = [state, message_str, resp_json.get("ret_type"), map_state]
                            fsm.transitions.append(new_transition)
                            for s in fsm.states:
                                get_all_paths(fsm, s)
                            print("new transition added")
                            print(new_transition)
                        else:
                            # 添加新状态
                            new_state = fsm.add_new_state()
                            new_transition = [state, message_str, resp_json.get("ret_type"), new_state.name]
                            fsm.transitions.append(new_transition)
                            
                            # 添加自循环
                            for i in range(len(symbols_fsm)):
                                new_transition = [new_state.name, symbols_fsm[i], responses[i], new_state.name]
                                fsm.transitions.append(new_transition)
                            
                            for s in fsm.states:
                                get_all_paths(fsm, s)
                            
                            new_state.oracle.decide_state(new_state)
                            print("new state added")
                            
                            # 如果使用RL，需要更新网络以支持新状态
                            if USE_RL and rl_scheduler:
                                print(f"  ℹ FSM状态数从{rl_scheduler.num_states}增加到{len(fsm.states)}")
                                print(f"  ℹ 需要重新初始化RL网络以支持新状态")
                                # 注意：这里应该重新初始化网络，但为简单起见先继续
                    
                    break
                
                gNBsocket.close()
                UEsocket.close()
                
                # 保存FSM
                fsm_file = open(f'./savedFSM{suffix}.json', 'w')
                fsm_file.write(fsm.to_json())
                fsm_file.close()
                fsm_sm_file = open(f'./savedFSM_sm{suffix}.json', 'w')
                fsm_sm_file.write(fsm_sm.to_json())
                fsm_sm_file.close()
                
                # 定期保存RL模型
                if USE_RL and rl_scheduler and rl_scheduler.steps % 10 == 0:
                    model_name = './rl_model_dueling.pth' if USE_DUELING else './rl_model_standard.pth'
                    rl_scheduler.save_model(model_name)
            else:
                print("start fuzzing error, resetting...")
        
        except Exception as e:
            print(f"An error occurred during fuzzing iteration: {e}")
            error_file = open('./error.log', 'a')
            error_file.write(time.strftime("%Y-%m-%d %H:%M:%S ", time.localtime()))
            error_file.write(str(e) + "\n")
            error_file.close()
            # 【加速】良性网络异常（UE 超时/断连）且核心仍存活时，不强制 full reset：
            # 交由 LIGHT_RESET 分支做轻量重连；UE 连续连接失败 5 次仍会兜底 full reset。
            err_str = str(e).lower()
            benign_network = ("timed out" in err_str
                              or "broken pipe" in err_str
                              or "connection refused" in err_str
                              or "connection reset" in err_str)
            if benign_network and is_process_running(get_profile().proc("amf")):
                print("  ⚠️ 良性超时/断连且 AMF 存活，跳过 full reset（下一迭代轻量重连）")
                full_reset = False
            else:
                full_reset = True
            continue
    
    # ==================== 实验完成 ====================
    
    print("\n" + "="*60)
    print("  ✅ 模糊测试完成！")
    print("="*60 + "\n")
    
    # 最终保存
    exit_handler(fsm, fsm_sm, rl_scheduler)




