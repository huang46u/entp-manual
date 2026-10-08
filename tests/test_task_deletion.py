from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from backup_service import BackupError, inspect_backup, restore_workspace
from database import Database
from flet_app import EntpFletApp
from markdown_store import MarkdownStore


class TaskDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "tasks.db", personal_workspace=True)
        self.mid = self.db.current_mainline_id()
        self.markdown = MarkdownStore(self.root / "markdown")

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def ui(self):
        app = EntpFletApp.__new__(EntpFletApp)
        app.db = self.db
        app.markdown = self.markdown
        app.expanded_task_ids = set()
        app.subtask_input_parent_id = None
        app._subtask_shortcut_parent_id = None
        self.dialogs = []
        self.messages = []
        app.page = SimpleNamespace(show_dialog=self.dialogs.append, update=lambda: None)
        app._close_dialog = lambda: self.dialogs.pop()
        app._sync_markdown = lambda: (self.markdown.sync_all(self.db), True)[1]
        app._refresh_task_surface = lambda: None
        app._notify_success = self.messages.append
        app._notify_error = self.messages.append
        return app

    def test_personal_workspace_overrides_demo_and_reopens_without_sample_data(self):
        self.assertEqual([row["name"] for row in self.db.list_mainlines()], ["我的主线", "收集箱"])
        self.assertEqual(self.db.list_tasks(), [])
        self.assertEqual(self.db.list_thoughts(), [])
        self.db.close()
        self.db = Database(self.root / "tasks.db", personal_workspace=True, internal_demo=True)
        self.assertEqual(self.db.list_tasks(), [])
        self.assertEqual(self.db.list_thoughts(), [])
        self.assertFalse(self.db.get_setting("internal_demo_version"))

    def test_delete_parent_removes_children_records_and_links_without_affecting_other_tasks(self):
        parent = self.db.create_task(self.mid, "删除父任务", is_today=True)
        child = self.db.create_task(self.mid, "删除子任务", parent_task_id=parent)
        other = self.db.create_task(self.mid, "保留任务", is_today=True)
        thought = self.db.create_thought("保留灵感")
        self.db.link_task(thought, parent)
        self.db.add_task_execution_log(parent, action="完成", complete=True)
        self.assertEqual(self.db.delete_task(parent), [parent, child])
        self.assertIsNone(self.db.get_task(parent))
        self.assertIsNone(self.db.get_task(child))
        self.assertIsNotNone(self.db.get_task(other))
        self.assertIsNotNone(self.db.get_thought(thought))
        self.assertEqual(int(self.db.get_focus_task(self.mid)["id"]), other)
        self.assertEqual(self.db.rows("SELECT * FROM task_execution_logs"), [])
        self.assertEqual(self.db.rows("SELECT * FROM thought_task_links"), [])
        self.assertEqual(self.db.rows("SELECT * FROM task_events WHERE task_id IS NULL"), [])
        self.assertEqual([row["task_id"] for row in self.db.list_daily_entries(self.db.today_iso())], [other])
        self.assertEqual(self.db.rows("PRAGMA foreign_key_check"), [])

    def test_delete_child_preserves_parent_and_sibling(self):
        parent = self.db.create_task(self.mid, "父任务")
        child = self.db.create_task(self.mid, "子任务", parent_task_id=parent)
        sibling = self.db.create_task(self.mid, "兄弟任务", parent_task_id=parent)
        self.assertEqual(self.db.delete_task(child), [child])
        self.assertIsNotNone(self.db.get_task(parent))
        self.assertEqual([row["id"] for row in self.db.list_subtasks(parent)], [sibling])
        self.assertEqual(self.db.delete_task(child), [])

    def test_delete_transaction_rolls_back_history_if_database_rejects_delete(self):
        task = self.db.create_task(self.mid, "事务任务", is_today=True)
        self.db.set_task_completed(task, True)
        events = self.db.rows("SELECT * FROM task_events")
        self.db.conn.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON tasks BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete_task(task)
        self.assertIsNotNone(self.db.get_task(task))
        self.assertEqual(len(self.db.rows("SELECT * FROM task_events")), len(events))
        self.assertEqual(len(self.db.list_daily_entries(self.db.today_iso())), 1)

    def test_ui_cancel_and_backup_failure_leave_task_untouched(self):
        task = self.db.create_task(self.mid, "不能误删", is_today=True)
        app = self.ui()
        app.request_delete_task(task)
        self.dialogs[-1].actions[0].on_click(None)
        self.assertIsNotNone(self.db.get_task(task))
        app.request_delete_task(task)
        with patch("flet_app.export_workspace", side_effect=BackupError("disk unavailable")):
            self.dialogs[-1].actions[1].on_click(None)
        self.assertIsNotNone(self.db.get_task(task))
        self.assertIn("未删除任务", self.messages[-1])

    def test_ui_deletion_backup_restores_text_images_history_and_children(self):
        parent = self.db.create_task(self.mid, "正文任务", description="我的正文", is_today=True)
        child = self.db.create_task(self.mid, "子任务", parent_task_id=parent)
        other = self.db.create_task(self.mid, "不删除")
        self.db.set_task_completed(parent, True)
        self.markdown.sync_all(self.db)
        image = self.markdown.root / "_assets" / "task" / f"T{parent:04d}" / "image.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"durable attachment")
        app = self.ui()
        app.expanded_task_ids.add(parent)
        app.subtask_input_parent_id = parent
        app.request_delete_task(parent)
        self.dialogs[-1].actions[1].on_click(None)
        self.assertIsNone(self.db.get_task(parent))
        self.assertIsNone(self.db.get_task(child))
        self.assertFalse(self.markdown.path_for("task", parent).exists())
        self.assertFalse(image.exists())
        self.assertTrue(self.markdown.path_for("task", other).exists())
        archive = next((self.root / "backups").glob("*.entp.zip"))
        self.assertEqual(inspect_backup(archive).tasks, 3)
        restored_path = self.root / "restored.db"
        restored_markdown = self.root / "restored-markdown"
        restore_workspace(archive, restored_path, restored_markdown)
        restored = Database(restored_path, personal_workspace=True)
        try:
            self.assertEqual(restored.get_task(parent)["description"], "我的正文")
            self.assertIsNotNone(restored.get_task(child))
            self.assertEqual(len(restored.list_daily_entries(restored.today_iso())), 1)
            self.assertEqual((restored_markdown / image.relative_to(self.markdown.root)).read_bytes(), b"durable attachment")
        finally:
            restored.close()
