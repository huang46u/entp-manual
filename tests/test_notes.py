from __future__ import annotations

from workspace_runtime import configure_workspace
configure_workspace()

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import flet as ft

from database import Database
from flet_app import EntpFletApp
from markdown_store import SYSTEM_END, MarkdownStore
from tests.desktop_e2e import _find, _find_markdown_editor, _walk


class NoteDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "notes.db", personal_workspace=True)
        self.mid = self.db.current_mainline_id()
        self.task = self.db.create_task(self.mid, "学习 Stripe Patterns")
        self.markdown = MarkdownStore(self.root / "markdown")

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_note_belongs_to_mainline_and_optionally_links_task(self):
        loose = self.db.create_note(self.mid, title="  读论文   第一遍 ", body="要点\n")
        linked = self.db.create_note(self.mid, title="复现", task_id=self.task)
        note = self.db.get_note(loose)
        self.assertEqual(note["title"], "读论文 第一遍")
        self.assertEqual(note["body"], "要点")
        self.assertIsNone(note["task_title"])
        self.assertEqual(self.db.get_note(linked)["task_title"], "学习 Stripe Patterns")
        self.assertEqual({int(n["id"]) for n in self.db.list_notes(self.mid)}, {loose, linked})
        self.assertEqual([int(n["id"]) for n in self.db.list_notes(task_id=self.task)], [linked])
        with self.assertRaises(ValueError):
            self.db.create_note(self.mid, task_id=99999)

    def test_update_changes_only_given_fields_and_skips_noop(self):
        note_id = self.db.create_note(self.mid, title="进展", body="旧内容")
        self.db.conn.execute("UPDATE notes SET updated_at = '2000-01-01 00:00:00' WHERE id = ?", (note_id,))
        self.db.update_note(note_id, title="进展", body="旧内容")
        self.assertEqual(self.db.get_note(note_id)["updated_at"], "2000-01-01 00:00:00")
        self.db.update_note(note_id, body="新内容", task_id=self.task)
        note = self.db.get_note(note_id)
        self.assertEqual((note["title"], note["body"], note["task_id"]), ("进展", "新内容", self.task))
        self.assertNotEqual(note["updated_at"], "2000-01-01 00:00:00")
        self.db.update_note(note_id, task_id=None)
        self.assertIsNone(self.db.get_note(note_id)["task_id"])

    def test_deleting_linked_task_keeps_note(self):
        note_id = self.db.create_note(self.mid, title="保留", task_id=self.task)
        self.db.delete_task(self.task)
        note = self.db.get_note(note_id)
        self.assertIsNotNone(note)
        self.assertIsNone(note["task_id"])

    def test_markdown_mirror_keeps_user_text_and_lists_note_in_index(self):
        note_id = self.db.create_note(self.mid, title="读完第 3 节", body="条纹场的定义", task_id=self.task)
        self.markdown.sync_all(self.db)
        path = self.markdown.path_for("note", note_id)
        self.assertEqual(path, self.markdown.root / "笔记" / f"N{note_id:04d}.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("条纹场的定义", content)
        self.assertIn("**关联任务：** 学习 Stripe Patterns", content)
        path.write_text(content + "\n外部补充\n", encoding="utf-8")

        self.db.update_note(note_id, body="更新后的定义")
        self.markdown.sync_all(self.db)
        content = path.read_text(encoding="utf-8")
        self.assertIn("更新后的定义", content)
        self.assertIn("外部补充", content.split(SYSTEM_END, 1)[1])
        index = (self.markdown.root / "笔记" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn(f"N{note_id:04d}.md", index)

    def test_remove_note_documents_deletes_file_and_pasted_images(self):
        note_id = self.db.create_note(self.mid, title="带图")
        self.markdown.sync_all(self.db)
        assets, _prefix = self.markdown.editor_image_context("note", note_id)
        (assets / "a.png").write_bytes(b"png")
        self.markdown.remove_note_documents([note_id])
        self.assertFalse(self.markdown.path_for("note", note_id).exists())
        self.assertFalse(assets.exists())


class NoteUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "ui.db", personal_workspace=True)
        self.mid = self.db.current_mainline_id()
        self.task = self.db.create_task(self.mid, "学习论文")
        self.dialogs: list = []
        self.messages: list = []
        a = self.app = EntpFletApp.__new__(EntpFletApp)
        a.db = self.db
        a.markdown = MarkdownStore(self.root / "markdown")
        a.current_mid = self.mid
        a.active_index = a.NAV_CURRENT
        a._closed = a._exiting = False
        a._active_editor_dialog = None
        a.detail_holder = ft.Container()
        a._side_column = a._notes_card
        a.page = SimpleNamespace(
            show_dialog=self.dialogs.append,
            update=lambda: None,
            run_task=lambda coroutine, *args: coroutine(*args).close(),
        )
        a._close_dialog = self.close_dialog
        a._sync_markdown = lambda **_: (a.markdown.sync_all(a.db), True)[1]
        a._write_runtime_error = lambda *_: None
        a._notify_error = self.messages.append
        a._notify_success = self.messages.append

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def close_dialog(self) -> None:
        dialog = self.dialogs.pop()
        if getattr(dialog, "on_dismiss", None):
            dialog.on_dismiss(None)

    def note_parts(self):
        dialog = self.dialogs[-1]
        title = _find(dialog, ft.TextField, hint_text="笔记标题，例如：读完第 3 节 / 复现进展")
        editor = _find_markdown_editor(dialog)
        close = _find(dialog, ft.IconButton, tooltip="关闭笔记")
        return dialog, title, editor, close

    def test_closing_untouched_new_note_leaves_nothing_behind(self):
        self.app.new_note()
        self.assertEqual(self.app._active_editor_dialog, "note")
        _dialog, _title, _editor, close = self.note_parts()
        close.on_click(None)
        self.assertEqual(self.db.list_notes(), [])
        self.assertEqual(self.dialogs, [])
        self.assertIsNone(self.app._active_editor_dialog)
        self.assertFalse(any((self.app.markdown.root / "_assets" / "note").glob("N*")))

    def test_note_from_task_is_linked_saved_and_listed_on_card(self):
        self.app.new_note(task_id=self.task)
        _dialog, title, editor, close = self.note_parts()
        title.value = "第一遍阅读"
        title.on_change(SimpleNamespace(control=title, data=title.value))
        editor.on_change(SimpleNamespace(control=editor, data="核心想法：用条纹场参数化"))
        close.on_click(None)

        [note] = self.db.list_notes(self.mid)
        self.assertEqual((note["title"], note["body"], note["task_id"]), ("第一遍阅读", "核心想法：用条纹场参数化", self.task))
        document = self.app.markdown.path_for("note", int(note["id"])).read_text(encoding="utf-8")
        self.assertIn("核心想法：用条纹场参数化", document)
        texts = [c.value for c in _walk(self.app.detail_holder.content) if isinstance(c, ft.Text)]
        self.assertIn("第一遍阅读", texts)

    def test_card_offers_full_list_beyond_preview_limit(self):
        for i in range(self.app.NOTE_PREVIEW_LIMIT + 1):
            self.db.create_note(self.mid, title=f"笔记 {i}")
        card = self.app._notes_card()
        more = _find(card, ft.TextButton, content=f"查看全部 {self.app.NOTE_PREVIEW_LIMIT + 1} 篇")
        more.on_click(None)
        rows = [c for c in _walk(self.dialogs[-1]) if isinstance(c, ft.Text) and str(c.value).startswith("笔记 ")]
        self.assertEqual(len(rows), self.app.NOTE_PREVIEW_LIMIT + 1)

    def test_delete_with_content_asks_backs_up_then_removes(self):
        note_id = self.db.create_note(self.mid, title="要删的", body="内容")
        self.app.open_note(note_id)
        _find(self.dialogs[-1], ft.IconButton, tooltip="删除笔记").on_click(None)
        confirm = _find(self.dialogs[-1], ft.FilledButton, content="删除笔记")
        confirm.on_click(None)
        self.assertIsNone(self.db.get_note(note_id))
        self.assertFalse(self.app.markdown.path_for("note", note_id).exists())
        self.assertTrue(list((self.root / "backups").glob("删除笔记前_*.entp.zip")))


if __name__ == "__main__":
    unittest.main()
