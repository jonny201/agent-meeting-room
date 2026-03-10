# Linux 部署说明

## 1. 同步代码到测试主机

在 Windows PowerShell 中执行：

```powershell
scp -r c:\code\agent-meeting-room root@10.168.21.10:/root/
```

如果只是同步增量文件，也可以在项目根目录执行：

```powershell
scp -r docs src scripts deploy main.py README.md requirements.txt .gitignore .env.example root@10.168.21.10:/root/agent-meeting-room/
```

## 2. 初始化 Python 环境

在 Linux 主机上执行：

```bash
cd /root/agent-meeting-room
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. 配置环境变量

项目根目录提供了 `.env.example`，可以复制为 `.env` 后再按需修改：

```bash
cd /root/agent-meeting-room
cp -n .env.example .env
```

默认参数说明：

- `AMR_HOST=0.0.0.0`：监听全部网卡
- `AMR_PORT=8000`：服务端口
- `AMR_DEBUG=0`：关闭 Flask 调试模式
- `AMR_DISABLE_LLM=1`：离线模式，便于先验证系统功能链路

## 4. 安装为 systemd 服务

推荐直接执行项目内脚本：

```bash
cd /root/agent-meeting-room
chmod +x scripts/install_systemd_service.sh
./scripts/install_systemd_service.sh
```

这个脚本会自动完成以下动作：

- 检查 `.venv` 是否存在
- 如果 `.env` 不存在则自动创建默认配置
- 生成 `/etc/systemd/system/agent-meeting-room.service`
- 执行 `systemctl daemon-reload`
- 执行 `systemctl enable agent-meeting-room`
- 执行 `systemctl restart agent-meeting-room`
- 打印当前服务状态和最近日志

## 5. 常用运维命令

```bash
systemctl status agent-meeting-room --no-pager
systemctl restart agent-meeting-room
systemctl stop agent-meeting-room
journalctl -u agent-meeting-room -f
curl -I http://127.0.0.1:8000
```

## 6. 浏览器访问

测试主机地址：

- http://10.168.21.10:8000

## 7. 说明

- SQLite 数据库默认位于 `data/agent_meeting_room.db`
- 角色配置默认位于 `data/rooms/<room_id>/roles.json`
- systemd 日志统一通过 `journalctl -u agent-meeting-room` 查看
- 如果后续切换到真实大模型，请把 `.env` 中的 `AMR_DISABLE_LLM` 改为 `0` 或删除该变量
- 如果检测到旧版单会议室数据库结构，系统会自动把旧库重命名为 `*.legacy-时间戳.db` 后再重建新库，避免升级时启动失败