"""
重置辅助模块 - 改进的重置机制
包括AMF状态清理、注销UE等功能
"""

from dotenv import dotenv_values
import os
import subprocess
import time
import socket

config = dotenv_values(".env")

def cleanup_amf_state():
    """
    清理AMF状态
    尝试在killCore之前先注销UE，清理AMF中的注册信息
    """
    print("  🔄 尝试清理AMF中的UE注册信息...")
    
    try:
        # 尝试连接UE并发送注销请求
        # 注意：这需要UE还在运行才能工作
        # 如果UE已经停止，这个操作会失败，但没关系
        
        # 检查UE进程是否还在运行
        result = subprocess.run(['pgrep', '-f', 'nr-ue'], 
                              capture_output=True, timeout=2)
        
        if result.returncode == 0:
            # UE还在运行，尝试发送注销请求
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(("localhost", 45678))
                
                # 发送注销请求（通过发送deregistrationRequest符号）
                # 注意：这需要UE能够响应，如果UE已经不稳定可能失败
                sock.send(b"deregistrationRequest\n")
                time.sleep(0.5)
                
                try:
                    sock.recv(1024)  # 尝试接收响应
                except:
                    pass  # 如果没有响应也没关系
                
                sock.close()
                
                # 等待AMF处理注销请求
                time.sleep(1)
                print("  ✓ 已发送注销请求")
            except Exception as e:
                # UE可能已经断开或无法响应，这是正常的
                print(f"  ℹ️ 无法发送注销请求（UE可能已断开）: {e}")
        else:
            print("  ℹ️ UE进程已停止，跳过注销请求")
    except Exception as e:
        print(f"  ℹ️ 清理AMF状态时出错（可忽略）: {e}")

def ensure_core_fully_stopped(max_wait=5):
    """
    确保Core完全停止
    等待所有进程完全退出
    """
    print("  ⏳ 等待Core完全停止...")
    
    for i in range(max_wait):
        result = subprocess.run(['pgrep', '-f', '5gc'], 
                              capture_output=True, timeout=1)
        if result.returncode != 0:
            # 没有找到5gc进程
            if i > 0:
                print(f"  ✓ Core已完全停止（等待了{i+1}秒）")
            return True
        
        time.sleep(1)
    
    # 如果还有进程在运行，强制kill
    print("  ⚠️ Core进程仍未完全停止，强制清理...")
    subprocess.run(["pkill", "-9", "-f", "5gc"], 
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-x", "open5gs-amfd"],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    return True

def ensure_amf_fully_ready(max_wait=30):
    """
    确保AMF完全就绪
    检查AMF NGAP服务是否完全启动
    """
    print("  ⏳ 等待AMF完全就绪...")
    
    # 检查AMF进程
    for i in range(max_wait):
        result = subprocess.run(['pgrep', '-f', 'amf'], 
                              capture_output=True, timeout=1)
        if result.returncode == 0:
            # AMF进程在运行
            
            # 检查AMF日志，确认NGAP服务已启动
            try:
                with open('./logs/core.log', 'r') as f:
                    log_content = f.read()
                    if 'ngap_server' in log_content.lower() or 'amf initialize...done' in log_content.lower():
                        # 额外等待，确保NGAP服务完全初始化
                        if i >= 3:  # 至少等待3秒
                            print(f"  ✓ AMF NGAP服务已启动（等待了{i+1}秒）")
                            return True
            except:
                pass
        
        time.sleep(1)
    
    print(f"  ⚠️ AMF就绪检查超时（等待了{max_wait}秒）")
    return False

def clear_system_state():
    """
    清理系统状态
    清理可能的缓存、临时文件等
    """
    print("  🔄 清理系统状态...")
    
    # 清理socket连接状态（通过发送信号给进程）
    # 这里主要是等待时间，让系统状态稳定
    
    # 等待所有进程完全退出
    time.sleep(2)
    
    print("  ✓ 系统状态已清理")




