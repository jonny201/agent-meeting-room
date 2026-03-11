from __future__ import annotations

from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

from .models import Participant, ParticipantType, RoomStatus, TaskStatus
from .services import MeetingRoomService


def create_app(db_path: str | None = None) -> Flask:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent.parent
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )
    app.config["SECRET_KEY"] = "agent-meeting-room-dev"
    app.config["DB_PATH"] = db_path or str(project_root / "data" / "agent_meeting_room.db")

    service = MeetingRoomService(app.config["DB_PATH"])
    app.extensions["meeting_room_service"] = service

    @app.context_processor
    def inject_enums() -> dict[str, object]:
        return {
            "participant_types": ParticipantType,
            "task_statuses": TaskStatus,
            "room_statuses": RoomStatus,
        }

    @app.get("/")
    def home() -> str:
        current_service = _service(app)
        rooms = current_service.list_rooms()
        if not rooms:
            room = current_service.create_room("默认会议室", "通过多角色协作完成任务。", seed_defaults=True)
            return redirect(url_for("dashboard", room_id=room.room_id))
        return redirect(url_for("dashboard", room_id=rooms[0].room_id))

    @app.get("/rooms/<room_id>")
    def dashboard(room_id: str) -> str:
        current_service = _service(app)
        state = current_service.get_state(room_id)
        return render_template(
            "dashboard.html",
            rooms=current_service.list_rooms(),
            state=state,
            llm_profiles=current_service.list_llm_profiles(),
            memories=current_service.list_memories(room_id, limit=12),
            decisions=current_service.list_decisions(room_id),
            tools=current_service.list_tools(),
            active_room_id=room_id,
        )

    @app.post("/rooms/create")
    def create_room() -> str:
        current_service = _service(app)
        room = current_service.create_room(request.form.get("room_name", ""), request.form.get("goal", ""), seed_defaults=True)
        flash("新会议室已创建。", "success")
        return redirect(url_for("dashboard", room_id=room.room_id))

    @app.post("/rooms/<room_id>/update")
    def update_room(room_id: str) -> str:
        current_service = _service(app)
        current_service.update_room(room_id, request.form.get("room_name", ""), request.form.get("goal", ""))
        flash("会议室名称和目标已更新。", "success")
        return redirect(url_for("dashboard", room_id=room_id))

    @app.post("/rooms/<room_id>/status")
    def update_room_status(room_id: str) -> str:
        status = RoomStatus(request.form.get("status", RoomStatus.ACTIVE.value))
        _service(app).change_room_status(room_id, status)
        flash("会议室状态已更新。", "success")
        return redirect(url_for("dashboard", room_id=room_id))

    @app.get("/rooms/<room_id>/roles/new")
    def new_role(room_id: str) -> str:
        current_service = _service(app)
        template_id = request.args.get("template_id", "")
        participant = current_service.build_participant_from_template(template_id) if template_id else Participant(
            participant_id="new",
            name="",
            role="",
            participant_type=ParticipantType.AI,
        )
        return render_template(
            "role_editor.html",
            rooms=current_service.list_rooms(),
            active_room_id=room_id,
            room=current_service.get_room(room_id),
            participant=participant,
            tools=current_service.list_tools(),
            role_templates=current_service.list_role_templates(),
            selected_template_id=template_id,
            llm_profiles=current_service.list_llm_profiles(),
            is_new=True,
        )

    @app.get("/rooms/<room_id>/roles/<participant_id>")
    def edit_role(room_id: str, participant_id: str) -> str:
        current_service = _service(app)
        participant = current_service.get_role(room_id, participant_id)
        return render_template(
            "role_editor.html",
            rooms=current_service.list_rooms(),
            active_room_id=room_id,
            room=current_service.get_room(room_id),
            participant=participant,
            tools=current_service.list_tools(),
            role_templates=current_service.list_role_templates(),
            selected_template_id="",
            llm_profiles=current_service.list_llm_profiles(),
            is_new=False,
        )

    @app.post("/rooms/<room_id>/roles/save")
    def save_role(room_id: str) -> str:
        current_service = _service(app)
        participant_type = ParticipantType(request.form.get("participant_type", ParticipantType.HUMAN.value))
        participant_id = request.form.get("participant_id", "").strip()
        tools = request.form.getlist("tools")
        if participant_id and participant_id != "new":
            participant = current_service.get_role(room_id, participant_id)
            participant.name = request.form.get("name", "").strip()
            participant.role = request.form.get("role", "").strip()
            participant.participant_type = participant_type
            participant.description = request.form.get("description", "").strip()
            participant.llm_profile_id = request.form.get("llm_profile_id", "").strip()
            participant.enabled = request.form.get("enabled") == "on"
            participant.tools = tools
            participant.system_prompt = request.form.get("system_prompt", "")
            current_service.save_role(room_id, participant)
        else:
            current_service.add_participant(
                room_id=room_id,
                name=request.form.get("name", ""),
                role=request.form.get("role", ""),
                participant_type=participant_type,
                description=request.form.get("description", ""),
                llm_profile_id=request.form.get("llm_profile_id", ""),
                tools=tools,
                system_prompt=request.form.get("system_prompt", ""),
            )
        flash("角色配置已保存。", "success")
        return redirect(url_for("dashboard", room_id=room_id))

    @app.post("/rooms/<room_id>/messages/send")
    def send_message(room_id: str) -> str:
        current_service = _service(app)
        sender_id = request.form.get("sender_id", "")
        content = request.form.get("content", "")
        auto_ai = request.form.get("auto_ai") == "on"
        latest_message = current_service.post_message(room_id, sender_id, content)
        if auto_ai:
            current_service.drive_room_to_completion(room_id, latest_message)
        flash("消息已发送。", "success")
        return redirect(url_for("dashboard", room_id=room_id) + "#conversation")

    @app.post("/rooms/<room_id>/messages/trigger-ai")
    def trigger_ai(room_id: str) -> str:
        _service(app).drive_room_to_completion(room_id)
        flash("AI 角色已开始回应。", "success")
        return redirect(url_for("dashboard", room_id=room_id) + "#conversation")

    @app.post("/rooms/<room_id>/tasks/add")
    def add_task(room_id: str) -> str:
        current_service = _service(app)
        current_service.add_task(
            room_id=room_id,
            title=request.form.get("title", ""),
            description=request.form.get("description", ""),
            owner_id=request.form.get("owner_id", ""),
            acceptance_criteria=request.form.get("acceptance_criteria", ""),
        )
        current_service.drive_room_to_completion(room_id)
        flash("任务已创建。", "success")
        return redirect(url_for("dashboard", room_id=room_id) + "#tasks")

    @app.post("/rooms/<room_id>/tasks/<task_id>/status")
    def update_task_status(room_id: str, task_id: str) -> str:
        status = TaskStatus(request.form.get("status", TaskStatus.PENDING.value))
        current_service = _service(app)
        current_service.update_task_status(room_id, task_id, status)
        if status in {TaskStatus.REJECTED, TaskStatus.IN_PROGRESS, TaskStatus.PENDING}:
            current_service.drive_room_to_completion(room_id)
        flash("任务状态已更新。", "success")
        return redirect(url_for("dashboard", room_id=room_id) + "#tasks")

    @app.post("/rooms/<room_id>/review")
    def review(room_id: str) -> str:
        approved = request.form.get("approved") == "true"
        _service(app).record_review(
            room_id=room_id,
            approved=approved,
            reviewer_name=request.form.get("reviewer_name", ""),
            note=request.form.get("note", ""),
        )
        flash("评审结果已记录。", "success")
        return redirect(url_for("dashboard", room_id=room_id) + "#review")

    @app.post("/rooms/<room_id>/memories/add")
    def add_memory(room_id: str) -> str:
        _service(app).add_memory(
            room_id=room_id,
            title=request.form.get("title", ""),
            content=request.form.get("content", ""),
            tags=request.form.get("tags", ""),
            source="manual",
        )
        flash("长期记忆已保存。", "success")
        return redirect(url_for("dashboard", room_id=room_id) + "#memories")

    @app.get("/settings/models")
    def model_settings() -> str:
        current_service = _service(app)
        return render_template("models.html", llm_profiles=current_service.list_llm_profiles(), rooms=current_service.list_rooms())

    @app.post("/settings/models")
    def save_model_settings() -> str:
        current_service = _service(app)
        current_service.save_llm_profile(
            profile_id=request.form.get("profile_id", ""),
            name=request.form.get("name", ""),
            provider=request.form.get("provider", ""),
            model=request.form.get("model", ""),
            base_url=request.form.get("base_url", ""),
            api_key=request.form.get("api_key", ""),
            temperature=float(request.form.get("temperature", "0") or 0),
            max_tokens=int(request.form.get("max_tokens", "8192") or 8192),
            enable_thinking=request.form.get("enable_thinking") == "on",
            is_default=request.form.get("is_default") == "on",
        )
        flash("模型配置已保存。", "success")
        return redirect(url_for("model_settings"))

    return app


def _service(app: Flask) -> MeetingRoomService:
    return app.extensions["meeting_room_service"]