# RL-ProbeFuzzer 详细运行过程指南

## 📋 目录

1. [运行环境准备](#运行环境准备)
2. [程序启动流程](#程序启动流程)
3. [单次迭代详细流程](#单次迭代详细流程)
4. [实时输出解读](#实时输出解读)
5. [运行示例](#运行示例)
6. [常见问题处理](#常见问题处理)

---

## 🔧 运行环境准备

### 1. 系统要求

```bash
OS: Ubuntu 20.04+
Python: 3.8+
Docker: 已安装并运行
内存: 8GB+
磁盘: 20GB+
```

### 2. 依赖检查

```bash
# 进入项目目录
cd /home/mm/桌面/ProbeFuzzer/ProbeFuzzer-main/CoreFuzzer

# 检查Python依赖
python3 << 'EOF'
import sys
print(f"Python版本: {sys.version}")

try:
    import torch
    print(f"✓ PyTorch: {torch.__version__}")
except:
    print("✗ PyTorch 未安装")

try:
    import numpy as np
    print(f"✓ NumPy: {np.__version__}")
except:
    print("✗ NumPy 未安装")

try:
    import pymongo
    print("✓ pymongo 已安装")
except:
    print("✗ pymongo 未安装")
EOF
```

### 3. Docker检查

```bash
# 检查Docker容器状态
docker ps | grep corefuzzer

# 应该看到类似输出:
# bdf172fb5587   corefuzzer:sm   "/bin/bash"   Running
```

### 4. 配置检查

```bash
# 检查.env文件
cat .env | head -20

# 应该包含:
# MONGODB_URI=mongodb://...
# CORE_PATH=/open5gs/install/...
# 等配置项
```

---

## 🚀 程序启动流程

### 方式1: 标准启动（推荐）

```bash
cd /home/mm/桌面/ProbeFuzzer/ProbeFuzzer-main/CoreFuzzer

# 使用RL版本
python3 core_fuzzer.py
```

### 方式2: Docker内启动

```bash
# 进入Docker容器
docker exec -it bdf172fb5587 /bin/bash

# 在容器内运行
cd /CoreFuzzer
python3 core_fuzzer.py
```

### 方式3: 后台运行

```bash
# 后台运行并记录日志
nohup python3 core_fuzzer.py > fuzzing.log 2>&1 &

# 查看进程
ps aux | grep core_fuzzer

# 实时查看日志
tail -f fuzzing.log
```

---

## 📊 程序完整启动流程

### 阶段0: 程序初始化（0-5秒）

```
═══════════════════════════════════════════════════════════════
程序: core_fuzzer.py
时间: 0-5秒
═══════════════════════════════════════════════════════════════

[Step 1] 加载配置
  ├─ 读取 .env 文件
  ├─ 解析配置项
  │   ├─ MONGODB_URI
  │   ├─ CORE_PATH
  │   ├─ GNB_PATH
  │   └─ UE_PATH
  └─ ✓ 配置加载完成

[Step 2] 检查USE_RL标志
  ├─ USE_RL = True (line 13)
  └─ ✓ 将使用RL调度器

[Step 3] 加载状态机
  ├─ 读取 savedFSM.json
  ├─ 解析状态: 17个状态
  ├─ 解析转换: 200+条转换
  ├─ 解析路径: 191条路径
  └─ ✓ 状态机加载完成
     输出示例:
     状态列表: s0, s1, s2, ..., s16
     初始状态: s0

[Step 4] 连接数据库
  ├─ 连接MongoDB
  ├─ 选择数据库: corefuzzer
  ├─ 选择集合: messages
  └─ ✓ 数据库连接成功
     输出: Connected to MongoDB

[Step 5] 初始化PowerSchedule（备用）
  ├─ 创建PowerSchedule对象
  ├─ 设置能量参数
  └─ ✓ 备用调度器初始化

[Step 6] 初始化RL调度器 ⭐
  ├─ 检查状态数: 17
  ├─ 创建RLScheduler对象
  │   ├─ 初始化DQN网络
  │   │   ├─ Policy Network: 10→128→128→64→17
  │   │   └─ Target Network: 10→128→128→64→17
  │   ├─ 初始化优化器: Adam(lr=0.001)
  │   ├─ 初始化回放缓冲区: 10,000容量
  │   └─ 初始化参数
  │       ├─ epsilon: 1.0
  │       ├─ gamma: 0.99
  │       └─ batch_size: 64
  ├─ 尝试加载预训练模型
  │   └─ 未找到 rl_model.pth (首次运行)
  └─ ✓ RL调度器初始化完成
     输出: RLScheduler initialized with 17 states

[Step 7] 注册退出处理器
  └─ ✓ exit_handler() 注册完成
```

---

### 阶段1: 环境重置（5-25秒）

```
═══════════════════════════════════════════════════════════════
时间: 5-25秒
操作: 重置测试环境
═══════════════════════════════════════════════════════════════

[Step 1] 停止所有组件
  ├─ killCore()  - 停止Open5GS所有NF
  │   ├─ 停止AMF
  │   ├─ 停止SMF
  │   ├─ 停止UPF
  │   ├─ 停止NRF
  │   ├─ 停止AUSF
  │   ├─ 停止UDM
  │   ├─ 停止PCF
  │   └─ 停止其他NF
  ├─ killGNB()   - 停止gNB
  └─ killUE()    - 停止UE
  输出: Killing all components...

[Step 2] 启动Open5GS
  ├─ startCore()
  │   ├─ 启动NRF (先启动，其他NF依赖它)
  │   ├─ 等待1秒
  │   ├─ 启动AMF, SMF, UPF, AUSF, UDM, PCF等
  │   └─ 等待10秒 (让核心网完全启动)
  └─ ✓ Core network started
     输出: Open5GS components starting...
           Waiting 10 seconds...

[Step 3] 启动gNB
  ├─ startGNB()
  │   └─ 启动UERANSIM gNB
  ├─ 等待0.1秒
  └─ ✓ gNB started

[Step 4] 启动UE
  ├─ startUE()
  │   └─ 启动UERANSIM UE (fuzzing测试用)
  ├─ 等待0.1秒
  └─ ✓ UE started

[Step 5] 重置计数器
  └─ IMSI_OFFSET = 0

总耗时: ~20秒
```

---

### 阶段2: 主测试循环（持续运行）

```
═══════════════════════════════════════════════════════════════
主循环: while True
每次迭代: 30-60秒
═══════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────┐
│ 迭代 #N 开始                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔄 单次迭代详细流程

### Step 1: 轻量级重置（1-2秒）

```
════════════════════════════════════════════════════════════
Step 1: 轻量级重置
════════════════════════════════════════════════════════════

操作:
  ├─ killGNB()      - 停止gNB
  ├─ killUE()       - 停止UE
  ├─ startGNB()     - 重启gNB
  ├─ startUE()      - 重启UE
  └─ IMSI_OFFSET += 1  - 递增IMSI偏移

输出:
  Light reset... IMSI_OFFSET: 75

为什么需要:
  - 清理上次测试的UE状态
  - 避免状态残留影响
  - 每次使用新的IMSI避免冲突
```

---

### Step 2: 连接UE（0.5秒）

```
════════════════════════════════════════════════════════════
Step 2: 连接UE Socket
════════════════════════════════════════════════════════════

操作:
  ├─ connectUE()
  │   ├─ 创建Socket
  │   ├─ 连接到 127.0.0.1:45678
  │   └─ 设置超时: 30秒
  └─ ✓ UE连接成功

输出:
  Connecting to UE...
  UE connected

异常处理:
  - 如果连接超时（重试10次后full_reset）
  - 如果连接失败（重新启动UE）
```

---

### Step 3: RL状态选择 ⭐（0.1秒）

```
════════════════════════════════════════════════════════════
Step 3: RL智能状态选择 (核心创新)
════════════════════════════════════════════════════════════

[3.1] 提取全局特征
  ├─ 调用: current_features = rl_scheduler.extract_global_features(fsm.states)
  └─ 返回: 10维特征向量
     
     特征内容:
     features[0] = 0.74   # 总执行次数/1000
     features[1] = 0.96   # 总路径数/200
     features[2] = 0.85   # 状态数/20
     features[3] = 15.3   # 访问方差（不平衡度）
     features[4] = 0.0    # 未访问状态比例
     features[5] = 0.12   # 低访问状态比例
     features[6] = 5.2    # 平均能量
     features[7] = 2.1    # 能量标准差
     features[8] = 0.29   # 已注册状态比例
     features[9] = 0.35   # 安全上下文状态比例

[3.2] Epsilon-greedy选择
  ├─ 当前epsilon: 0.653
  ├─ 生成随机数: 0.734
  ├─ 0.734 > 0.653 → 利用模式
  └─ 调用DQN网络预测Q值

[3.3] DQN网络前向传播
  ├─ 输入: features (10维)
  ├─ fc1: 10 → 128, ReLU
  ├─ fc2: 128 → 128, ReLU  
  ├─ fc3: 128 → 64, ReLU
  ├─ fc4: 64 → 17 (Q值)
  └─ 输出Q值:
     s0:  12.3
     s1:  8.5
     s2:  15.7
     ...
     s11: 45.2  ← 最高
     ...
     s16: 7.1

[3.4] 选择最优动作
  ├─ action = argmax(Q值) = 11
  └─ curr_state = fsm.states[11]  (s11)

输出:
  RL选择状态: s11 (epsilon=0.653)

对比（如果USE_RL=False）:
  # 使用PowerSchedule
  schedule.adjustEnergy(fsm.states)
  curr_state = schedule.choose(fsm.states)  # 加权随机
  输出: 选择状态: s7
```

---

### Step 4: 执行路径到目标状态（5-10秒）

```
════════════════════════════════════════════════════════════
Step 4: 执行路径序列
════════════════════════════════════════════════════════════

[4.1] 选择路径
  ├─ curr_state = s11 (已注册状态)
  ├─ path = curr_state.select_path()
  └─ 选中路径: s0 → s1 → s3 → s11
     
     路径详情:
     ├─ input_symbols:  [registrationRequest, authenticationResponse, 
     │                   securityModeComplete, registrationComplete]
     └─ output_symbols: [authenticationRequest, securityModeCommand,
                         registrationAccept, configurationUpdateCommand]

[4.2] 执行路径 (execSequence)
  
  发送消息1:
    ├─ 发送: registrationRequest
    ├─ 期望: authenticationRequest
    ├─ 实际: authenticationRequest
    └─ ✓ 匹配，继续
    输出: s0 → s1: registrationRequest → authenticationRequest

  发送消息2:
    ├─ 发送: authenticationResponse
    ├─ 期望: securityModeCommand
    ├─ 实际: securityModeCommand
    └─ ✓ 匹配，继续
    输出: s1 → s3: authenticationResponse → securityModeCommand

  发送消息3:
    ├─ 发送: securityModeComplete
    ├─ 期望: registrationAccept
    ├─ 实际: registrationAccept
    └─ ✓ 匹配，继续
    输出: s3 → s5: securityModeComplete → registrationAccept

  发送消息4:
    ├─ 发送: registrationComplete
    ├─ 期望: configurationUpdateCommand
    ├─ 实际: configurationUpdateCommand
    └─ ✓ 匹配，到达目标
    输出: s5 → s11: registrationComplete → configurationUpdateCommand

[4.3] 到达目标状态
  └─ ✓ 成功到达 s11
     输出: Reached target state: s11

异常处理:
  - 如果响应不匹配 → reset_count++, 重试
  - 如果超时 → full_reset
```

---

### Step 5: 启用模糊测试（0.1秒）

```
════════════════════════════════════════════════════════════
Step 5: 启用模糊测试模式
════════════════════════════════════════════════════════════

[5.1] 发送启用命令
  ├─ sendSymbol("enableFuzzing")
  └─ UE响应: "Start fuzzing"
  输出: Fuzzing enabled

[5.2] 收集种子消息（如果首次测试此状态）
  
  if not curr_state.is_init:
    对每个可用符号:
      ├─ 发送: registrationRequest
      ├─ 接收消息
      ├─ 解析: {"send_type": "...", "new_msg": "7E00...", ...}
      └─ 存储到数据库
      
      重复所有enabled符号...
    
  curr_state.is_init = True
  
  输出:
    Collecting seed messages...
    Stored: registrationRequest
    Stored: authenticationResponse
    ...
```

---

### Step 6: 模糊测试循环（主要时间）

```
════════════════════════════════════════════════════════════
Step 6: 模糊测试执行 (10-30秒)
════════════════════════════════════════════════════════════

while fuzzing:

  [6.1] 连接gNB
    └─ connectGNB() - Socket连接到gNB端口
    输出: Connecting to gNB...

  [6.2] 获取有趣消息
    ├─ ins_msg = get_insteresting_msg(state="s11")
    └─ 从数据库查询当前状态的有趣消息
       返回: {
         "send_type": "PDUSessionEstablishmentRequest",
         "new_msg": "7E00670100042E0000D41201...",
         "size": 38,
         "sht": 2,
         "secmod": 2
       }
    输出: Selected message: PDUSessionEstablishmentRequest (size=38)

  [6.3] 通知UE消息大小
    └─ sendSymbol("incomingMessage_38")
    输出: Notified UE: incoming message size 38

  [6.4] 发送变异消息 ⭐
    ├─ sendFuzzingMessage(ins_msg["new_msg"].encode())
    │   
    │   UE端（C++）:
    │   ├─ 接收原始消息: 7E00670100042E0000D41201...
    │   ├─ 决定变异类型: 50%结构级 或 50%字节级
    │   │
    │   ├─ 如果结构级变异:
    │   │   ├─ 解码NAS消息
    │   │   ├─ 变异字段（IE修改、添加、删除）
    │   │   └─ 重新编码
    │   │
    │   └─ 如果字节级变异:
    │       ├─ 随机选择操作（修改/删除/插入字节）
    │       └─ 直接修改PDU字节
    │   
    │   ├─ 变异后: 7E68670100052E0102CD6F1201...
    │   └─ 发送到AMF
    │
    └─ 接收UE响应
       返回: {
         "ret_type": "PDUSessionEstablishmentAccept",
         "ret_msg": "7E002E0100...",
         "byte_mut": false,
         "sht": 2,
         "secmod": 2,
         "mm_status": "RM-REGISTERED"
       }
    
    输出: Mutated and sent: PDUSessionEstablishmentRequest
          Received: PDUSessionEstablishmentAccept

  [6.5] 探测AMF状态
    ├─ startUE2() - 启动探测UE
    ├─ connectUE2() - 连接探测UE
    ├─ check_amf() - 执行标准注册流程
    │   ├─ 发送: registrationRequest
    │   ├─ 期望: authenticationRequest
    │   └─ 如果收到: authenticationRequest → AMF正常
    │       如果无响应/错误 → AMF崩溃
    └─ if_crash = False (AMF正常)
    
    输出: AMF probe: OK

  [6.6] 检测gNB反馈
    ├─ gNBsocket.recv(1024, timeout=1)
    └─ 收到: "Error indication: Protocol Error"
    
    is_interesting = True
    if_error = True
    error_cause = "Protocol Error"
    
    输出: gNB feedback: Error indication: Protocol Error

  [6.7] 检测协议违规
    ├─ violation = curr_state.oracle.query_message(
    │     send_type="PDUSessionEstablishmentRequest",
    │     ret_type="PDUSessionEstablishmentAccept",
    │     sht=2,
    │     secmod=2
    │   )
    │
    │   Oracle逻辑:
    │   ├─ 当前状态: s11 (已注册，有安全上下文)
    │   ├─ 发送消息: PDUSessionEstablishmentRequest
    │   ├─ 响应消息: PDUSessionEstablishmentAccept
    │   ├─ 检查: 是否符合协议状态机
    │   └─ 结果: 符合规范
    │
    └─ violation = False
    
    输出: Protocol violation: False

  [6.8] 探测SMF状态（如果需要）
    ├─ if ins_msg["send_type"] in symbols_sm:
    │   ├─ startUE3()
    │   ├─ connectUE3()
    │   └─ check_smf()
    └─ if_crash_sm = False
    
    输出: SMF probe: OK

  [6.9] 存储测试结果
    └─ store_new_message(
         state="s11",
         send_type="PDUSessionEstablishmentRequest",
         ret_type="PDUSessionEstablishmentAccept",
         if_crash=False,
         if_crash_sm=False,
         is_interesting=True,
         if_error=True,
         error_cause="Protocol Error",
         ...
       )
    
    输出: Test result stored to MongoDB

  [6.10] 检查是否发现新状态
    ├─ if ret_type != "" and not fsm.search_new_transition(...):
    │   └─ 执行状态学习流程
    │       ├─ 对所有符号执行测试
    │       ├─ 收集响应
    │       ├─ 检查是否映射到已知状态
    │       └─ 如果不是 → 添加新状态
    └─ 本次未发现新状态
    
    输出: No new state discovered

  break  # 每次只测试一个消息

结束模糊测试循环
```

---

### Step 7: RL训练 ⭐（0.2-0.5秒）

```
════════════════════════════════════════════════════════════
Step 7: RL训练和策略更新 (核心创新)
════════════════════════════════════════════════════════════

if USE_RL and rl_scheduler:

  [7.1] 构建测试结果
    test_result = {
        'crashed': False,              # AMF未崩溃
        'protocol_violation': False,   # 无协议违规
        'new_state': False,            # 未发现新状态
        'coverage_increase': 0,        # 覆盖率无增加
        'state_visit_count': 142,      # s11访问次数
        'interesting': True,           # 发现有趣消息
        'error_triggered': True        # 触发错误
    }

  [7.2] 计算奖励
    reward = rl_scheduler.calculate_reward(test_result)
    
    计算过程:
    reward = 0
    + 0      (未崩溃)
    + 0      (无违规)
    + 0      (无新状态)
    + 0      (覆盖率无增加)
    + 20     (有趣消息)
    + 10     (触发错误)
    - 9.2    (过度访问惩罚: (142-50)*0.1)
    = 20.8
    
    输出: Reward: 20.8

  [7.3] 提取下一状态特征
    next_features = rl_scheduler.extract_global_features(fsm.states)
    
    返回: [0.74, 0.96, 0.85, 15.4, 0.0, 0.12, 5.3, 2.1, 0.29, 0.35]

  [7.4] 存储经验
    rl_scheduler.store_transition(
        state_features=current_features,   # 测试前特征
        action=11,                         # 选择的动作(s11)
        reward=20.8,                       # 获得的奖励
        next_state_features=next_features, # 测试后特征
        done=False                         # 未终止
    )
    
    ├─ 添加到回放缓冲区
    └─ 当前缓冲区大小: 142条经验
    
    输出: Experience stored (buffer: 142/10000)

  [7.5] 训练DQN网络
    if len(rl_scheduler.memory) >= rl_scheduler.batch_size:  # 142 >= 64
      
      loss = rl_scheduler.train()
      
      训练过程:
      ────────────────────────────────────
      [1] 采样batch
        └─ batch = random.sample(memory, 64)
        
      [2] 转换为tensor
        ├─ states: Tensor(64, 10)
        ├─ actions: Tensor(64)
        ├─ rewards: Tensor(64)
        ├─ next_states: Tensor(64, 10)
        └─ dones: Tensor(64)
      
      [3] 计算当前Q值
        ├─ Q(s,a) = policy_net(states).gather(1, actions)
        └─ current_q: Tensor(64, 1)
      
      [4] 计算目标Q值
        ├─ next_q = target_net(next_states).max(1)[0]
        ├─ target_q = rewards + (1-dones) * 0.99 * next_q
        └─ target_q: Tensor(64)
      
      [5] 计算Loss
        └─ loss = MSE(current_q, target_q) = 125.43
      
      [6] 反向传播
        ├─ optimizer.zero_grad()
        ├─ loss.backward()
        └─ optimizer.step()
      
      [7] 更新目标网络（如果需要）
        if steps % 100 == 0:
          target_net ← policy_net
        
        (本次: 142 % 100 != 0, 不更新)
      
      [8] 衰减Epsilon
        epsilon = max(0.01, 0.653 * 0.995)
        epsilon = 0.649
      ────────────────────────────────────
      
      输出: [RL训练] Step 142, Loss: 125.43, Epsilon: 0.649, Reward: 20.8

  [7.6] 更新统计
    ├─ total_reward += 20.8
    ├─ steps = 142
    └─ epsilon = 0.649
```

---

### Step 8: 保存状态（每次迭代）

```
════════════════════════════════════════════════════════════
Step 8: 保存状态
════════════════════════════════════════════════════════════

[8.1] 保存状态机
  ├─ 文件: savedFSM_rl.json
  ├─ 内容: 当前FSM状态（17个状态，更新的计数和路径）
  └─ ✓ FSM保存完成

[8.2] 保存RL模型（每10步）
  if rl_scheduler.steps % 10 == 0:
    ├─ rl_scheduler.save_model('rl_model_real.pth')
    ├─ 保存内容:
    │   ├─ policy_net权重
    │   ├─ target_net权重
    │   ├─ optimizer状态
    │   ├─ epsilon值
    │   └─ 步数
    └─ ✓ 模型保存完成
  
  (本次: 142 % 10 == 2, 不保存)

[8.3] 关闭连接
  ├─ gNBsocket.close()
  └─ UEsocket.close()
```

---

### 迭代结束，开始下一次迭代

```
═══════════════════════════════════════════════════════════════
迭代 #142 完成
总耗时: 约45秒
下一次迭代使用更新后的策略 (epsilon=0.649)
═══════════════════════════════════════════════════════════════

[回到Step 1，开始迭代 #143]
```

---

## 📺 实时输出解读

### 完整输出示例

```bash
$ python3 core_fuzzer.py

Connected to MongoDB
Loading FSM from savedFSM.json...
Loaded 17 states, 191 paths
RLScheduler initialized with 17 states
  - Input dim: 10
  - Hidden layers: 128, 128, 64
  - Output dim: 17
  - Device: cpu
  - Memory capacity: 10000
  - Batch size: 64

Starting fuzzing with RL scheduler...

═══════════════════════════════════════════════════════════════
Iteration #1
═══════════════════════════════════════════════════════════════

Light reset... IMSI_OFFSET: 1
Connecting to UE... OK

[RL State Selection]
  Features extracted: [0.00, 0.10, 0.85, 0.0, 0.94, 0.76, 1.0, 0.0, 0.0, 0.0]
  Epsilon: 1.000
  Random action: 3
  Selected state: s3

Executing path to s3...
  s0 → s1: registrationRequest → authenticationRequest
  s1 → s3: authenticationResponse → securityModeCommand
  ✓ Reached target state: s3

Enabling fuzzing...
  Fuzzing enabled: Start fuzzing

Collecting seed messages...
  ✓ Stored: securityModeComplete
  ✓ Stored: registrationRequest
  State initialized

Fuzzing s3...
  Selected message: securityModeComplete (size=12)
  Notified UE: incoming message size 12
  Mutated and sent: securityModeComplete
  Received: registrationAccept
  
  AMF probe: OK
  gNB feedback: (no feedback)
  Protocol violation: False
  SMF probe: OK
  
  ✓ Test result stored

[RL Training]
  Test result: {crashed: False, violation: False, interesting: True}
  Reward: 20.0
  Experience stored (buffer: 1/10000)
  Training skipped (need 64 experiences)

Iteration #1 completed in 38.2s
Next epsilon: 0.995

═══════════════════════════════════════════════════════════════
Iteration #64
═══════════════════════════════════════════════════════════════

Light reset... IMSI_OFFSET: 64
Connecting to UE... OK

[RL State Selection]
  Features extracted: [0.32, 0.48, 0.85, 8.2, 0.12, 0.35, 3.2, 1.5, 0.18, 0.24]
  Epsilon: 0.741
  Random number: 0.823 > 0.741 → Exploit
  Q-values: [12.3, 8.5, 15.7, 22.1, ..., 18.9]
  Selected state: s7 (Q=22.1)

Executing path to s7...
  s0 → s1: registrationRequest → authenticationRequest
  s1 → s3: authenticationResponse → securityModeCommand
  s3 → s5: securityModeComplete → registrationAccept
  s5 → s7: registrationComplete → configurationUpdateCommand
  ✓ Reached target state: s7

Fuzzing s7...
  Selected message: deregistrationRequest (size=15)
  Mutated and sent: deregistrationRequest
  Received: deregistrationAccept
  
  AMF probe: OK
  Protocol violation: True ⚠️
  
  ✓ Test result stored (interesting!)

[RL Training] ⭐ First training!
  Test result: {crashed: False, violation: True, interesting: True}
  Reward: 520.0  (violation +500, interesting +20)
  Experience stored (buffer: 64/10000)
  
  Training DQN...
    Batch sampled: 64 experiences
    Current Q-values computed
    Target Q-values computed
    Loss: 686.2
    Backpropagation completed
    Weights updated
    
  [RL训练] Step 64, Loss: 686.2000, Epsilon: 0.738, Reward: 520.0

Iteration #64 completed in 42.1s

═══════════════════════════════════════════════════════════════
Iteration #142
═══════════════════════════════════════════════════════════════

Light reset... IMSI_OFFSET: 142
Connecting to UE... OK

[RL State Selection]
  Features extracted: [0.74, 0.96, 0.85, 15.3, 0.0, 0.12, 5.2, 2.1, 0.29, 0.35]
  Epsilon: 0.653
  Random number: 0.734 > 0.653 → Exploit
  Q-values: [12.3, 8.5, 15.7, ..., 45.2, ...]
  Selected state: s11 (Q=45.2) ⭐ Learned best state!

Executing path to s11...
  [路径执行...]
  ✓ Reached target state: s11

Fuzzing s11...
  Selected message: PDUSessionEstablishmentRequest (size=38)
  Mutated and sent: PDUSessionEstablishmentRequest
  Received: PDUSessionEstablishmentAccept
  
  gNB feedback: Error indication: Protocol Error
  Protocol violation: False
  
  ✓ Test result stored

[RL Training]
  Test result: {interesting: True, error: True}
  Reward: 20.8 (interesting +20, error +10, over-visit -9.2)
  Experience stored (buffer: 142/10000)
  
  Training DQN...
    Loss: 125.4
    
  [RL训练] Step 142, Loss: 125.4300, Epsilon: 0.649, Reward: 20.8

Iteration #142 completed in 44.8s

═══════════════════════════════════════════════════════════════
... (继续运行)
═══════════════════════════════════════════════════════════════

[Ctrl+C pressed]

Graceful shutdown...
  Stopping all components...
  Saving FSM to savedFSM_rl.json... ✓
  Saving RL model to rl_model_real.pth... ✓
  Saving statistics to rl_stats_real.json... ✓

=== RL训练统计 ===
总步数: 142
最终epsilon: 0.649
平均奖励: 32.5

Program terminated.
```

---

## 🎯 关键输出指标解读

### 1. RL状态选择输出

```
[RL State Selection]
  Features extracted: [0.74, 0.96, ...]  ← 10维特征
  Epsilon: 0.653                         ← 探索率（越来越小）
  Random number: 0.734 > 0.653           ← 利用模式
  Q-values: [12.3, ..., 45.2, ...]       ← 每个状态的价值
  Selected state: s11 (Q=45.2)           ← 选中s11（Q值最高）
```

**解读**：
- Epsilon < 0.7：更多利用学到的知识
- Q=45.2 最高：s11是当前最有价值的状态
- 随机数 > epsilon：使用DQN网络选择

---

### 2. 奖励输出

```
Reward: 520.0 (violation +500, interesting +20)
```

**奖励分解**：
- +1000：崩溃（最高）
- +500：协议违规
- +200：新状态
- +20：有趣消息
- +10：触发错误
- -0.1×N：过度访问惩罚

---

### 3. 训练输出

```
[RL训练] Step 142, Loss: 125.43, Epsilon: 0.649, Reward: 20.8
```

**解读**：
- Step 142：总训练步数
- Loss 125.43：训练损失（从686降到100+）
- Epsilon 0.649：探索率下降（从1.0到0.01）
- Reward 20.8：本次奖励

**Loss趋势**：
- 初期（步数0-100）：Loss 600-400（不稳定）
- 中期（步数101-300）：Loss 400-150（收敛）
- 后期（步数301+）：Loss 150-100（稳定）

---

### 4. 缓冲区状态

```
Experience stored (buffer: 142/10000)
```

**解读**：
- 当前142条经验
- 容量10,000
- 达到64条开始训练

---

## 🔍 常见问题处理

### 问题1: UE连接超时

```
输出: Connecting to UE... Timeout
      Connection timeout, retrying...
```

**原因**: UE未正常启动或端口占用  
**处理**: 
- 自动重试（最多10次）
- 10次后执行full_reset
- 重启所有组件

---

### 问题2: AMF崩溃检测

```
输出: AMF probe: FAILED ⚠️
      if_crash = True
```

**处理**:
- 记录崩溃信息
- 奖励+1000
- 执行full_reset
- 继续测试

---

### 问题3: 训练Loss震荡

```
输出: Loss: 686.2 → 420.5 → 650.3 → 380.2 ...
```

**原因**: 训练初期正常现象  
**处理**: 
- 继续训练
- Loss会逐渐收敛
- 目标网络每100步更新一次稳定训练

---

### 问题4: Epsilon不下降

```
输出: Epsilon: 1.000 → 1.000 → 1.000 ...
```

**原因**: 未进入训练（经验不足64条）  
**检查**: 
- 查看buffer大小
- 等待达到64条经验
- Epsilon在训练时才衰减

---

## 📊 性能监控

### 实时监控命令

```bash
# 监控CPU使用
top -p $(pgrep -f core_fuzzer.py)

# 监控内存
watch -n 1 "ps aux | grep core_fuzzer | grep -v grep"

# 监控训练进度
tail -f fuzzing.log | grep "RL训练"

# 查看模型大小
ls -lh rl_model_real.pth

# 查看数据库大小
du -h /var/lib/mongodb/
```

---

## 🎓 总结

### 完整运行时间线

```
时间轴:
0s        - 程序启动
5s        - 初始化完成（RL调度器初始化）
25s       - 环境重置完成
65s       - 迭代#1完成
...       - 持续运行
2880s     - 迭代#64完成，首次训练
6400s     - 迭代#142完成，策略优化显著
...       - 继续运行或停止

平均每次迭代: 40-50秒
运行500次迭代: 约6-7小时
```

---

### 核心流程总结

1. **初始化**（5秒）：加载FSM + 初始化RL
2. **环境重置**（20秒）：启动Open5GS + gNB + UE
3. **主循环**（每次40-50秒）：
   - RL选择状态（0.1秒）⭐
   - 执行路径（10秒）
   - 模糊测试（20秒）
   - RL训练（0.5秒）⭐
   - 保存状态（0.1秒）

---

**这就是RL-ProbeFuzzer的完整运行过程！** 🎉

