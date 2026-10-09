from __future__ import annotations

from workspace_runtime import configure_workspace
configure_workspace()

import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft

from database import Database
from flet_app import EntpFletApp
from markdown_store import MarkdownStore
from tests.desktop_e2e import _walk, _find


class StructureUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root/"ui.db",personal_workspace=True)
        self.task = self.db.create_task(self.db.current_mainline_id(),"算法全流程",is_today=True)
        self.app = EntpFletApp.__new__(EntpFletApp)
        a = self.app
        a.db = self.db
        a.markdown = MarkdownStore(self.root/"markdown")
        a.current_mid = self.db.current_mainline_id()
        a.active_index = a.NAV_CURRENT
        a.selected_day = a.calendar_selected_day = date.today()
        a.calendar_month = date.today().replace(day=1)
        a.selected_task_id = self.task
        a.today_collapsed = {}
        a.rail = SimpleNamespace(selected_index=0)
        a.quick_task_input = ft.TextField(value="尚未提交的任务")
        a.quick_today_input = ft.TextField(value="尚未提交的今日输入")
        a.inline_inspiration_input = ft.TextField(value="尚未提交的灵感")
        a.content_switcher = ft.Container(ft.Column([a.quick_task_input]))
        a.page = SimpleNamespace(controls=[a.content_switcher],overlay=[],update=lambda:None,
                                  _dialogs=SimpleNamespace(controls=[]))
        a._sync_markdown = lambda **kwargs:(a.markdown.sync_all(a.db),True)[1]
        a._write_runtime_error = lambda *_:None
        a._notify_error = lambda *_:None
        a._structure_init()
        self.views = []
        def show(index):
            a.active_index = index
            self.views.append(index)
            a._structure_route = None
            a._structure_fields = {}
            a._structure_flush = None
        a.show_view = show

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def button(self,label):
        for control in _walk(self.app.content_switcher.content):
            if isinstance(control,(ft.FilledButton,ft.TextButton,ft.OutlinedButton)) and control.content==label:
                return control
        raise AssertionError(label)

    def click(self,label):
        self.button(label).on_click(None)

    def test_focus_anchor_shortcut_links_task_and_returns_to_current_view(self):
        a = self.app
        before = dict(self.db.get_task(self.task))
        a.inspiration_capture_open = False
        a.content_switcher.content = a._focus_card(self.db.get_task(self.task))
        self.click("添加外部锚点")
        f = a._structure_fields
        self.assertEqual(f["task"].value,str(self.task))
        f["title"].value = "论文提交"
        f["source"].value = "会议组织方"
        f["kind"].value = "deadline"
        self.click("保存外部锚点")
        self.assertEqual(self.views[-1],a.NAV_CURRENT)
        anchor = self.db.structure_day(self.db.today_iso())["anchors"][0]
        self.assertEqual(anchor["task_id"],self.task)
        self.assertEqual(dict(self.db.get_task(self.task)),before)
        self.assertEqual(len(self.db.list_tasks()),1)

    def test_anchor_shortcut_without_focus_and_edit_preserves_existing_link(self):
        a = self.app
        a.inspiration_capture_open = False
        a.content_switcher.content = a._focus_card(None)
        self.click("添加外部锚点")
        self.assertEqual(a._structure_fields["task"].value,"")
        a.open_anchor(default_task_id=self.task)
        a._structure_fields["task"].value = ""
        a._structure_fields["title"].value = "面试"
        a._structure_fields["source"].value = "公司"
        self.click("保存外部锚点")
        aid = self.db.row("SELECT id FROM external_anchors")[0]
        a.open_anchor(aid,default_task_id=self.task)
        self.assertEqual(a._structure_fields["task"].value,"")

    def test_research_scenario_two_iterations_and_reopen_resume_draft(self):
        a = self.app
        a.open_experiment(task_id=self.task)
        a._structure_fields["question"].value = "网格变化是否符合预期？"
        self.click("开始记录实验")
        fields = a._structure_fields
        fields["method"].value = "运行原算法"
        fields["observation"].value = "非流形边 2"
        fields["next_hypothesis"].value = "修改局部符号"
        self.click("保存实际观察")
        self.assertEqual(len(self.db.task_execution_logs(self.task)),1)
        self.assertEqual(a._structure_fields,{})
        self.click("继续下一次实验")
        self.assertEqual(a._structure_fields["hypothesis"].value,"修改局部符号")
        a._structure_fields["method"].value = "运行修正方案"
        a._structure_fields["method"].on_change(None)
        eid = self.db.row("SELECT id FROM experiments")[0]
        self.db.close()
        self.db = Database(self.root/"ui.db",personal_workspace=True)
        a.db = self.db
        a.open_experiment(experiment_id=eid)
        self.assertEqual(a._structure_fields["method"].value,"运行修正方案")
        a._structure_fields["observation"].value = "非流形边 0"
        self.click("保存实际观察")
        self.assertEqual([r["observation"] for r in self.db.experiment_iterations(eid)],["非流形边 2","非流形边 0"])
        self.click("结束实验并生成总结")
        self.assertIn("非流形边 0",a._structure_fields["summary"].value)
        self.click("保存总结并结束")
        self.assertNotEqual(self.db.get_task(self.task)["status"],"完成")

    def test_waiting_scenario_form_check_then_actionable(self):
        a = self.app
        before = dict(self.db.get_task(self.task))
        a.open_waiting()
        f = a._structure_fields
        for k,v in dict(title="等待薪酬",who="HR",check=self.db.today_iso(),task=str(self.task)).items():
            f[k].value = v
        self.click("保存等待事项")
        wid = self.db.row("SELECT id FROM waiting_items")[0]
        a._waiting_view()
        self.assertEqual(self.db.row("SELECT status FROM waiting_items WHERE id=?",(wid,))[0],"check")
        a.open_waiting(wid)
        f = a._structure_fields
        for k,v in dict(facts="收到方案",state="actionable",has_action="1",action="回复方案").items():
            f[k].value = v
        self.click("保存等待事项")
        self.assertFalse(self.db.task_is_waiting(self.task))
        self.assertEqual(dict(self.db.get_task(self.task)),before)

    def test_recovery_keeps_same_tree_inputs_and_task_context(self):
        a = self.app
        a.open_experiment(task_id=self.task)
        a._structure_fields["question"].value = "未提交的问题"
        previous = a.content_switcher.content
        a.enter_recovery()
        self.assertFalse(a.content_switcher.visible)
        self.assertIs(a.content_switcher.content,previous)
        a._quiet_activity.value = "听音乐"
        a.exit_quiet()
        self.assertIs(a.content_switcher.content,previous)
        self.assertTrue(a.content_switcher.visible)
        self.assertEqual(a._structure_fields["question"].value,"未提交的问题")
        self.assertEqual(a.quick_task_input.value,"尚未提交的任务")
        self.assertEqual(a.selected_task_id,self.task)
        self.assertEqual(self.db.row("SELECT activity FROM recovery_sessions")[0],"听音乐")

    def test_recovery_restart_restores_route_and_exit_context(self):
        a = self.app
        a.open_waiting()
        a._structure_fields["title"].value = "尚未保存的等待事项"
        a.enter_recovery()
        a._quiet_activity.value = "安静休息"
        a._quiet_activity.on_change(None)
        self.db.close()
        self.db = Database(self.root/"ui.db",personal_workspace=True)
        a.db = self.db
        a._quiet_mode = None
        a.page.controls = [a.content_switcher]
        a.content_switcher.visible = True
        a._restore_quiet_startup()
        self.assertEqual(a._quiet_mode,"recovery")
        self.assertEqual(a._structure_fields["title"].value,"尚未保存的等待事项")
        a.exit_quiet()
        self.assertTrue(a.content_switcher.visible)
        self.assertEqual(self.db.get_setting("quiet_context"),"")

    def test_skip_recovery_removes_facts_and_does_not_clear_work(self):
        a = self.app
        a.enter_recovery()
        a._quiet_activity.value = "散步"
        a._skip_recovery()
        a.exit_quiet()
        self.assertEqual(self.db.rows("SELECT * FROM recovery_sessions"),[])
        self.assertEqual(self.db.rows("SELECT * FROM structure_events WHERE entity_type='recovery_sessions'"),[])
        self.assertEqual(a.quick_today_input.value,"尚未提交的今日输入")

    def test_recovery_restart_preserves_subtask_input_and_expanded_context(self):
        a = self.app
        a.expanded_task_ids = {self.task}
        a.subtask_input_parent_id = self.task
        subtask = ft.TextField(hint_text="添加子任务",value="尚未提交的子任务")
        a.content_switcher.content = ft.Column([a.quick_task_input,subtask])
        a.enter_recovery()
        a._quiet_mode = None
        a.expanded_task_ids = set()
        a.subtask_input_parent_id = None
        a.page.controls = [a.content_switcher]
        def rebuild(index):
            self.views.append(index)
            a._structure_route = None
            a.content_switcher.content = ft.Column([a.quick_task_input,ft.TextField(hint_text="添加子任务",value="")])
        a.show_view = rebuild
        a._restore_quiet_startup()
        restored = next(c for c in _walk(a.content_switcher.content) if isinstance(c,ft.TextField) and c.hint_text=="添加子任务")
        self.assertEqual(restored.value,"尚未提交的子任务")
        self.assertEqual(a.expanded_task_ids,{self.task})
        self.assertEqual(a.subtask_input_parent_id,self.task)
        a.exit_quiet()

    def test_quiet_shortcuts_cannot_change_work(self):
        a = self.app
        a.enter_recovery()
        a._handle_task_keyboard_shortcut(SimpleNamespace(key="Enter",shift=True))
        self.assertEqual(len(self.db.list_tasks()),1)
        a.exit_quiet()

    def test_skipping_locked_recovery_document_does_not_trap_user_in_mode(self):
        a = self.app
        a.enter_recovery()
        a.markdown.sync_all(a.db)
        blocked = a.markdown.path_for("recovery",a._quiet_session_id)
        original = Path.unlink
        def unlink(path,*args,**kwargs):
            if path==blocked:
                raise PermissionError("document locked")
            return original(path,*args,**kwargs)
        a._sync_markdown = lambda **_:a.markdown.sync_all(a.db,continue_on_error=True)
        with patch.object(Path,"unlink",new=unlink):
            a._skip_recovery()
            self.assertIsNone(a._quiet_session_id)
            self.assertTrue(a.markdown.last_sync_errors)
            a.exit_quiet()
            self.assertIsNone(a._quiet_mode)
        a._sync_markdown()
        self.assertFalse(blocked.exists())

    def test_evidence_import_is_in_workspace_and_backup_covers_file(self):
        a = self.app
        eid = self.db.create_experiment(self.task,"证据")
        iid = self.db.start_iteration(eid)
        source = self.root/"output.log"
        source.write_text("Edge-CD=0.1",encoding="utf-8")
        target = a.import_experiment_file(iid,source)
        self.assertTrue(target.is_relative_to(a.markdown.root))
        self.assertEqual(target.read_text(encoding="utf-8"),"Edge-CD=0.1")
        self.assertEqual(self.db.row("SELECT kind FROM experiment_evidence")[0],"attachment")

    def test_assessment_clear_and_worry_create_are_real_forms(self):
        a = self.app
        a.open_assessment(self.db.today_iso())
        a._structure_fields["pressure"].value = "高"
        self.click("保存状态记录")
        a.open_assessment(self.db.today_iso())
        a._structure_fields["pressure"].value = ""
        self.click("保存状态记录")
        self.assertIsNone(self.db.row("SELECT pressure FROM daily_assessments")[0])
        a.open_worry()
        a._structure_fields["content"].value = "现实问题"
        self.click("保存")
        self.assertEqual(self.db.row("SELECT content FROM worries")[0],"现实问题")
        self.assertEqual(self.db.list_thoughts(),[])

    def test_rhythm_menu_is_the_single_pacing_entry(self):
        a = self.app
        a.inspiration_capture_open = False
        a.content_switcher.content = a._focus_card(self.db.get_task(self.task))
        labels = [c.content for c in _walk(a.content_switcher.content) if isinstance(c,ft.TextButton)]
        self.assertNotIn("进入恢复状态",labels)
        menu = a._rhythm_menu()
        items = {i.content:i for i in menu.items if i.content}
        self.assertEqual(set(items),{"切换为等待","进入恢复状态","担忧收纳","安静一下"})
        items["切换为等待"].on_click(None)
        self.assertEqual(self.db.get_setting("activity_mode"),"wait")
        self.assertIn("重新进入推进",[i.content for i in a._rhythm_menu(compact=True).items])

    def test_date_and_time_fields_accept_picker_values_and_text(self):
        a = self.app
        a.open_anchor()
        day, start = a._structure_fields["day"], a._structure_fields["start"]
        self.assertIsNotNone(day.suffix_icon)
        self.assertIsNotNone(start.suffix_icon)
        opened = []
        a.page.show_dialog = opened.append
        with patch.object(ft.TextField,"update",lambda self:None):
            day.suffix_icon.on_click(None)
            opened[-1].on_change(SimpleNamespace(control=SimpleNamespace(value=date(2026,3,4))))
            start.suffix_icon.on_click(None)
            from datetime import time
            opened[-1].on_change(SimpleNamespace(control=SimpleNamespace(value=time(7,5))))
        self.assertEqual((day.value,start.value),("2026-03-04","07:05"))
        a._structure_fields["title"].value = "评审会"
        a._structure_fields["source"].value = "组委会"
        self.click("保存外部锚点")
        row = self.db.row("SELECT anchor_date,start_at FROM external_anchors")
        self.assertEqual(row["anchor_date"],"2026-03-04")
        self.assertIn("T07:05",row["start_at"])

    def test_today_structure_collapses_to_summary(self):
        a = self.app
        today = self.db.today_iso()
        self.db.save_anchor(title="组会",source="导师",kind="event",anchor_date=today)
        collapsed = a._today_structure(today)
        texts = [str(c.value) for c in _walk(collapsed) if isinstance(c,ft.Text)]
        self.assertTrue(any("组会" in t for t in texts))
        self.assertFalse(any(isinstance(c,ft.TextButton) and c.content=="添加外部锚点" for c in _walk(collapsed)))
        a.toggle_today_structure()
        expanded = a._today_structure(today)
        self.assertTrue(any(isinstance(c,ft.TextButton) and c.content=="添加外部锚点" for c in _walk(expanded)))

    def test_parent_rows_offer_add_subtask_and_hover_targets_shortcut(self):
        a = self.app
        other = self.db.create_task(a.current_mid,"另一个父任务")
        a.expanded_task_ids = set()
        a.subtask_input_parent_id = None
        a._subtask_shortcut_parent_id = None
        a._quick_task_input_focused = True
        a._quick_today_input_focused = False
        a._active_editor_dialog = None
        a._quiet_mode = None
        a.refresh_current_sections = lambda **_: None
        row = a._task_row(self.db.get_task(other),completed=False,subtasks=[])
        buttons = [c for c in _walk(row) if isinstance(c,ft.IconButton) and c.icon==ft.Icons.ADD_ROUNDED]
        self.assertEqual(len(buttons),1)
        hovered = next(c for c in _walk(row) if isinstance(c,ft.Container) and c.on_hover)
        with patch.object(ft.IconButton,"update",lambda self:None):
            hovered.on_hover(SimpleNamespace(data=True))
        self.assertEqual(buttons[0].opacity,1)
        # Shift+Enter now creates the subtask under the hovered row, not the focus task.
        a.quick_task_input.value = "悬停后的子任务"
        a._handle_task_keyboard_shortcut(SimpleNamespace(key="Enter",shift=True))
        children = [r["title"] for r in self.db.list_subtasks(other)]
        self.assertEqual(children,["悬停后的子任务"])
        self.assertEqual(self.db.list_subtasks(self.task),[])
        buttons[0].on_click(None)
        self.assertEqual(a.subtask_input_parent_id,other)
        done = a._task_row(self.db.get_task(other),completed=True,subtasks=[])
        self.assertFalse(any(isinstance(c,ft.IconButton) and c.icon==ft.Icons.ADD_ROUNDED for c in _walk(done)))

    def test_side_nav_keeps_selected_index_contract(self):
        from flet_app import SideNav
        chosen = []
        nav = SideNav(sections=[("执行",[(0,"当前主线",ft.Icons.FLAG_OUTLINED,ft.Icons.FLAG_ROUNDED),
                                        (1,"今日清单",ft.Icons.CHECKLIST_ROUNDED,ft.Icons.FACT_CHECK_ROUNDED)])],
                      on_select=chosen.append,rhythm=ft.Container(),footer=[])
        nav.selected_index = 1
        item, icon, label = nav._items[1][:3]
        self.assertEqual((nav.selected_index,icon.icon),(1,ft.Icons.FACT_CHECK_ROUNDED))
        item.on_click(None)
        self.assertEqual(chosen,[1])
        nav.set_compact(True)
        self.assertFalse(label.visible)
        self.assertEqual(item.tooltip,"今日清单")


if __name__=="__main__":
    unittest.main()
