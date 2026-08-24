# RL-ProbeFuzzer 算法流程和运行流程详解

## 📋 目录

1. [系统整体架构](#系统整体架构)
2. [算法流程详解](#算法流程详解)
3. [运行流程详解](#运行流程详解)
4. [关键算法实现](#关键算法实现)
5. [数据流图](#数据流图)

---

## 🏗️ 系统整体架构

### 三大核心组件

```
┌─────────────────────────────────────────────────────────┐
│                    RL-ProbeFuzzer                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Corelearner  │  │  CoreFuzzer  │  │  UERANSIM    │ │
│  │              │  │   + RL       │  │              │ │
│  │ 状态机学习    │─▶│  模糊测试    │─▶│  消息生成    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│        │                   │                   │       │
│        ▼                   ▼                   ▼       │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Open5GS (5G Core)                   │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 🔬 算法流程详解

### 阶段一：状态机学习（Corelearner）

#### 1.1 学习算法：TTT (Tree-based Testing)

```
输入: 5G NAS协议，测试消息集
输出: 状态机模型

算法流程:
1. 初始化: 创建单个初始状态
2. 对每个状态:
   2.1 构建判别树 (Discrimination Tree)
   2.2 执行测试查询 (Membership Queries)
   2.3 观察输出响应
   2.4 更新状态转换表
3. 等价性测试 (WPMethod):
   3.1 生成测试序列
   3.2 检查假设的状态机是否等价于真实系统
   3.3 如果发现反例，返回步骤2
4. 收敛: 输出最终状态机

伪代码:
──────────────────────────────────
Algorithm: TTT Learning
──────────────────────────────────
Input: Alphabet Σ, SUL (System Under Learning)
Output: State Machine M

1: S ← {s0}  // 初始状态集
2: T ← ∅     // 判别树
3: while True do
4:   for each s ∈ S do
5:     for each a ∈ Σ do
6:       o ← Query(s, a)  // 执行查询
7:       s' ← FindOrCreateState(o, T)
8:       AddTransition(s, a, o, s')
9:     end for
10:  end for
11:  
12:  // 等价性测试
13:  counterexample ← WPMethod(M, SUL)
14:  if counterexample == null then
15:    return M  // 收敛
16:  else
17:    RefineModel(M, counterexample)
18:  end if
19: end while
```

**关键参数**:
- `alphabet`: 12个NAS消息类型
- `max_depth`: 1（判别树深度）
- `min_length`: 4（最小测试序列长度）
- `max_length`: 6（最大测试序列长度）
- `nr_queries`: 15（等价性测试查询数）

**输出**:
- `open5gs.dot`: 完整状态机（15个状态，200+转换）
- `open5gs_sm.dot`: 简化状态机（用于会话管理）

---

### 阶段二：RL引导的模糊测试（CoreFuzzer）

#### 2.1 核心算法：DQN (Deep Q-Network)

```
目标: 学习最优的状态选择策略π*
Q函数: Q(s,a) = 选择状态a后的期望累积奖励

算法流程:
──────────────────────────────────
Algorithm: DQN for State Selection
──────────────────────────────────
Input: FSM M, Replay Buffer D, Networks Q, Q'
Output: Optimal policy π*

1: Initialize Q-network Q(s,a; θ) with random weights θ
2: Initialize target Q-network Q'(s,a; θ') with θ' ← θ
3: Initialize replay buffer D ← ∅
4: for episode = 1 to N do
5:   Reset environment, s ← s0
6:   for t = 1 to T do
7:     // 状态特征提取
8:     φ(s) ← ExtractFeatures(FSM)  // 10维特征
9:     
10:     // Epsilon-greedy动作选择
11:     if random() < ε then
12:       a ← RandomState()          // 探索
13:     else
14:       a ← argmax_a' Q(φ(s), a'; θ)  // 利用
15:     end if
16:     
17:     // 执行模糊测试
18:     Execute fuzzing on state a
19:     Observe result: crash, violation, new_state, etc.
20:     
21:     // 计算奖励
22:     r ← CalculateReward(result)
23:     
24:     // 观察下一状态
25:     s' ← GetNextState(FSM)
26:     φ(s') ← ExtractFeatures(FSM)
27:     
28:     // 存储经验
29:     D ← D ∪ {(φ(s), a, r, φ(s'), done)}
30:     
31:     // 训练Q网络
32:     if |D| ≥ batch_size then
33:       Sample mini-batch B from D
34:       for each (φ, a, r, φ', d) ∈ B do
35:         if d then
36:           y ← r
37:         else
38:           y ← r + γ · max_a' Q'(φ', a'; θ')
39:         end if
40:         
41:         // 梯度下降
42:         θ ← θ - α∇_θ(Q(φ, a; θ) - y)²
43:       end for
44:     end if
45:     
46:     // 更新目标网络
47:     if t mod C == 0 then
48:       θ' ← θ
49:     end if
50:     
51:     // 衰减epsilon
52:     ε ← max(ε_min, ε · ε_decay)
53:     
54:     s ← s'
55:   end for
56: end for
```

**关键参数**:
```python
学习率 α: 0.001
折扣因子 γ: 0.99
初始探索率 ε: 1.0
最小探索率 ε_min: 0.01
探索衰减 ε_decay: 0.995
Batch大小: 64
回放缓冲区: 10000
目标网络更新频率: 100步
```

#### 2.2 状态特征提取

```python
def extract_global_features(all_states) -> np.ndarray[10]:
    """
    提取10维全局特征向量
    """
    features = np.zeros(10)
    
    # Feature 0: 归一化总执行次数
    total_count = sum(s.count for s in all_states)
    features[0] = total_count / 1000.0
    
    # Feature 1: 归一化总路径数
    total_paths = sum(len(s.paths) for s in all_states)
    features[1] = total_paths / 200.0
    
    # Feature 2: 归一化状态数
    features[2] = len(all_states) / 20.0
    
    # Feature 3: 访问分布方差（不平衡度）
    counts = [s.count for s in all_states]
    features[3] = np.var(counts) / (np.mean(counts) + 1)
    
    # Feature 4: 未访问状态比例
    unvisited = sum(1 for s in all_states if s.count == 0)
    features[4] = unvisited / len(all_states)
    
    # Feature 5: 低访问状态比例
    avg_count = np.mean(counts)
    low_visit = sum(1 for c in counts if c < avg_count * 0.5)
    features[5] = low_visit / len(all_states)
    
    # Feature 6-7: 能量统计
    energies = [s.energy for s in all_states]
    features[6] = np.mean(energies)
    features[7] = np.std(energies)
    
    # Feature 8-9: Oracle状态分布
    oracle_types = [s.oracle.state for s in all_states]
    features[8] = oracle_types.count('R') / len(all_states)  # 已注册
    features[9] = oracle_types.count('S') / len(all_states)  # 安全上下文
    
    return features
```

#### 2.3 奖励函数设计

```python
def calculate_reward(test_result) -> float:
    """
    多维度奖励函数
    """
    reward = 0.0
    
    # 最高优先级：发现安全问题
    if test_result['crashed']:
        reward += 1000              # 组件崩溃
    
    if test_result['protocol_violation']:
        reward += 500               # 协议违规
    
    # 高优先级：探索新路径
    if test_result['new_state']:
        reward += 200               # 发现新状态
    
    if test_result['new_transition']:
        reward += 100               # 发现新转换
    
    # 中优先级：增加覆盖率
    coverage_increase = test_result['coverage_increase']
    reward += coverage_increase * 50
    
    # 低优先级：触发新行为
    if test_result['new_message_type']:
        reward += 20
    
    if test_result['error_triggered']:
        reward += 30
    
    if test_result['interesting']:
        reward += 10
    
    # 惩罚：避免过度集中
    if test_result['state_visit_count'] > 50:
        reward -= (test_result['state_visit_count'] - 50) * 0.5
    
    return reward
```

**奖励设计理念**:
- 分层奖励：安全问题 > 探索 > 覆盖率
- 正向激励：鼓励发现新内容
- 负向惩罚：避免过度利用
- 可调权重：便于调优

#### 2.4 DQN网络结构

```
输入层 (10维)
    ↓
全连接层1 (128神经元)
    ↓
ReLU激活
    ↓
全连接层2 (128神经元)
    ↓
ReLU激活
    ↓
全连接层3 (64神经元)
    ↓
ReLU激活
    ↓
输出层 (17维) - 每个状态的Q值
```

**网络实现**:
```python
class DQNetwork(nn.Module):
    def __init__(self, state_dim=10, action_dim=17):
        super().__init__()
        self.fc1 = nn.Linear(state_dim, 128)
        self.fc2 = nn.Linear(128, 128)
        self.fc3 = nn.Linear(128, 64)
        self.fc4 = nn.Linear(64, action_dim)
    
    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        return self.fc4(x)  # Q值，无激活函数
```

**参数统计**:
- 总参数量: 10×128 + 128×128 + 128×64 + 64×17 = 26,825个
- 模型大小: ~448KB

---

## 🔄 运行流程详解

### 完整运行流程图

```
┌─────────────────────────────────────────────────────────────┐
│                     程序启动                                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 1. 初始化阶段                                                │
├─────────────────────────────────────────────────────────────┤
│ • 加载配置文件 (.env)                                        │
│ • 加载学习到的状态机 (savedFSM.json)                        │
│ • 初始化RL调度器 (RLScheduler)                              │
│   - 创建DQN网络                                             │
│   - 加载预训练模型（如果存在）                               │
│   - 初始化经验回放缓冲区                                     │
│ • 注册退出处理函数                                          │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. 环境重置                                                  │
├─────────────────────────────────────────────────────────────┤
│ • killCore() - 停止Open5GS所有NF                            │
│ • killGNB() - 停止gNB                                       │
│ • killUE() - 停止UE                                         │
│ • startCore() - 启动Open5GS (等待10秒)                      │
│ • startGNB() - 启动gNB (等待0.1秒)                          │
│ • startUE() - 启动UE (等待0.1秒)                            │
│ • setOffset(0) - 重置IMSI偏移                               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. 主测试循环 (while True)                                  │
└─────────────────────────────────────────────────────────────┘
        │
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.1 轻量级重置                                 │
        │   ├───────────────────────────────────────────────┤
        │   │ • killGNB(), killUE()                         │
        │   │ • startGNB(), startUE()                       │
        │   │ • IMSI_OFFSET += 1                            │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.2 连接UE                                     │
        │   ├───────────────────────────────────────────────┤
        │   │ • connectUE() - Socket连接到UE:45678          │
        │   │ • 超时处理: 重试10次后full_reset              │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.3 RL状态选择 ⭐核心创新                      │
        │   ├───────────────────────────────────────────────┤
        │   │ if USE_RL:                                    │
        │   │   1. 提取全局特征向量                          │
        │   │      features = extract_global_features()     │
        │   │                                               │
        │   │   2. Epsilon-greedy选择                       │
        │   │      if random() < ε:                         │
        │   │        action = random_choice()  // 探索      │
        │   │      else:                                    │
        │   │        Q_values = DQN(features)               │
        │   │        action = argmax(Q_values)  // 利用     │
        │   │                                               │
        │   │   3. 获取选中的状态                            │
        │   │      curr_state = fsm.states[action]         │
        │   │                                               │
        │   │ else: (原版PowerSchedule)                    │
        │   │   1. 调整能量                                 │
        │   │      adjustEnergy(states)                    │
        │   │   2. 加权随机选择                             │
        │   │      curr_state = weighted_choice(states)    │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.4 路径选择和执行                             │
        │   ├───────────────────────────────────────────────┤
        │   │ • path = curr_state.select_path()             │
        │   │ • execSequence(path):                         │
        │   │   - 依次发送input_symbols                     │
        │   │   - 验证output_symbols匹配                    │
        │   │   - 到达目标状态                              │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.5 启用模糊测试                               │
        │   ├───────────────────────────────────────────────┤
        │   │ • sendSymbol("enableFuzzing")                 │
        │   │ • 收集种子消息:                               │
        │   │   for symbol in symbols_enabled:              │
        │   │     msg = sendSymbol(symbol)                  │
        │   │     store_seed_message(msg)                   │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.6 模糊测试循环                               │
        │   ├───────────────────────────────────────────────┤
        │   │ while fuzzing:                                │
        │   │   1. connectGNB() - 连接gNB                   │
        │   │                                               │
        │   │   2. 获取有趣消息                              │
        │   │      ins_msg = get_interesting_msg(state)    │
        │   │                                               │
        │   │   3. 发送变异消息                              │
        │   │      sendSymbol("incomingMessage_SIZE")       │
        │   │      msg = sendFuzzingMessage(ins_msg)        │
        │   │                                               │
        │   │   4. 检测崩溃                                  │
        │   │      if_crash = check_amf()                   │
        │   │      if_crash_sm = check_smf()                │
        │   │                                               │
        │   │   5. 检测协议违规                              │
        │   │      violation = oracle.query_message(...)    │
        │   │                                               │
        │   │   6. 检测gNB反馈                              │
        │   │      msg_gnb = gNBsocket.recv()               │
        │   │      if "Error indication" in msg_gnb:        │
        │   │        is_interesting = True                  │
        │   │                                               │
        │   │   7. 存储测试结果                              │
        │   │      store_new_message(...)                   │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.7 RL训练 ⭐核心创新                          │
        │   ├───────────────────────────────────────────────┤
        │   │ if USE_RL:                                    │
        │   │   1. 构建测试结果                              │
        │   │      result = {                               │
        │   │        'crashed': if_crash,                   │
        │   │        'violation': violation,                │
        │   │        'new_state': ...,                      │
        │   │        'interesting': is_interesting          │
        │   │      }                                        │
        │   │                                               │
        │   │   2. 计算奖励                                  │
        │   │      reward = calculate_reward(result)        │
        │   │                                               │
        │   │   3. 获取下一状态特征                          │
        │   │      next_features = extract_features()       │
        │   │                                               │
        │   │   4. 存储经验                                  │
        │   │      memory.append((features, action,         │
        │   │                     reward, next_features))   │
        │   │                                               │
        │   │   5. 训练DQN                                   │
        │   │      if len(memory) >= batch_size:            │
        │   │        sample mini_batch from memory          │
        │   │        compute loss                           │
        │   │        backpropagation                        │
        │   │        update weights                         │
        │   │                                               │
        │   │   6. 更新目标网络                              │
        │   │      if steps % 100 == 0:                     │
        │   │        target_net ← policy_net                │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        ├─▶ ┌───────────────────────────────────────────────┐
        │   │ 3.8 保存状态                                   │
        │   ├───────────────────────────────────────────────┤
        │   │ • 保存状态机: savedFSM_rl.json                │
        │   │ • 保存RL模型: rl_model_real.pth               │
        │   │ • 每50步打印训练进度                          │
        │   └───────────────────────────────────────────────┘
        │                    ↓
        └──────────────────[循环回到3.1]
                           ↓
                    [Ctrl+C or Error]
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. 退出处理                                                  │
├─────────────────────────────────────────────────────────────┤
│ • killCore(), killGNB(), killUE()                           │
│ • 保存最终状态机                                             │
│ • 保存RL模型和统计信息                                       │
│ • 打印RL训练总结                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 关键算法实现

### 算法1：消息变异

```cpp
// nas_mutator.cpp
void mutate_pdu(OctetString &pdu)
{
    int len = pdu.length();
    int pos = generate_int(len);  // 随机位置
    int op = generate_int(3);     // 3种操作
    
    if (op == 0) {
        // 修改随机字节
        pdu.data()[pos] = generate_bit(8);
    }
    else if (op == 1) {
        // 删除随机字节
        pdu = pdu.subCopy(0, pos) + pdu.subCopy(pos+1);
    }
    else {
        // 插入随机字节
        pdu = pdu.subCopy(0, pos) + 
              byte(generate_bit(8)) + 
              pdu.subCopy(pos);
    }
}
```

**变异策略**:
- 50%概率：结构级变异（解码→变异→编码）
- 50%概率：字节级变异（直接修改PDU字节）

### 算法2：Oracle状态推理

```python
def find_state_rec(path, state, index):
    """
    递归推理当前协议状态
    
    状态转换规则:
    I -> N: registrationRequest收到
    N -> S: securityModeComplete发送
    S -> R: registrationComplete发送
    R -> D: deregistrationRequest发送
    """
    if state == "I":  # 初始状态
        if "registrationRequest" in path.input[index]:
            return find_state_rec(path, "N", index)
    
    elif state == "N":  # 无安全上下文
        if path.output[index] == "securityModeCommand":
            if path.input[index+1] == "securityModeComplete":
                return find_state_rec(path, "S", index+1)
    
    elif state == "S":  # 安全上下文已建立
        if path.output[index] == "registrationAccept":
            if path.input[index+1] == "registrationComplete":
                return find_state_rec(path, "R", index+1)
    
    elif state == "R":  # 已注册
        if path.input[index] == "deregistrationRequest":
            return find_state_rec(path, "D", index)
    
    return state
```

### 算法3：崩溃检测

```python
def check_amf():
    """
    探测AMF是否崩溃
    """
    # 标准注册流程
    expected_flow = [
        ("registrationRequest", "authenticationRequest"),
        ("authenticationResponse", "securityModeCommand"),
        ("securityModeComplete", "registrationAccept"),
        ("registrationComplete", "configurationUpdateCommand")
    ]
    
    # 执行流程
    for input_msg, expected_output in expected_flow:
        output = sendSymbol(input_msg)
        
        if output != expected_output:
            # AMF行为异常，可能已崩溃
            return True
    
    return False  # AMF正常
```

---

## 📊 数据流图

### 测试数据流

```
UE (UERANSIM)
    │
    │ NAS消息（变异后）
    ↓
gNB (UERANSIM)
    │
    │ NGAP包装
    ↓
AMF (Open5GS)
    │
    │ 处理并响应
    ↓
gNB
    │
    │ 响应消息
    ↓
UE
    │
    │ 测试结果
    ↓
CoreFuzzer
    │
    │ 提取特征
    ↓
RL Scheduler
    │
    │ 计算奖励
    ↓
DQN Network
    │
    │ 更新Q值
    ↓
[下次选择更优状态]
```

### 学习数据流

```
测试执行
    ↓
(state_features, action, reward, next_features, done)
    ↓
经验回放缓冲区 (Replay Buffer)
    ↓
采样Mini-Batch (64个经验)
    ↓
计算目标Q值: y = r + γ·max Q'(s', a')
    ↓
计算当前Q值: Q(s, a)
    ↓
计算Loss: MSE(Q, y)
    ↓
反向传播更新网络权重
    ↓
[策略改进]
```

---

## 🔍 详细执行流程示例

### 单次迭代的完整流程

```
迭代 #N:
═══════════════════════════════════════════════════════════

1. 重置环境
   └─ IMSI_OFFSET: 75

2. RL选择状态
   ├─ 提取特征: [0.74, 0.96, 0.85, 15.3, 0.0, 0.12, 5.2, 2.1, 0.29, 0.35]
   ├─ Epsilon: 0.653
   ├─ 随机数: 0.734 > 0.653 → 利用模式
   ├─ Q值: [12.3, 8.5, 15.7, ..., 45.2, ...]
   └─ 选择: s11 (Q值最高: 45.2)

3. 执行路径
   └─ 路径: s0 → s1 → s3 → s11
       消息序列:
       ├─ registrationRequest → authenticationRequest ✓
       ├─ authenticationResponse → securityModeCommand ✓
       ├─ securityModeComplete → registrationAccept ✓
       └─ registrationComplete → configurationUpdateCommand ✓

4. 启用模糊测试
   └─ enableFuzzing → "Start fuzzing" ✓

5. 收集种子消息
   ├─ registrationRequest → 7E004179...
   ├─ authenticationResponse → 7E005700...
   ├─ securityModeComplete → 7E005D00...
   └─ 存储到数据库

6. 模糊测试循环
   ├─ 连接gNB ✓
   ├─ 获取消息: PDUSessionEstablishmentRequest (size=38)
   ├─ 发送变异消息: 
   │   原始: 7E00670100042E0000D41201
   │   变异: 7E68670100052E0102CD6F1201
   │   类型: 结构级变异, sht=2, secmod=2
   │
   ├─ 检测AMF: 
   │   └─ 正常 ✓
   │
   ├─ 检测gNB反馈:
   │   └─ 无反馈
   │
   ├─ 检测违规:
   │   └─ oracle.query_message() → False
   │
   └─ 检测SMF:
       └─ 正常 ✓

7. RL训练 ⭐
   ├─ 构建结果: {crashed: False, violation: False, 
   │              new_state: False, interesting: True}
   │
   ├─ 计算奖励: +10 (interesting message)
   │
   ├─ 存储经验: (features, action=11, reward=10, next_features, False)
   │
   ├─ 训练网络:
   │   ├─ 采样batch: 64个经验
   │   ├─ 前向传播: Q(s,a)
   │   ├─ 计算目标: y = r + 0.99×max Q'(s')
   │   ├─ 计算loss: MSE = 125.43
   │   ├─ 反向传播: ∇θ Loss
   │   └─ 更新权重: θ ← θ - α∇θ
   │
   └─ 更新统计: 
       ├─ Steps: 142
       ├─ Epsilon: 0.653 → 0.649
       └─ Avg Reward: 12.8

8. 保存状态
   ├─ savedFSM_rl.json (状态机)
   └─ 每50步保存一次模型

═══════════════════════════════════════════════════════════
下一次迭代...
```

---

## 📈 RL学习过程

### Epsilon衰减曲线

```
Iteration    Epsilon    行为模式
─────────────────────────────────
0-50        1.0-0.8     完全探索
51-200      0.8-0.5     探索为主
201-400     0.5-0.2     平衡
401-700     0.2-0.05    利用为主
700+        0.05-0.01   完全利用
```

### Q值收敛过程

```
初期 (0-100):
  - Q值随机初始化
  - Loss高（~686）
  - 策略不稳定

中期 (100-300):
  - Q值逐渐收敛
  - Loss下降（~120）
  - 策略改进

后期 (300-500):
  - Q值稳定
  - Loss低（~100）
  - 策略成熟
```

---

## 🎯 关键创新点总结

### vs 原版ProbeFuzzer (PowerSchedule)

| 维度 | 原版 | RL版本 | 优势 |
|-----|------|--------|------|
| **状态选择** | 加权随机 | DQN智能选择 | 学习最优策略 |
| **适应性** | 静态能量分配 | 动态学习调整 | 自适应优化 |
| **历史利用** | 仅当前状态 | 经验回放学习 | 从历史学习 |
| **探索vs利用** | 固定权重 | 自动平衡 | Epsilon-greedy |
| **优化目标** | 单一能量 | 多维度奖励 | 综合优化 |

### 核心算法特点

1. **端到端学习**: 从原始特征直接学习Q值
2. **经验回放**: 打破样本相关性，提升样本效率
3. **目标网络**: 稳定训练，防止发散
4. **多维度奖励**: 综合考虑多个优化目标
5. **自适应探索**: Epsilon自动衰减

---

## 💻 代码实现关键点

### 关键代码片段

#### 1. RL状态选择（core_fuzzer.py:315-321）
```python
if USE_RL:
    current_features = rl_scheduler.extract_global_features(fsm.states)
    action = rl_scheduler.select_action(current_features, fsm.states)
    curr_state = fsm.states[action]
    print(f"RL选择状态: {curr_state.name} (epsilon={rl_scheduler.epsilon:.3f})")
```

#### 2. RL训练（core_fuzzer.py:538-562）
```python
if USE_RL and rl_scheduler:
    test_result = {...}
    reward = rl_scheduler.calculate_reward(test_result)
    next_features = rl_scheduler.extract_global_features(fsm.states)
    rl_scheduler.store_transition(current_features, action, reward, next_features, done)
    
    if len(rl_scheduler.memory) >= rl_scheduler.batch_size:
        loss = rl_scheduler.train()
```

#### 3. DQN训练（rl_scheduler.py:208-237）
```python
def train(self):
    batch = random.sample(self.memory, self.batch_size)
    states, actions, rewards, next_states, dones = zip(*batch)
    
    current_q = self.policy_net(states).gather(1, actions)
    next_q = self.target_net(next_states).max(1)[0]
    target_q = rewards + (1 - dones) * self.gamma * next_q
    
    loss = F.mse_loss(current_q, target_q)
    
    self.optimizer.zero_grad()
    loss.backward()
    self.optimizer.step()
    
    if self.steps % 100 == 0:
        self.target_net.load_state_dict(self.policy_net.state_dict())
```

---

## 📊 性能对比

### 模拟实验结果

```
指标               基线    RL版本   提升
───────────────────────────────────────
新状态发现          4       6      +50%  ⭐
有趣消息数         329     376    +14.3% ⭐
协议违规            2       2     持平
状态覆盖率        100%    100%    持平
平均奖励           N/A     9.61   新增指标
```

### RL学习统计

```
训练步数: 500
最终Epsilon: 0.11
平均奖励: 9.61
Loss收敛: 686 → 100 (降低85%)
```

---

## 🎓 论文核心论述

### Research Questions

**RQ1**: RL能否改进状态选择策略？
- **答**: ✅ 是，新状态发现提升50%

**RQ2**: RL的学习过程是否收敛？
- **答**: ✅ 是，Loss从686降到100

**RQ3**: RL在探索和利用之间如何平衡？
- **答**: ✅ Epsilon-greedy自动平衡

**RQ4**: 相比传统方法，RL的优势在哪？
- **答**: ✅ 自适应学习、历史利用、智能探索

---

## 📝 总结

### 算法流程核心

1. **状态机学习**: TTT算法 → 学习5G NAS协议状态机
2. **RL训练**: DQN算法 → 学习最优状态选择策略
3. **模糊测试**: 变异算法 → 生成测试消息
4. **漏洞检测**: Oracle算法 → 检测崩溃和违规

### 运行流程核心

1. **初始化**: 加载状态机 + 初始化RL
2. **主循环**: 
   - RL选择状态
   - 执行测试
   - 收集奖励
   - 训练网络
3. **保存**: 状态机 + RL模型

### 关键创新

**用DQN替代简单的能量调度，实现智能化、自适应的状态选择！**

---

**这就是RL-ProbeFuzzer的完整算法和运行流程！** 🎉


