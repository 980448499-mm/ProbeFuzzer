#!/bin/bash
# 删除所有与程序运行无关的文档和临时文件

cd /home/mm/桌面/ProbeFuzzer/ProbeFuzzer-main/CoreFuzzer

echo "🗑️  开始清理无关文件..."

# 1. 删除所有中文文档（保留README.md和HOW_TO_RUN.txt）
echo "  删除中文文档..."
rm -f *启动*.md *修复*.md *分析*.md *总结*.md *问题*.md *实验*.md *说明*.md *指南*.md *报告*.md
rm -f *维度*.md *流程图*.md *详解*.md *机制*.md *方案*.md *完成*.md *改进*.md *优化*.md
rm -f *原因*.md *根本*.md *深度*.md *终极*.md *最终*.md *全面*.md *紧急*.md
rm -f 安全vs漏洞*.md 漏洞*.md 模糊测试*.md UE*.md Unknown*.md 代码*.md 
rm -f 奖励*.md 在线学习*.md 四层*.md 十大*.md 状态*.md 网络*.md 训练*.md
rm -f 论文*.md 路径*.md 运行*.md 连接*.md 重置*.md 黄金*.md 消息*.md
rm -f 创新点*.md 减少*.md 关键*.md 所有*.md 强化学习*.md 算法*.md 系统*.md
rm -f 环境*.md 监控*.md 第二步*.md 致命*.md 诊断*.md registrationReject*.md
rm -f s10状态*.md Fuzz阶段*.md MongoDB*.md Core网络*.md P0*.md P1P2*.md
rm -f Epsilon*.md FSM加载*.md RL_vs_*.md

# 2. 删除英文文档（保留README.md和HOW_TO_RUN.txt以及requirements.txt）
echo "  删除英文文档..."
rm -f CODE_VERIFICATION_REPORT.md DIFFERENTIAL_TESTING_GUIDE.md DOCKER_运行指南.md
rm -f DUELING_DQN_COMPLETE.md DUELING_DQN_IMPLEMENTATION.md Dueling_DQN*.md
rm -f FINAL_SUMMARY.md IMPLEMENTATION_PLAN.md PAPER_DRAFT.md
rm -f QUICK_START.md RUN_GUIDE.md fix_port_check_and_ue_socket.md

# 3. 删除旧的日志文件（保留最新的）
echo "  删除旧日志文件..."
rm -f fuzzing_202512*.log error.log statelearner.log rl_real_experiment.log
rm -f 运行说明.txt 文件清单.txt

# 4. 删除旧的crash报告目录
echo "  删除旧crash报告..."
rm -rf crash_reports_202512*/

# 5. 删除旧的模型文件
echo "  删除旧模型文件..."
rm -f rl_model_dueling_202512*.pth rl_model_real*.pth

# 6. 删除旧的统计文件
echo "  删除旧统计文件..."
rm -f rl_stats_dueling_202512*.json rl_stats_real.json rl_stats_latest.json
rm -f rl_vs_no_rl_curves.csv

# 7. 删除旧的FSM文件
echo "  删除旧FSM文件..."
rm -f savedFSM_rl_dueling_202512*.json savedFSM_rl.json savedFSM_latest.json

# 8. 删除备份文件
echo "  删除备份文件..."
rm -f core_fuzzer_backup_original.py core_fuzzer_dueling_backup_complex.py

# 9. 删除无用的shell脚本
echo "  删除临时脚本..."
rm -f fix_ue_complete.sh fix_ue.sh run_fixed_code_in_docker.sh
rm -f diagnose_docker_env.sh diagnose_ue_connection.sh
rm -f run_dueling_dqn.sh run_rl_200_iterations.sh 快速运行.sh
rm -f check_env_in_docker.sh check_env_simple.sh check_status.sh

# 10. 删除无用的Python分析脚本
echo "  删除临时Python脚本..."
rm -f analyze_125_crashes.py analyze_latest_run.py
rm -f demo_dueling_dqn.py run_dueling_dqn_demo.py test_dueling_dqn.py
rm -f verify_real_crashes.py check_environment.py

# 11. 删除Jupyter notebook
echo "  删除Jupyter notebook..."
rm -f not_used.ipynb

# 12. 删除空目录
echo "  清理空目录..."
find . -type d -empty -delete 2>/dev/null || true

# 13. 显示剩余的重要文件
echo ""
echo "✅ 清理完成！剩余的核心文件："
echo ""
ls -lh | grep -E "\.(py|sh|yaml|txt|md)$" | grep -v "^d"

echo ""
echo "📊 磁盘空间节省："
du -sh . 


