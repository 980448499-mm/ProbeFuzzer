#!/usr/bin/env python3
"""
RL-based State Selection Scheduler for ProbeFuzzer
基于强化学习的状态选择调度器

改进点：
1. 使用DQN算法学习最优的状态选择策略
2. 自适应的能量分配
3. 基于历史反馈的智能决策
"""

import numpy as np
import random
import json
from collections import deque
from typing import List, Tuple, Dict
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

class DQNetwork(nn.Module):
    """
    Deep Q-Network
    输入：状态特征向量
    输出：每个动作的Q值
    """
    def __init__(self, state_dim: int, action_dim: int):
        super(DQNetwork, self).__init__()
        self.fc1 = nn.Linear(state_dim, 128)
        self.fc2 = nn.Linear(128, 128)
        self.fc3 = nn.Linear(128, 64)
        self.fc4 = nn.Linear(64, action_dim)
    
    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        return self.fc4(x)


class DuelingDQNetwork(nn.Module):
    """
    Dueling DQN Network
    
    将Q值分解为状态价值V(s)和动作优势A(s,a):
    Q(s,a) = V(s) + (A(s,a) - mean(A(s,·)))
    
    优势：
    1. 即使不选择某个动作，也能学习状态价值
    2. 在很多状态下，动作选择影响不大时，更高效
    3. 更稳定的训练过程
    
    Reference: Wang et al. "Dueling Network Architectures for 
               Deep Reinforcement Learning." ICML 2016.
    """
    def __init__(self, state_dim: int, action_dim: int):
        super(DuelingDQNetwork, self).__init__()
        
        # 共享特征提取层
        # 这些层对所有动作都是共享的
        self.feature_layer = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU()
        )
        
        # 状态价值流 (Value Stream)
        # 输出一个标量: V(s)
        # 表示"这个状态本身有多好"，与选择哪个动作无关
        self.value_stream = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1)  # 输出单个标量
        )
        
        # 动作优势流 (Advantage Stream)
        # 输出每个动作的优势: A(s,a)
        # 表示"选择这个动作比平均好多少"
        self.advantage_stream = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, action_dim)  # 输出每个动作的优势
        )
    
    def forward(self, x):
        """
        前向传播
        
        Args:
            x: 状态特征向量 [batch_size, state_dim]
        
        Returns:
            Q值 [batch_size, action_dim]
        """
        # 1. 提取共享特征
        features = self.feature_layer(x)  # [batch_size, 64]
        
        # 2. 计算状态价值 V(s)
        value = self.value_stream(features)  # [batch_size, 1]
        
        # 3. 计算动作优势 A(s,a)
        advantage = self.advantage_stream(features)  # [batch_size, action_dim]
        
        # 4. 组合成Q值
        # Q(s,a) = V(s) + (A(s,a) - mean(A(s,·)))
        # 减去平均值确保可识别性（identifiability）
        # 即: 唯一确定V(s)和A(s,a)的值
        q_values = value + (advantage - advantage.mean(dim=1, keepdim=True))
        
        return q_values


