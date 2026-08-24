#!/bin/bash

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║   🚀 启动Dueling DQN Fuzzer in Docker                    ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# 进入CoreFuzzer目录
cd "$(dirname "$0")"

echo "当前目录: $(pwd)"
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "  启动Docker容器（交互式）"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "容器启动后，请运行以下命令："
echo ""
echo "  cd /corefuzzer"
echo "  python3 core_fuzzer_dueling.py"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "按回车键启动容器..."
read

# 启动交互式容器
docker run --rm \
  -v $(pwd):/corefuzzer \
  --privileged \
  -it corefuzzer:sm \
  bash

echo ""
echo "容器已退出"








