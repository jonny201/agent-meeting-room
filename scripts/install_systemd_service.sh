#!/usr/bin/env bash

set -euo pipefail

# 这个脚本用于在 Linux 服务器上把当前项目安装为 systemd 服务。
# 默认会在当前目录生成环境文件，写入 unit 文件，随后执行 daemon-reload、enable 和 restart。

SERVICE_NAME="agent-meeting-room"
WORK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${WORK_DIR}/.env"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_BIN="${WORK_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[ERROR] 未找到虚拟环境解释器: ${PYTHON_BIN}" >&2
  echo "[ERROR] 请先在 ${WORK_DIR} 下执行 python3 -m venv .venv 和 pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'EOF'
AMR_HOST=0.0.0.0
AMR_PORT=8000
AMR_DEBUG=0
AMR_DISABLE_LLM=1
EOF
  echo "[INFO] 已创建默认环境文件: ${ENV_FILE}"
fi

cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=Agent Meeting Room Web Service
After=network.target
Wants=network.target

[Service]
Type=simple
WorkingDirectory=${WORK_DIR}
EnvironmentFile=-${ENV_FILE}
ExecStart=${PYTHON_BIN} ${WORK_DIR}/main.py
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

echo "[INFO] 已写入 systemd 单元文件: ${UNIT_FILE}"

systemctl stop ${SERVICE_NAME} >/dev/null 2>&1 || true
pkill -f "${WORK_DIR}/main.py" >/dev/null 2>&1 || true

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}

sleep 3

if command -v curl >/dev/null 2>&1; then
  echo "[INFO] 本机健康检查"
  health_ok=0
  for _ in 1 2 3 4 5; do
    if curl -I --max-time 5 "http://127.0.0.1:${AMR_PORT:-8000}"; then
      health_ok=1
      break
    fi
    sleep 2
  done
  if [[ "${health_ok}" -ne 1 ]]; then
    echo "[WARN] 本机健康检查暂未通过，下面继续输出 systemd 状态和日志用于排查。"
  fi
fi

echo "[INFO] 当前服务状态"
systemctl --no-pager --full status ${SERVICE_NAME}

echo "[INFO] 最近 30 行日志"
journalctl -u ${SERVICE_NAME} -n 30 --no-pager