class RLScheduler:
    """
    强化学习调度器
    支持标准DQN和Dueling DQN
    """
    def __init__(self, num_states: int, state_features_dim: int = 10, use_dueling: bool = True):
        """
        Args:
            num_states: FSM中的状态数量
            state_features_dim: 状态特征向量的维度
            use_dueling: 是否使用Dueling DQN架构（默认True）
        """
        self.num_states = num_states
        self.state_features_dim = state_features_dim
        self.use_dueling = use_dueling
        
        # 选择网络架构
        NetworkClass = DuelingDQNetwork if use_dueling else DQNetwork
        
        # DQN网络
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.policy_net = NetworkClass(state_features_dim, num_states).to(self.device)
        self.target_net = NetworkClass(state_features_dim, num_states).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        
        # 打印使用的网络类型
        network_type = "Dueling DQN" if use_dueling else "Standard DQN"
        print(f"  🧠 使用网络架构: {network_type}")
        
        # 优化器
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=0.001)
        
        # 经验回放缓冲区
        self.memory = deque(maxlen=10000)
        self.batch_size = 8  # 【修复】降低到8，更快开始训练（适合短期实验）
        
        # 强化学习参数
        self.gamma = 0.99  # 折扣因子
        self.epsilon = 1.0  # 探索率
        self.epsilon_min = 0.15  # 【局部最优修复】从0.01提高到0.15，保持15%探索率
        self.epsilon_decay = 0.997  # 【局部最优修复】从0.995改为0.997，衰减更慢
        
        # 训练步数
        self.steps = 0
        self.target_update_freq = 100
        
        # 累积奖励与统计信息
        self.total_reward = 0.0
        self.stats = {
            'total_rewards': [],
            'avg_q_values': [],
            'epsilon_history': [],
            'state_selection_history': []
        }

    def reset_statistics(self, reset_memory: bool = True, reset_steps: bool = True,
                         reset_epsilon: bool = False):
        """
        重置统计信息/经验（用于开启新的实验）
        """
        if reset_memory:
            self.memory.clear()
        self.total_reward = 0.0
        self.stats = {
            'total_rewards': [],
            'avg_q_values': [],
            'epsilon_history': [],
            'state_selection_history': []
        }
        if reset_steps:
            self.steps = 0
        if reset_epsilon:
            self.epsilon = 1.0
        # 记录当前epsilon，方便分析起点
        self.stats['epsilon_history'].append(self.epsilon)
    
    def extract_state_features(self, state, all_states: List) -> np.ndarray:
        """
        提取状态特征向量
        
        特征包括：
        1. 状态访问次数（归一化）
        2. 状态能量值
        3. 状态路径数量
        4. Oracle状态类型（one-hot编码）
        5. 平均路径长度
        6. 状态访问频率
        7-10. 其他特征
        """
        total_count = sum(s.count for s in all_states)
        avg_count = total_count / len(all_states) if all_states else 1
        
        features = np.zeros(self.state_features_dim)
        
        # 特征1: 归一化的访问次数
        features[0] = state.count / (avg_count + 1)
        
        # 特征2: 能量值（归一化）
        max_energy = max(s.energy for s in all_states) if all_states else 1
        features[1] = state.energy / (max_energy + 1)
        
        # 特征3: 调整后能量（归一化）
        max_adj_energy = max(s.adjusted_energy for s in all_states) if all_states else 1
        features[2] = state.adjusted_energy / (max_adj_energy + 1)
        
        # 特征4: 路径数量（归一化）
        max_paths = max(len(s.paths) for s in all_states) if all_states else 1
        features[3] = len(state.paths) / (max_paths + 1)
        
        # 特征5-9: Oracle状态类型（one-hot编码）
        # I, N, S, R, D, O
        oracle_states = ['I', 'N', 'S', 'R', 'D', 'O']
        oracle_idx = oracle_states.index(state.oracle.state) if state.oracle.state in oracle_states else 5
        features[4 + oracle_idx] = 1.0  # one-hot
        
        return features
    
    def select_action(self, state_features: np.ndarray, all_states: List) -> int:
        """
        使用epsilon-greedy策略选择动作（状态）
        """
        # 【修复】确保状态数量匹配
        actual_num_states = len(all_states)
        if actual_num_states != self.num_states:
            print(f"    ⚠ 警告: 状态数变化 {self.num_states} → {actual_num_states}")
            self.num_states = actual_num_states
        
        # Epsilon-greedy
        if random.random() < self.epsilon:
            # 探索：随机选择
            action = random.randint(0, self.num_states - 1)
        else:
            # 利用：选择Q值最大的动作
            with torch.no_grad():
                state_tensor = torch.FloatTensor(state_features).unsqueeze(0).to(self.device)
                q_values = self.policy_net(state_tensor)
                action = q_values.argmax().item()
        
        # 【修复】边界检查
        action = min(action, self.num_states - 1)
        action = max(action, 0)
        
        self.stats['state_selection_history'].append(action)
        return action
    
    def calculate_reward(self, test_result: Dict) -> float:
        """
        计算奖励（改进版 - P0修复）
        
        改进点：
        1. 添加基础时间成本（负奖励）
        2. 细化崩溃奖励（真实崩溃 vs 超时）
        3. 添加密集反馈（响应时间、错误类型等）
        4. 添加负奖励机制（重复测试、无效操作）
        5. 正常拒绝不再算作崩溃奖励
        
        奖励层次：
        - Layer 1 (最高): 真实崩溃 +1000, 超时/DoS +800
        - Layer 2 (高): 协议违规 +500, 协议错误 +300
        - Layer 3 (中): 新状态 +200, 新转换 +100
        - Layer 4 (低): 覆盖率增长 +50*增量, 新消息类型 +20, 错误触发 +30
        - Layer 5 (惩罚): 基础成本 -10, 重复测试 -1~-5, 无响应 -5, 正常拒绝 +0
        """
        # 【P0修复1】基础时间成本（每次迭代都扣除）
        reward = -10.0
        
        # 【P0修复2】细化崩溃奖励（区分真实崩溃和超时）
        crash_type = test_result.get('crash_type', None)
        if crash_type == 'real_crash':
            # 真实进程崩溃（SIGSEGV/SIGABRT等）
            reward += 1000
            print(f"    🎉 [L1] 发现真实崩溃! 奖励: +1000")
        elif crash_type == 'timeout':
            # 服务超时/无响应（潜在DoS）
            reward += 800
            print(f"    ⏱️ [L1] 服务超时/无响应! 奖励: +800")
        elif test_result.get('crashed', False):
            # 兼容旧版本（如果没有crash_type字段）
            reward += 1000
            print(f"    🎉 [L1] 发现崩溃! 奖励: +1000")
        
        # 【P0修复3】正常拒绝不算崩溃（假阳性修复）
        if test_result.get('normal_reject', False):
            # 正常安全拒绝（符合3GPP规范），不给奖励，但也不惩罚
            reward += 0  # 明确标记为0，表示这是正常行为
            print(f"    ℹ️ [正常拒绝] 这是符合规范的安全行为，无奖励")
        
        # Layer 2: 协议层错误
        if test_result.get('protocol_violation', False):
            reward += 500
            print(f"    🎉 [L2] 发现协议违规! 奖励: +500")
        
        if test_result.get('protocol_error', False):
            reward += 300
            print(f"    🔴 [L2] 协议错误! 奖励: +300")
        
        # Layer 3: 探索性发现
        if test_result.get('new_state', False):
            reward += 200
            print(f"    ✓ [L3] 发现新状态! 奖励: +200")
        
        if test_result.get('new_transition', False):
            reward += 100
            print(f"    ✓ [L3] 发现新转换! 奖励: +100")
        
        if test_result.get('new_response', False):
            reward += 100
            print(f"    ✓ [L3] 发现新响应! 奖励: +100")
        
        # Layer 4: 增量改进（密集反馈）
        coverage_increase = test_result.get('coverage_increase', 0)
        if coverage_increase > 0:
            coverage_reward = min(coverage_increase * 50, 100)  # 最多+100
            reward += coverage_reward
            print(f"    ✓ [L4] 覆盖率提升{coverage_increase:.2%}: +{coverage_reward:.1f}")
        
        # 【P0修复4】密集反馈：响应时间奖励
        response_time = test_result.get('response_time', None)
        if response_time is not None:
            if response_time < 0.1:  # 快速响应
                reward += 5
            elif response_time > 2.0:  # 慢速响应（可能有问题）
                reward += 10  # 慢响应也可能是有趣的行为
        
        # 【P0修复4】密集反馈：错误类型奖励
        error_type = test_result.get('error_type', None)
        if error_type:
            # 不同类型的错误给予不同奖励
            error_rewards = {
                'authentication_failure': 15,
                'integrity_check_failed': 20,
                'security_context_error': 25,
                'unknown_error': 10
            }
            error_reward = error_rewards.get(error_type, 15)
            reward += error_reward
            print(f"    ✓ [L4] 错误类型({error_type}): +{error_reward}")
        
        if test_result.get('error_triggered', False):
            reward += 30
            print(f"    ✓ [L4] 触发错误! 奖励: +30")
        
        if test_result.get('new_message_type', False):
            reward += 20
            print(f"    ✓ [L4] 新消息类型! 奖励: +20")
        
        if test_result.get('interesting', False):
            reward += 10
            print(f"    ✓ [L4] 有趣行为! 奖励: +10")
        
        # 【P0修复5 + 局部最优修复】负奖励机制
        # 探索奖励: 鼓励访问少的状态（优先）
        state_visit_count = test_result.get('state_visit_count', 0)
        if state_visit_count < 5:
            exploration_bonus = 50  # 前5次访问给予探索奖励
            reward += exploration_bonus
            print(f"    ✨ [探索奖励] 状态访问少({state_visit_count}次): +{exploration_bonus:.1f}")
        elif state_visit_count < 15:
            exploration_bonus = 20  # 5-15次仍给予少量奖励
            reward += exploration_bonus
            print(f"    ✨ [探索奖励] 鼓励多样性: +{exploration_bonus:.1f}")
        
        # 惩罚1: 重复访问同一状态（避免过度集中）
        if state_visit_count > 10:
            # 【局部最优修复】访问次数越多，惩罚越重（不封顶，从0.5增加到1.5）
            repeat_penalty = (state_visit_count - 10) * 1.5
            reward -= repeat_penalty
            if repeat_penalty > 0:
                print(f"    ⚠️ [惩罚] 重复访问状态({state_visit_count}次): -{repeat_penalty:.1f}")
        
        # 【局部最优修复】奖励探索：鼓励访问少的状态
        if state_visit_count < 5:
            exploration_bonus = 50  # 前5次访问给予探索奖励
            reward += exploration_bonus
            print(f"    ✨ [探索奖励] 状态访问少({state_visit_count}次): +{exploration_bonus:.1f}")
        elif state_visit_count < 15:
            exploration_bonus = 20  # 5-15次仍给予少量奖励
            reward += exploration_bonus
            print(f"    ✨ [探索奖励] 鼓励多样性: +{exploration_bonus:.1f}")
        
        # 惩罚2: 无响应/无反馈
        if test_result.get('no_response', False):
            reward -= 5
            print(f"    ⚠️ [惩罚] 无响应: -5")
        
        # 惩罚3: 网络连接失败
        if test_result.get('connection_failed', False):
            reward -= 10
            print(f"    ⚠️ [惩罚] 连接失败: -10")
        
        # 惩罚4: 无效操作（解码错误等）
        if test_result.get('invalid_operation', False):
            reward -= 3
            print(f"    ⚠️ [惩罚] 无效操作: -3")
        
        # 奖励限制：确保奖励在合理范围内
        reward = max(reward, -50)  # 最小-50分
        reward = min(reward, 1500)  # 最大1500分（真实崩溃+协议违规+其他）
        
        # 【修复】记录奖励到统计
        self.total_reward += reward
        self.stats['total_rewards'].append(reward)
        
        return reward
    
    def store_transition(self, state_features: np.ndarray, action: int, 
                        reward: float, next_state_features: np.ndarray, done: bool):
        """
        存储经验到回放缓冲区
        
        【修复】在存储经验时也更新epsilon，即使未开始训练
        这样可以确保epsilon随着探索的进行而逐渐衰减
        """
        self.memory.append((state_features, action, reward, next_state_features, done))
        
        # 【修复】即使不训练，也让epsilon随经验累积衰减
        # 这样可以更早进入利用阶段，同时保持探索
        if len(self.memory) > 0 and self.epsilon > self.epsilon_min:
            # 每收集4条经验衰减一次epsilon（相当于每训练一次衰减）
            if len(self.memory) % 4 == 0:
                self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
                # 记录epsilon变化（但不频繁记录，避免历史过长）
                if len(self.memory) % 16 == 0:
                    self.stats['epsilon_history'].append(self.epsilon)
    
    def train(self):
        """
        训练DQN网络
        """
        if len(self.memory) < self.batch_size:
            return
        
        # 采样batch
        batch = random.sample(self.memory, self.batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        
        # 转换为tensor
        states = torch.FloatTensor(np.array(states)).to(self.device)
        actions = torch.LongTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(np.array(next_states)).to(self.device)
        dones = torch.FloatTensor(dones).to(self.device)
        
        # 计算当前Q值
        current_q_values = self.policy_net(states).gather(1, actions.unsqueeze(1))
        
        # 计算目标Q值
        with torch.no_grad():
            next_q_values = self.target_net(next_states).max(1)[0]
            target_q_values = rewards + (1 - dones) * self.gamma * next_q_values
        
        # 计算loss
        loss = F.mse_loss(current_q_values.squeeze(), target_q_values)
        
        # 反向传播
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        # 更新目标网络
        self.steps += 1
        if self.steps % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())
        
        # 衰减epsilon
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
        
        # 记录统计
        self.stats['avg_q_values'].append(current_q_values.mean().item())
        self.stats['epsilon_history'].append(self.epsilon)
        
        return loss.item()
    
    def choose_state_rl(self, all_states: List):
        """
        使用RL选择下一个要测试的状态
        
        这个函数替代原来的PowerSchedule.choose()
        """
        # 1. 提取当前环境的全局特征
        global_features = self.extract_global_features(all_states)
        
        # 2. 使用RL agent选择状态
        action = self.select_action(global_features, all_states)
        
        # 确保action在有效范围内
        if action >= len(all_states):
            action = action % len(all_states)
        
        selected_state = all_states[action]
        
        return selected_state, action
    
    def extract_global_features(self, all_states: List) -> np.ndarray:
        """
        提取全局特征（整个FSM的状态）
        """
        total_count = sum(s.count for s in all_states)
        total_paths = sum(len(s.paths) for s in all_states)
        
        features = np.zeros(self.state_features_dim)
        
        # 全局统计特征
        features[0] = total_count / 1000.0  # 归一化总执行次数
        features[1] = total_paths / 200.0   # 归一化总路径数
        features[2] = len(all_states) / 20.0  # 归一化状态数
        
        # 访问分布的方差（衡量不平衡度）
        counts = [s.count for s in all_states]
        if counts:
            features[3] = np.var(counts) / (np.mean(counts) + 1)
        
        # 未访问状态数量
        unvisited = sum(1 for s in all_states if s.count == 0)
        features[4] = unvisited / len(all_states)
        
        # 低访问状态数量（访问次数 < 平均值的50%）
        avg_count = np.mean(counts) if counts else 0
        low_visit = sum(1 for c in counts if c < avg_count * 0.5)
        features[5] = low_visit / len(all_states)
        
        # 能量分布
        energies = [s.energy for s in all_states]
        if energies:
            features[6] = np.mean(energies)
            features[7] = np.std(energies)
        
        # Oracle状态分布
        oracle_types = [s.oracle.state for s in all_states]
        features[8] = oracle_types.count('R') / len(all_states)  # 已注册状态比例
        features[9] = oracle_types.count('S') / len(all_states)  # 安全上下文状态比例
        
        return features
    
    def save_model(self, path: str = './rl_model.pth'):
        """
        保存训练好的模型
        """
        torch.save({
            'policy_net_state_dict': self.policy_net.state_dict(),
            'target_net_state_dict': self.target_net.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'epsilon': self.epsilon,
            'steps': self.steps,
            'stats': self.stats
        }, path)
        print(f"模型已保存到: {path}")
    
    def load_model(self, path: str = './rl_model.pth'):
        """
        加载预训练的模型
        """
        checkpoint = torch.load(path, map_location=self.device)
        self.policy_net.load_state_dict(checkpoint['policy_net_state_dict'])
        self.target_net.load_state_dict(checkpoint['target_net_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.epsilon = checkpoint['epsilon']
        self.steps = checkpoint['steps']
        self.stats = checkpoint['stats']
        print(f"模型已加载: {path}")
    
    def get_stats(self) -> Dict:
        """
        获取统计信息
        """
        return {
            'total_steps': self.steps,
            'epsilon': self.epsilon,
            'avg_reward': np.mean(self.stats['total_rewards'][-100:]) if self.stats['total_rewards'] else 0,
            'avg_q_value': np.mean(self.stats['avg_q_values'][-100:]) if self.stats['avg_q_values'] else 0
        }


class RLGuidedFuzzer:
    """
    集成RL调度器的模糊测试器
    """
    def __init__(self, fsm, rl_scheduler: RLScheduler):
        self.fsm = fsm
        self.rl_scheduler = rl_scheduler
        self.episode_reward = 0
        self.episode_count = 0
        
    def run_fuzzing_iteration(self):
        """
        运行一次模糊测试迭代
        """
        # 1. 获取当前全局特征
        current_features = self.rl_scheduler.extract_global_features(self.fsm.states)
        
        # 2. RL选择状态
        selected_state, action = self.rl_scheduler.choose_state_rl(self.fsm.states)
        
        print(f"RL选择状态: {selected_state.name} (epsilon={self.rl_scheduler.epsilon:.3f})")
        
        # 3. 执行模糊测试
        test_result = self.execute_fuzzing(selected_state)
        
        # 4. 计算奖励
        reward = self.rl_scheduler.calculate_reward(test_result)
        self.episode_reward += reward
        
        print(f"  奖励: {reward:.1f} (累计: {self.episode_reward:.1f})")
        
        # 5. 获取下一个状态的特征
        next_features = self.rl_scheduler.extract_global_features(self.fsm.states)
        
        # 6. 存储经验
        done = test_result.get('crashed', False) or test_result.get('protocol_violation', False)
        self.rl_scheduler.store_transition(current_features, action, reward, next_features, done)
        
        # 7. 训练网络
        if len(self.rl_scheduler.memory) >= self.rl_scheduler.batch_size:
            loss = self.rl_scheduler.train()
            if loss and self.rl_scheduler.steps % 10 == 0:
                print(f"  训练Loss: {loss:.4f}")
        
        # 8. Episode结束
        if done or self.episode_count % 100 == 0:
            self.rl_scheduler.stats['total_rewards'].append(self.episode_reward)
            print(f"\n=== Episode {self.episode_count} 结束 ===")
            print(f"总奖励: {self.episode_reward:.1f}")
            print(f"平均奖励(最近100): {np.mean(self.rl_scheduler.stats['total_rewards'][-100:]):.1f}")
            self.episode_reward = 0
        
        self.episode_count += 1
        
        return test_result
    
    def execute_fuzzing(self, state) -> Dict:
        """
        执行模糊测试（调用原有的CoreFuzzer逻辑）
        """
        # TODO: 集成原有的fuzzing逻辑
        # 这里返回模拟结果
        return {
            'crashed': False,
            'protocol_violation': False,
            'new_state': False,
            'coverage_increase': 0,
            'state_visit_count': state.count,
            'interesting': False,
            'error_triggered': False
        }


# 使用示例
if __name__ == '__main__':
    # 假设有17个状态
    num_states = 17
    
    # 创建RL调度器
    rl_scheduler = RLScheduler(num_states=num_states)
    
    print("="*60)
    print("  基于强化学习的ProbeFuzzer状态选择器")
    print("="*60)
    print(f"状态数量: {num_states}")
    print(f"特征维度: {rl_scheduler.state_features_dim}")
    print(f"设备: {rl_scheduler.device}")
    print(f"初始epsilon: {rl_scheduler.epsilon}")
    print("="*60)
    print()
    
    print("✓ RL调度器初始化完成")
    print("✓ DQN网络已创建")
    print("✓ 准备开始训练")
    print()
    print("下一步: 集成到CoreFuzzer主循环")

