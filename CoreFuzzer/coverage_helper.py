#!/usr/bin/env python3
"""
代码覆盖率计算模块
修复P0问题：缺乏代码覆盖率反馈

功能：
1. 监控代码覆盖率文件（如果启用了覆盖率编译）
2. 计算覆盖率增量
3. 提供覆盖率统计信息
"""

import os
import subprocess
import json
import re
from typing import Dict, Optional, Tuple
from pathlib import Path

class CoverageHelper:
    """
    代码覆盖率辅助类
    
    注意：要使用此功能，需要在编译Open5GS时启用覆盖率选项：
    - 使用gcov: 编译时添加 -fprofile-arcs -ftest-coverage
    - 使用lcov: 编译时添加 --coverage
    """
    
    def __init__(self, open5gs_path: Optional[str] = None):
        """
        初始化覆盖率辅助类
        
        Args:
            open5gs_path: Open5GS源码路径（可选）
        """
        self.open5gs_path = open5gs_path
        self.last_coverage = 0.0
        self.coverage_history = []
        
        # 覆盖率文件路径（如果使用gcov）
        self.gcov_data_dir = os.path.join(open5gs_path, "build") if open5gs_path else None
        
        # 如果Open5GS未启用覆盖率编译，使用文件监控作为替代
        self.use_file_monitoring = True
        
    def get_code_coverage(self) -> float:
        """
        获取当前代码覆盖率
        
        Returns:
            覆盖率百分比 (0.0 - 100.0)
        """
        # 方法1: 尝试使用gcov（如果可用）
        if self.gcov_data_dir and os.path.exists(self.gcov_data_dir):
            try:
                coverage = self._get_gcov_coverage()
                if coverage is not None:
                    return coverage
            except Exception as e:
                print(f"    ⚠️ gcov覆盖率获取失败: {e}")
        
        # 方法2: 使用文件监控（状态覆盖作为替代）
        if self.use_file_monitoring:
            return self._get_state_coverage()
        
        return 0.0
    
    def _get_gcov_coverage(self) -> Optional[float]:
        """
        使用gcov获取代码覆盖率
        
        Returns:
            覆盖率百分比，如果失败返回None
        """
        try:
            # 运行gcov收集数据
            result = subprocess.run(
                ["gcov", "-r", "-j", self.gcov_data_dir],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.gcov_data_dir
            )
            
            # 解析.gcov文件获取覆盖率
            total_lines = 0
            covered_lines = 0
            
            for gcov_file in Path(self.gcov_data_dir).glob("**/*.gcov"):
                with open(gcov_file, 'r') as f:
                    for line in f:
                        # gcov格式: count:line_number:source_code
                        match = re.match(r'^\s*(\d+|-|#####):\s*\d+:', line)
                        if match:
                            count = match.group(1)
                            total_lines += 1
                            if count != '-' and count != '#####':
                                covered_lines += 1
            
            if total_lines > 0:
                coverage = (covered_lines / total_lines) * 100.0
                return coverage
            
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        
        return None
    
    def _get_state_coverage(self) -> float:
        """
        使用状态覆盖作为替代指标（如果代码覆盖率不可用）
        
        Returns:
            状态覆盖率百分比
        """
        # 这是一个占位实现
        # 实际应该从FSM获取状态覆盖信息
        return 0.0
    
    def get_coverage_increase(self, current_states: int, total_states: int) -> float:
        """
        计算覆盖率增量（状态覆盖版本）
        
        Args:
            current_states: 当前已访问状态数
            total_states: 总状态数
            
        Returns:
            覆盖率增量 (0.0 - 1.0)
        """
        if total_states == 0:
            return 0.0
        
        current_coverage = (current_states / total_states) * 100.0
        increase = max(0.0, current_coverage - self.last_coverage) / 100.0
        self.last_coverage = current_coverage
        
        if increase > 0:
            self.coverage_history.append({
                'coverage': current_coverage,
                'increase': increase,
                'timestamp': str(subprocess.check_output(['date', '+%Y-%m-%d %H:%M:%S'], text=True).strip())
            })
        
        return increase
    
    def get_statistics(self) -> Dict:
        """
        获取覆盖率统计信息
        
        Returns:
            统计信息字典
        """
        return {
            'current_coverage': self.last_coverage,
            'coverage_history': self.coverage_history[-100:],  # 最近100条记录
            'total_measurements': len(self.coverage_history)
        }
    
    def reset(self):
        """重置覆盖率统计"""
        self.last_coverage = 0.0
        self.coverage_history = []




