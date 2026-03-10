from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .models import ParticipantType, TaskStatus
from .services import MeetingRoomService


class MeetingRoomApp:
    """Desktop prototype with a chat-first layout inspired by messaging tools."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Agent Meeting Room")
        self.root.geometry("1440x860")
        self.root.minsize(1200, 760)

        self.service = MeetingRoomService(
            room_name="产品协作室",
            goal="通过角色协作完成讨论、任务拆解、执行跟踪和评审推进",
        )

        self.sender_var = tk.StringVar()
        self.participant_name_var = tk.StringVar()
        self.participant_role_var = tk.StringVar(value="Expert")
        self.participant_type_var = tk.StringVar(value=ParticipantType.HUMAN.value)
        self.participant_desc_var = tk.StringVar()

        self.task_title_var = tk.StringVar()
        self.task_owner_var = tk.StringVar()
        self.review_reviewer_var = tk.StringVar(value="主持人")

        self._configure_style()
        self._build_layout()
        self.refresh_all()

    def _configure_style(self) -> None:
        self.root.configure(bg="#dbe7d8")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Sidebar.TFrame", background="#f6f9f2")
        style.configure("Panel.TFrame", background="#edf5ea")
        style.configure("Card.TLabelframe", background="#f8fbf6", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background="#f8fbf6", foreground="#22452c")
        style.configure("Primary.TButton", background="#2f7d4a", foreground="#ffffff")
        style.map("Primary.TButton", background=[("active", "#26663d")])
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=12, style="Panel.TFrame")
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(container, style="Panel.TFrame")
        header.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            header,
            text="Agent Meeting Room",
            font=("Microsoft YaHei UI", 20, "bold"),
            background="#edf5ea",
            foreground="#1f3d26",
        ).pack(side=tk.LEFT)
        self.phase_label = ttk.Label(
            header,
            text="",
            font=("Microsoft YaHei UI", 11, "bold"),
            background="#edf5ea",
            foreground="#2f7d4a",
        )
        self.phase_label.pack(side=tk.RIGHT)

        paned = ttk.Panedwindow(container, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        self.left_panel = ttk.Frame(paned, style="Sidebar.TFrame", padding=12)
        self.center_panel = ttk.Frame(paned, style="Panel.TFrame", padding=12)
        self.right_panel = ttk.Frame(paned, style="Sidebar.TFrame", padding=12)

        paned.add(self.left_panel, weight=20)
        paned.add(self.center_panel, weight=50)
        paned.add(self.right_panel, weight=30)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

    def _build_left_panel(self) -> None:
        goal_card = ttk.LabelFrame(self.left_panel, text="Room Goal", style="Card.TLabelframe", padding=10)
        goal_card.pack(fill=tk.X, pady=(0, 10))
        self.goal_label = ttk.Label(
            goal_card,
            text=self.service.state.goal,
            wraplength=280,
            background="#f8fbf6",
            foreground="#22342a",
            font=("Microsoft YaHei UI", 10),
            justify=tk.LEFT,
        )
        self.goal_label.pack(fill=tk.X)

        participants_card = ttk.LabelFrame(self.left_panel, text="Participants", style="Card.TLabelframe", padding=10)
        participants_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.participants_listbox = tk.Listbox(
            participants_card,
            height=18,
            activestyle="none",
            bg="#ffffff",
            fg="#1b2f21",
            font=("Microsoft YaHei UI", 10),
            borderwidth=0,
            highlightthickness=0,
        )
        self.participants_listbox.pack(fill=tk.BOTH, expand=True)

        add_card = ttk.LabelFrame(self.left_panel, text="Add Participant", style="Card.TLabelframe", padding=10)
        add_card.pack(fill=tk.X)

        ttk.Label(add_card, text="Name", background="#f8fbf6").pack(anchor=tk.W)
        ttk.Entry(add_card, textvariable=self.participant_name_var).pack(fill=tk.X, pady=(2, 8))
        ttk.Label(add_card, text="Role", background="#f8fbf6").pack(anchor=tk.W)
        ttk.Entry(add_card, textvariable=self.participant_role_var).pack(fill=tk.X, pady=(2, 8))
        ttk.Label(add_card, text="Type", background="#f8fbf6").pack(anchor=tk.W)
        type_box = ttk.Combobox(
            add_card,
            textvariable=self.participant_type_var,
            values=[ParticipantType.HUMAN.value, ParticipantType.AI.value],
            state="readonly",
        )
        type_box.pack(fill=tk.X, pady=(2, 8))
        ttk.Label(add_card, text="Description", background="#f8fbf6").pack(anchor=tk.W)
        ttk.Entry(add_card, textvariable=self.participant_desc_var).pack(fill=tk.X, pady=(2, 10))
        ttk.Button(add_card, text="Add Role", command=self._on_add_participant, style="Primary.TButton").pack(fill=tk.X)

    def _build_center_panel(self) -> None:
        timeline_card = ttk.LabelFrame(self.center_panel, text="Conversation", style="Card.TLabelframe", padding=10)
        timeline_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.chat_text = tk.Text(
            timeline_card,
            wrap=tk.WORD,
            bg="#ffffff",
            fg="#1d2c22",
            font=("Microsoft YaHei UI", 10),
            borderwidth=0,
            highlightthickness=0,
            padx=12,
            pady=12,
            state=tk.DISABLED,
        )
        self.chat_text.pack(fill=tk.BOTH, expand=True)

        compose_card = ttk.LabelFrame(self.center_panel, text="Compose", style="Card.TLabelframe", padding=10)
        compose_card.pack(fill=tk.X)

        top_row = ttk.Frame(compose_card, style="Panel.TFrame")
        top_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(top_row, text="Sender", background="#f8fbf6").pack(side=tk.LEFT)
        self.sender_box = ttk.Combobox(top_row, textvariable=self.sender_var, state="readonly", width=28)
        self.sender_box.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top_row, text="Trigger AI Replies", command=self._on_trigger_ai).pack(side=tk.RIGHT)

        self.message_input = tk.Text(
            compose_card,
            height=6,
            wrap=tk.WORD,
            font=("Microsoft YaHei UI", 10),
            borderwidth=1,
            relief=tk.FLAT,
        )
        self.message_input.pack(fill=tk.X)
        ttk.Button(compose_card, text="Send Message", command=self._on_send_message, style="Primary.TButton").pack(
            anchor=tk.E, pady=(8, 0)
        )

    def _build_right_panel(self) -> None:
        task_card = ttk.LabelFrame(self.right_panel, text="Tasks", style="Card.TLabelframe", padding=10)
        task_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.task_tree = ttk.Treeview(task_card, columns=("title", "owner", "status"), show="headings", height=10)
        self.task_tree.heading("title", text="Title")
        self.task_tree.heading("owner", text="Owner")
        self.task_tree.heading("status", text="Status")
        self.task_tree.column("title", width=180, anchor=tk.W)
        self.task_tree.column("owner", width=120, anchor=tk.W)
        self.task_tree.column("status", width=120, anchor=tk.W)
        self.task_tree.pack(fill=tk.BOTH, expand=True)

        actions = ttk.Frame(task_card, style="Sidebar.TFrame")
        actions.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(actions, text="In Progress", command=lambda: self._update_selected_task(TaskStatus.IN_PROGRESS)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(actions, text="Review", command=lambda: self._update_selected_task(TaskStatus.AWAITING_REVIEW)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(actions, text="Approve", command=lambda: self._update_selected_task(TaskStatus.APPROVED)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(actions, text="Reject", command=lambda: self._update_selected_task(TaskStatus.REJECTED)).pack(side=tk.LEFT)

        add_task_card = ttk.LabelFrame(self.right_panel, text="Add Task", style="Card.TLabelframe", padding=10)
        add_task_card.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(add_task_card, text="Title", background="#f8fbf6").pack(anchor=tk.W)
        ttk.Entry(add_task_card, textvariable=self.task_title_var).pack(fill=tk.X, pady=(2, 8))
        ttk.Label(add_task_card, text="Owner", background="#f8fbf6").pack(anchor=tk.W)
        self.task_owner_box = ttk.Combobox(add_task_card, textvariable=self.task_owner_var, state="readonly")
        self.task_owner_box.pack(fill=tk.X, pady=(2, 8))
        ttk.Label(add_task_card, text="Description", background="#f8fbf6").pack(anchor=tk.W)
        self.task_desc_text = tk.Text(add_task_card, height=4, wrap=tk.WORD, font=("Microsoft YaHei UI", 10), relief=tk.FLAT)
        self.task_desc_text.pack(fill=tk.X, pady=(2, 8))
        ttk.Label(add_task_card, text="Acceptance", background="#f8fbf6").pack(anchor=tk.W)
        self.task_accept_text = tk.Text(add_task_card, height=3, wrap=tk.WORD, font=("Microsoft YaHei UI", 10), relief=tk.FLAT)
        self.task_accept_text.pack(fill=tk.X, pady=(2, 10))
        ttk.Button(add_task_card, text="Create Task", command=self._on_add_task, style="Primary.TButton").pack(fill=tk.X)

        review_card = ttk.LabelFrame(self.right_panel, text="Review Gate", style="Card.TLabelframe", padding=10)
        review_card.pack(fill=tk.X)
        ttk.Label(review_card, text="Reviewer", background="#f8fbf6").pack(anchor=tk.W)
        ttk.Entry(review_card, textvariable=self.review_reviewer_var).pack(fill=tk.X, pady=(2, 8))
        ttk.Label(review_card, text="Decision Note", background="#f8fbf6").pack(anchor=tk.W)
        self.review_note_text = tk.Text(review_card, height=4, wrap=tk.WORD, font=("Microsoft YaHei UI", 10), relief=tk.FLAT)
        self.review_note_text.pack(fill=tk.X, pady=(2, 10))
        review_actions = ttk.Frame(review_card, style="Sidebar.TFrame")
        review_actions.pack(fill=tk.X)
        ttk.Button(review_actions, text="Approve Next Step", command=lambda: self._on_review(True), style="Primary.TButton").pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4)
        )
        ttk.Button(review_actions, text="Hold", command=lambda: self._on_review(False)).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0)
        )

    def refresh_all(self) -> None:
        # Keep the three panels synchronized after every user action.
        self.phase_label.configure(text=f"Phase: {self.service.state.phase.value}")
        self._refresh_participants()
        self._refresh_messages()
        self._refresh_tasks()

    def _refresh_participants(self) -> None:
        self.participants_listbox.delete(0, tk.END)
        sender_values: list[str] = []
        owner_values: list[str] = []
        for participant in self.service.state.participants:
            label = f"{participant.name} [{participant.role}] ({participant.participant_type.value})"
            self.participants_listbox.insert(tk.END, label)
            sender_values.append(f"{participant.participant_id} | {participant.name}")
            owner_values.append(f"{participant.participant_id} | {participant.name}")
        self.sender_box.configure(values=sender_values)
        self.task_owner_box.configure(values=owner_values)

        if sender_values and self.sender_var.get() not in sender_values:
            self.sender_var.set(sender_values[0])
        if owner_values and self.task_owner_var.get() not in owner_values:
            self.task_owner_var.set(owner_values[0])

    def _refresh_messages(self) -> None:
        self.chat_text.configure(state=tk.NORMAL)
        self.chat_text.delete("1.0", tk.END)
        for message in self.service.state.messages:
            timestamp = message.created_at.strftime("%H:%M:%S")
            line = f"[{timestamp}] {message.sender_name} / {message.sender_role} / {message.kind.value}\n{message.content}\n\n"
            self.chat_text.insert(tk.END, line)
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def _refresh_tasks(self) -> None:
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        for task in self.service.state.tasks:
            self.task_tree.insert("", tk.END, iid=task.task_id, values=(task.title, task.owner_name, task.status.value))

    def _on_add_participant(self) -> None:
        name = self.participant_name_var.get().strip()
        role = self.participant_role_var.get().strip()
        if not name or not role:
            messagebox.showwarning("Missing Data", "Name and role are required.")
            return

        participant_type = ParticipantType(self.participant_type_var.get())
        self.service.add_participant(name, role, participant_type, self.participant_desc_var.get())
        self.service.add_system_message(f"新增角色：{name} [{role}] ({participant_type.value})")
        self.participant_name_var.set("")
        self.participant_desc_var.set("")
        self.refresh_all()

    def _on_send_message(self) -> None:
        sender_value = self.sender_var.get().strip()
        content = self.message_input.get("1.0", tk.END).strip()
        if not sender_value or not content:
            messagebox.showwarning("Missing Data", "Sender and message are required.")
            return

        sender_id = sender_value.split("|", 1)[0].strip()
        latest_message = self.service.post_message(sender_id, content)
        self.message_input.delete("1.0", tk.END)

        # Trigger AI replies automatically after a human message to simulate discussion.
        sender = self.service.get_participant(sender_id)
        if sender.participant_type == ParticipantType.HUMAN:
            self.service.trigger_ai_discussion(latest_message)
        self.refresh_all()

    def _on_trigger_ai(self) -> None:
        self.service.trigger_ai_discussion()
        self.refresh_all()

    def _on_add_task(self) -> None:
        title = self.task_title_var.get().strip()
        owner_value = self.task_owner_var.get().strip()
        description = self.task_desc_text.get("1.0", tk.END).strip()
        acceptance = self.task_accept_text.get("1.0", tk.END).strip()

        if not title or not owner_value:
            messagebox.showwarning("Missing Data", "Task title and owner are required.")
            return

        owner_id = owner_value.split("|", 1)[0].strip()
        self.service.add_task(title, description, owner_id, acceptance)
        self.task_title_var.set("")
        self.task_desc_text.delete("1.0", tk.END)
        self.task_accept_text.delete("1.0", tk.END)
        self.refresh_all()

    def _update_selected_task(self, status: TaskStatus) -> None:
        selected_items = self.task_tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select a task first.")
            return
        self.service.update_task_status(selected_items[0], status)
        self.refresh_all()

    def _on_review(self, approved: bool) -> None:
        reviewer_name = self.review_reviewer_var.get().strip()
        note = self.review_note_text.get("1.0", tk.END).strip()
        if not reviewer_name or not note:
            messagebox.showwarning("Missing Data", "Reviewer and note are required.")
            return
        self.service.record_review(approved, reviewer_name, note)
        self.review_note_text.delete("1.0", tk.END)
        self.refresh_all()


def create_app() -> tk.Tk:
    root = tk.Tk()
    MeetingRoomApp(root)
    return root