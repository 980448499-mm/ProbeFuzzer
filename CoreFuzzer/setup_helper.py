from dotenv import dotenv_values, load_dotenv
import os, subprocess, time
# helper functions for start and kill the components

load_dotenv(".env")  # 加载到 os.environ，供 core_profile 的 {VAR} 命令解析使用
config = dotenv_values(".env")
# set IMSI offset
IMSI_OFFSET = 0
MAX_IMSI_OFFSET = 9998  # 【P2改进】从98增加到9998，使用更大的IMSI偏移量，避免AMF记住之前的注册

def setOffset(new_offset:int):
    global IMSI_OFFSET
    IMSI_OFFSET = new_offset

def getOffset():
    global IMSI_OFFSET
    return IMSI_OFFSET

def startCore(profile=None) -> bool:
    """
    启动 5G 核心网（根据 core profile 选择 native/docker 启动命令）。
    """
    from core_profile import current_profile
    if profile is None:
        profile = current_profile()

    cmd = profile.resolved_start_cmd()
    log_file = profile.resolved_log_path("core") or "./logs/core.log"

    try:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        with open(log_file, "w") as out:
            out.write(f"=== Core启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')} "
                      f"(core={profile.name}) ===\n")

        with open(log_file, "a") as out:
            subprocess.Popen(args=cmd, stdout=out, stderr=out, start_new_session=True)

        time.sleep(3)

        amf = profile.proc("amf")
        if profile.deployment == "docker":
            r = subprocess.run(["docker", "ps", "--filter", f"name={amf}",
                                "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and amf in r.stdout:
                return True
        else:
            result = subprocess.run(['pgrep', '-f', amf], capture_output=True, timeout=2)
            if result.returncode == 0:
                return True

        print(f"  ❌ Core({profile.name}) AMF 进程/容器未找到")
        return False

    except FileNotFoundError as e:
        print(f"  ❌ 启动命令未找到: {e}")
        return False
    except PermissionError:
        print("  ❌ 权限不足，无法启动核心网")
        return False
    except Exception as e:
        print(f"  ❌ 启动Core失败: {e}")
        return False

def startUE() -> bool:
    """
    【关键修复】启动UE并验证成功 - 不检查父进程退出，而是检查实际运行状态
    
    Returns:
        bool: 启动是否成功
    """
    from core_profile import current_profile
    cfg = os.path.join(os.environ.get("UERANSIM_PATH", ""), "config", current_profile().ue_config)
    if not os.path.exists(cfg):
        print(f"  ❌ UE配置文件不存在: {cfg}")
        return False
    
    try:
        imsi = f"imsi-{current_profile().imsi_base + IMSI_OFFSET}"
        with open("./logs/ue.log", "w") as out:
            out.write(f"=== UE启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}, IMSI: {imsi} ===\n")
        
        with open("./logs/ue.log", "a") as out:
            subprocess.Popen(
                args=["nr-ue", "-c", cfg, "-i", imsi, "-p", str(current_profile().ue_port)],
                stdout=out,
                stderr=out,
                start_new_session=True
            )
            # 【终极修复】UE启动需要：fork → 读配置 → 连接AMF → 创建socket → accept()
            # 这个过程需要4-6秒，尤其是连接AMF有网络延迟
            time.sleep(6)  # 从3秒增加到6秒
            
            # 【关键修复】检查实际进程是否运行，而不是父进程退出状态
            # UE进程会fork，父进程退出码0是正常的！
            result = subprocess.run(['pgrep', '-x', 'nr-ue'], 
                                  capture_output=True, timeout=2)
            if result.returncode == 0:
                return True
            
            print(f"  ❌ UE进程未找到")
            return False
    except Exception as e:
        print(f"  ❌ 启动UE失败: {e}")
        return False
        
def startUE2():
    global IMSI_OFFSET
    IMSI_OFFSET += 1
    with open("./logs/ue2.log", "w") as out:
        from core_profile import current_profile
        cfg = os.path.join(os.environ.get("UERANSIM_PATH", ""), "config", current_profile().ue_config)
        imsi = f"imsi-{current_profile().imsi_base + IMSI_OFFSET}"
        subprocess.Popen(args=["nr-ue", "-c", cfg, "-i", imsi, "-p", "45679"], 
                         stdout=out, stderr=out, start_new_session=True)
        
def startUE3():
    global IMSI_OFFSET
    IMSI_OFFSET += 1
    with open("./logs/ue3.log", "w") as out:
        from core_profile import current_profile
        cfg = os.path.join(os.environ.get("UERANSIM_PATH", ""), "config", current_profile().ue_config)
        imsi = f"imsi-{current_profile().imsi_base + IMSI_OFFSET}"
        subprocess.Popen(args=["nr-ue", "-c", cfg, "-i", imsi, "-p", "45680"], 
                         stdout=out, stderr=out, start_new_session=True)

def startGNB() -> bool:
    """
    【修复】启动gNB并验证成功
    
    Returns:
        bool: 启动是否成功
    """
    from core_profile import current_profile
    cfg = os.path.join(os.environ.get("UERANSIM_PATH", ""), "config", current_profile().gnb_config)
    if not os.path.exists(cfg):
        print(f"  ❌ GNB配置文件不存在: {cfg}")
        return False
    
    try:
        with open("./logs/gnb.log", "w") as out:
            out.write(f"=== GNB启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        
        with open("./logs/gnb.log", "a") as out:
            subprocess.Popen(
                args=["nr-gnb", "-c", cfg], 
                stdout=out, 
                stderr=out, 
                start_new_session=True
            )
            time.sleep(3)
            
            # 【关键修复】检查实际进程是否运行
            result = subprocess.run(['pgrep', '-x', 'nr-gnb'], 
                                  capture_output=True, timeout=2)
            if result.returncode == 0:
                return True
            
            print(f"  ❌ GNB进程未找到")
            return False
    except Exception as e:
        print(f"  ❌ 启动GNB失败: {e}")
        return False

def killCore(profile=None):
    from core_profile import current_profile
    if profile is None:
        profile = current_profile()

    cmd = profile.resolved_kill_cmd()
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 额外清理（原生进程名，兼容 kill 命令未完全覆盖的情况）
    if profile.deployment == "native":
        for role in ("amf", "smf", "upf", "nrf"):
            name = profile.proc(role)
            if name:
                subprocess.run(["pkill", "-2", "-x", name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def killUE():
    subprocess.run(["pkill", "-9", "-x", "nr-ue"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(3):
        out = subprocess.run(["pgrep", "-x", "nr-ue"], capture_output=True, text=True)
        for pid in out.stdout.split():
            subprocess.run(["kill", "-9", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

def killGNB():
    subprocess.run(["pkill", "-9", "-x", "nr-gnb"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(3):
        out = subprocess.run(["pgrep", "-x", "nr-gnb"], capture_output=True, text=True)
        for pid in out.stdout.split():
            subprocess.run(["kill", "-9", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

GNB_CONTROL_PORT = 56789

def is_gnb_port_listening() -> bool:
    """Check nr-gnb state-learner TCP port without holding a UE connection."""
    try:
        r = subprocess.run(["ss", "-ltn"], capture_output=True, text=True, timeout=3)
        return f":{GNB_CONTROL_PORT} " in r.stdout
    except Exception:
        return False

def wait_for_gnb_port(max_wait: int = 25) -> bool:
    for _ in range(max_wait):
        if is_gnb_port_listening():
            proc = subprocess.run(["pgrep", "-x", "nr-gnb"], capture_output=True)
            if proc.returncode == 0:
                return True
        time.sleep(1)
    return False

def restartGNB() -> bool:
    """Restart only nr-gnb; leave Open5GS Core / AMF running."""
    print("  🔄 重启 nr-gnb（保留 AMF/Core）...")
    killGNB()
    time.sleep(1)
    if not startGNB():
        print("  ❌ nr-gnb 启动失败")
        return False
    if wait_for_gnb_port(25):
        print("  ✅ GNB 控制端口 56789 就绪")
        return True
    print("  ⚠️ GNB 进程已启动但控制端口未就绪")
    return False

def sendRRCRelease():
    subprocess.Popen(args=["nr-cli", "UERANSIM-gnb-999-70-1", "--exec", "ue-release 1"])
    time.sleep(0.25)
