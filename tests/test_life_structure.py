from __future__ import annotations

from workspace_runtime import configure_workspace
configure_workspace()

import json
import hashlib
import sqlite3
import unittest
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backup_service import export_workspace, inspect_backup, restore_workspace, REQUIRED_TABLES, _validate_database, BackupError
from database import Database, SCHEMA_VERSION
from life_structure import STRUCTURE_TABLES
from markdown_store import MarkdownStore


class LifeStructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "test.db"
        self.db = Database(self.path,personal_workspace=True)
        self.task = self.db.create_task(self.db.current_mainline_id(),"真实技术工作",is_today=True)
        self.md = MarkdownStore(self.root / "markdown")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def reopen(self):
        self.db.close()
        self.db = Database(self.path,personal_workspace=True)

    def experiment(self):
        eid = self.db.create_experiment(self.task,"网格局部拓扑为何错误？")
        iid = self.db.start_iteration(eid)
        self.db.save_iteration_draft(iid,hypothesis="参数过大",method="运行提取算法",observation="发现两个非流形边",next_hypothesis="检查局部符号")
        return eid,iid

    def test_upgrade_218_and_repeat_preserve_old_facts_and_markdown(self):
        self.db.add_task_execution_log(self.task,action="旧工作",result="旧证据",complete=True)
        self.md.sync_all(self.db)
        body = self.md.path_for("task",self.task)
        body.write_text(body.read_text(encoding="utf-8")+"\n我的私人正文\n",encoding="utf-8")
        tables = ["mainlines","tasks","thoughts","daily_entries","task_events","task_execution_logs"]
        before = {t:[tuple(r) for r in self.db.rows(f"SELECT * FROM {t} ORDER BY id")] for t in tables}
        self.db.conn.execute("PRAGMA foreign_keys=OFF")
        for table in STRUCTURE_TABLES:
            self.db.conn.execute(f"DROP TABLE {table}")
        self.db.conn.execute("PRAGMA user_version=218")
        self.db.conn.commit()
        self.reopen()
        self.reopen()
        for table in tables:
            self.assertEqual(before[table],[tuple(r) for r in self.db.rows(f"SELECT * FROM {table} ORDER BY id")])
        self.assertEqual(self.db.row("PRAGMA user_version")[0],SCHEMA_VERSION)
        self.assertEqual(self.db.rows("SELECT * FROM structure_events"),[])
        self.md.sync_all(self.db)
        self.assertIn("我的私人正文",body.read_text(encoding="utf-8"))

    def test_anchor_source_validation_no_task_generation_or_state_change(self):
        before = dict(self.db.get_task(self.task))
        with self.assertRaises(ValueError):
            self.db.save_anchor(title="自设安排",source="",kind="event",anchor_date=self.db.today_iso())
        aid = self.db.save_anchor(title="面试",source="公司 HR",kind="event",anchor_date=self.db.today_iso(),task_id=self.task)
        self.db.set_anchor_status(aid,"ended")
        self.db.set_anchor_status(aid,"ended")
        self.assertEqual(dict(self.db.get_task(self.task)),before)
        self.assertEqual(len(self.db.list_tasks()),1)
        self.assertEqual(len(self.db.rows("SELECT * FROM structure_events")),2)

    def test_future_database_is_not_downgraded(self):
        path = self.root / "future.db"
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA user_version=999")
        connection.close()
        with self.assertRaisesRegex(ValueError,"更新版本"):
            Database(path)
        with self.assertRaisesRegex(BackupError,"更高版本"):
            _validate_database(path)
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0],999)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[])
        finally:
            connection.close()

    def test_existing_empty_workspace_never_receives_demo_records(self):
        path = self.root / "existing-empty.db"
        empty = Database(path,seed_on_empty=False)
        empty.save_worry("已有现实问题")
        empty.close()
        reopened = Database(path,internal_demo=True)
        try:
            self.assertEqual(reopened.list_tasks(),[])
            self.assertEqual(reopened.list_thoughts(),[])
            self.assertEqual(reopened.rows("SELECT * FROM experiments"),[])
            self.assertEqual(reopened.row("SELECT content FROM worries")[0],"已有现实问题")
            self.assertEqual([r["name"] for r in reopened.list_mainlines()],["我的主线","收集箱"])
        finally:
            reopened.close()

    def test_anchor_types_timezone_and_cross_day_validation(self):
        today = date.today()
        start = datetime.now().astimezone().replace(hour=23,minute=30,second=0).isoformat()
        end = (datetime.fromisoformat(start)+timedelta(hours=2)).isoformat()
        aid = self.db.save_anchor(title="外部活动",source="组织方",kind="event",anchor_date=today.isoformat(),start_at=start,end_at=end)
        self.assertIn(aid,[r["id"] for r in self.db.structure_day((today+timedelta(days=1)).isoformat())["anchors"]])
        with self.assertRaises(ValueError):
            self.db.save_anchor(title="投稿",source="会议",kind="deadline",anchor_date=today.isoformat(),start_at=start,end_at=end)
        with self.assertRaises(ValueError):
            self.db.save_anchor(title="活动",source="组织方",kind="event",anchor_date=today.isoformat(),start_at="2026-10-09T10:00:00")

    def test_history_anchor_reschedule_keeps_original_day(self):
        today = date.today()
        yesterday = (today-timedelta(days=1)).isoformat()
        with patch.object(self.db,"today_iso",return_value=yesterday):
            aid = self.db.save_anchor(title="原安排",source="老师",kind="event",anchor_date=yesterday)
        self.db.save_anchor(title="新安排",source="老师",kind="event",anchor_date=today.isoformat(),anchor_id=aid)
        self.assertEqual(self.db.structure_day(yesterday)["anchors"][0]["title"],"原安排")
        self.assertIn(yesterday,self.db.structure_dates())

    def test_three_rounds_reopen_and_exactly_one_old_log_per_round(self):
        eid,iid = self.experiment()
        for n in range(3):
            if n:
                iid = self.db.start_iteration(eid)
                self.db.save_iteration_draft(iid,method=f"修正方案 {n}",observation=f"观察 {n}",next_hypothesis=f"下一轮 {n}")
            log = self.db.record_iteration(iid)
            self.assertEqual(self.db.record_iteration(iid),log)
            self.reopen()
        iterations = self.db.experiment_iterations(eid)
        self.assertEqual([r["round_no"] for r in iterations],[1,2,3])
        self.assertEqual(iterations[0]["observation"],"发现两个非流形边")
        self.assertEqual(len(self.db.task_execution_logs(self.task)),3)
        self.assertEqual(len(self.db.rows("SELECT * FROM task_events WHERE event_type='executed'")),3)
        self.assertEqual(self.db.get_task(self.task)["status"],"今日")
        self.assertEqual(self.db.get_task(self.task)["next_action"],"")
        self.assertEqual(self.db.completion_days(date.today().year,date.today().month),{})

    def test_iteration_cannot_overwrite_observation_and_evidence_is_append_only(self):
        eid,iid = self.experiment()
        self.db.record_iteration(iid)
        with self.assertRaises(ValueError):
            self.db.save_iteration_draft(iid,observation="覆盖")
        self.db.add_experiment_evidence(iid,"Edge-CD 0.02")
        self.db.add_experiment_evidence(iid,"修正说明：单位为毫米")
        self.assertEqual(len(self.db.rows("SELECT * FROM experiment_evidence")),2)
        self.assertEqual(len(self.db.task_execution_logs(self.task)),1)
        self.assertIn("发现两个非流形边",self.db.experiment_summary(eid))

    def test_record_round_rolls_back_log_ledger_and_events_on_failure(self):
        _,iid = self.experiment()
        before = {t:len(self.db.rows(f"SELECT * FROM {t}")) for t in ("task_execution_logs","daily_entries","task_events","structure_events")}
        self.db.conn.execute("CREATE TRIGGER fail_round BEFORE UPDATE OF state ON experiment_iterations BEGIN SELECT RAISE(ABORT,'round failed'); END")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.record_iteration(iid)
        for t,count in before.items():
            self.assertEqual(len(self.db.rows(f"SELECT * FROM {t}")),count)
        self.assertEqual(self.db.row("SELECT state FROM experiment_iterations WHERE id=?",(iid,))[0],"draft")

    def test_wait_check_actionable_without_mutating_task(self):
        before = dict(self.db.get_task(self.task))
        wid = self.db.save_waiting_item(title="薪酬",waiting_for="HR",task_id=self.task,check_date=self.db.today_iso())
        self.assertTrue(self.db.task_is_waiting(self.task))
        self.assertEqual(self.db.refresh_waiting_checks(),1)
        self.assertEqual(self.db.refresh_waiting_checks(),0)
        self.assertEqual(self.db.row("SELECT status FROM waiting_items WHERE id=?",(wid,))[0],"check")
        self.db.save_waiting_item(title="薪酬",waiting_for="HR",task_id=self.task,facts="收到薪酬方案",has_action=True,action="回复方案",status="actionable",item_id=wid)
        self.assertFalse(self.db.task_is_waiting(self.task))
        self.assertEqual(dict(self.db.get_task(self.task)),before)
        self.db.archive_waiting(wid)
        self.db.archive_waiting(wid,False)
        self.assertEqual(self.db.rows("PRAGMA foreign_key_check"),[])

    def test_multiple_waits_and_future_checks(self):
        self.db.save_waiting_item(title="等待审稿",waiting_for="编辑",task_id=self.task,check_date=(date.today()+timedelta(days=7)).isoformat())
        self.assertEqual(self.db.refresh_waiting_checks(),0)
        self.db.save_waiting_item(title="沟通",waiting_for="导师",task_id=self.task,status="actionable",has_action=True,action="发送现有结果")
        self.assertFalse(self.db.task_is_waiting(self.task))

    def test_recovery_reopen_end_skip_and_date_distribution(self):
        sid = self.db.start_recovery("听音乐")
        self.assertEqual(self.db.start_recovery(),sid)
        self.reopen()
        self.assertEqual(self.db.row("SELECT id FROM recovery_sessions WHERE ended_at IS NULL")[0],sid)
        self.db.end_recovery(sid)
        self.db.end_recovery(sid)
        self.assertEqual(len(self.db.structure_day(self.db.today_iso())["recoveries"]),1)
        self.md.sync_all(self.db)
        self.db.skip_recovery_record(sid)
        self.md.sync_all(self.db)
        self.assertNotIn("听音乐",self.md.daily_path(self.db.today_iso()).read_text(encoding="utf-8"))
        self.assertEqual(self.db.rows("SELECT * FROM structure_events WHERE entity_type='recovery_sessions'"),[])

    def test_recovery_context_transaction_rolls_back_on_settings_failure(self):
        self.db.conn.execute("""CREATE TRIGGER fail_quiet_context BEFORE INSERT ON app_settings
            WHEN NEW.key='quiet_context' BEGIN SELECT RAISE(ABORT,'context failed'); END""")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.start_recovery(context={"active_index":0})
        self.assertEqual(self.db.rows("SELECT * FROM recovery_sessions"),[])
        self.assertEqual(self.db.rows("SELECT * FROM structure_events WHERE entity_type='recovery_sessions'"),[])

    def test_deleted_task_preserves_experiments_completion_and_linked_records(self):
        eid,iid = self.experiment()
        self.db.record_iteration(iid)
        self.db.set_task_completed(self.task,True)
        self.db.save_waiting_item(title="等待消息",waiting_for="公司",task_id=self.task)
        self.db.save_worry("担忧现实问题",task_id=self.task)
        self.db.delete_task(self.task)
        self.assertEqual(self.db.row("SELECT task_id FROM experiments WHERE id=?",(eid,))[0],None)
        self.assertEqual(len(self.db.completed_entries_on(self.db.today_iso())),1)
        self.assertEqual(len(self.db.rows("SELECT * FROM task_execution_logs")),1)
        self.assertEqual(self.db.rows("PRAGMA foreign_key_check"),[])
        self.md.sync_all(self.db)
        self.assertIn("发现两个非流形边",self.md.path_for("experiment",eid).read_text(encoding="utf-8"))

    def test_fourteen_days_missing_assessments_and_zero_are_distinct(self):
        days = self.db.structure_review()
        self.assertEqual(len(days),14)
        self.assertTrue(all(d["assessment"] is None for d in days))
        self.db.save_daily_assessment(self.db.today_iso(),autonomous_work=0,pressure="高")
        d = self.db.structure_review()[-1]
        self.assertEqual(d["assessment"]["autonomous_work"],0)
        self.assertIsNone(d["assessment"]["external_anchor"])
        self.db.save_daily_assessment(self.db.today_iso(),pressure=None)
        self.assertIsNone(self.db.structure_day(self.db.today_iso())["assessment"]["pressure"])

    def test_worries_do_not_enter_ideas_or_create_tasks(self):
        before = (len(self.db.list_tasks()),len(self.db.list_thoughts()))
        wid = self.db.save_worry("等待外界答复")
        self.db.save_worry("保留原文",worry_id=wid,archived=True)
        self.assertEqual((len(self.db.list_tasks()),len(self.db.list_thoughts())),before)
        self.db.delete_worry(wid)
        self.assertEqual(self.db.rows("SELECT * FROM worries"),[])

    def test_new_document_sync_does_not_delete_unmanaged_notes(self):
        note = self.md.root / "担忧" / "Q9999.md"
        note.write_text("用户自己写的正文，没有程序管理区",encoding="utf-8")
        self.md.sync_all(self.db)
        self.assertEqual(note.read_text(encoding="utf-8"),"用户自己写的正文，没有程序管理区")

    def test_full_backup_roundtrip_new_entities_drafts_and_attachment(self):
        eid,iid = self.experiment()
        self.db.record_iteration(iid)
        draft = self.db.start_iteration(eid)
        self.db.save_iteration_draft(draft,method="未运行的下一轮")
        self.db.save_anchor(title="投稿",source="会议",kind="deadline",anchor_date=self.db.today_iso())
        self.db.save_activity("自由阅读",self.db.today_iso())
        self.db.save_waiting_item(title="审稿",waiting_for="编辑")
        self.db.start_recovery("休息")
        self.db.save_worry("关注结果")
        self.db.save_daily_assessment(self.db.today_iso(),pressure="适中")
        attachment = self.md.root / "_assets" / "experiments" / str(iid) / "output.txt"
        attachment.parent.mkdir(parents=True)
        attachment.write_text("实际输出",encoding="utf-8")
        self.db.add_experiment_evidence(iid,attachment.relative_to(self.md.root).as_posix(),"attachment")
        self.md.sync_all(self.db)
        before = {t:[tuple(r) for r in self.db.rows(f"SELECT * FROM {t}")] for t in STRUCTURE_TABLES}
        archive = self.root / "full.entp.zip"
        export_workspace(self.db,self.md.root,archive)
        self.assertTrue(STRUCTURE_TABLES <= set(inspect_backup(archive).table_counts))
        restored_path = self.root / "restored.db"
        restored_md = self.root / "restored-md"
        restore_workspace(archive,restored_path,restored_md)
        restored = Database(restored_path,personal_workspace=True)
        try:
            for table in STRUCTURE_TABLES:
                self.assertEqual(before[table],[tuple(r) for r in restored.rows(f"SELECT * FROM {table}")])
            self.assertEqual((restored_md/attachment.relative_to(self.md.root)).read_text(encoding="utf-8"),"实际输出")
        finally:
            restored.close()

    def test_v1_backup_import_and_new_format_manifest_compatibility(self):
        self.md.sync_all(self.db)
        archive = self.root / "v2.entp.zip"
        export_workspace(self.db,self.md.root,archive)
        v1 = self.root / "v1.entp.zip"
        legacy = self.root / "legacy-218.db"
        destination = sqlite3.connect(legacy)
        self.db.conn.backup(destination)
        destination.execute("PRAGMA foreign_keys=OFF")
        for table in STRUCTURE_TABLES:
            destination.execute(f"DROP TABLE {table}")
        destination.execute("PRAGMA user_version=218")
        destination.commit()
        destination.close()
        legacy_bytes = legacy.read_bytes()
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(v1,"w") as target:
            for name in source.namelist():
                data = source.read(name)
                if name=="database/entp.db":
                    data = legacy_bytes
                if name=="manifest.json":
                    manifest = json.loads(data)
                    manifest["format_version"] = 1
                    manifest["table_counts"] = {k:v for k,v in manifest["table_counts"].items() if k in REQUIRED_TABLES}
                    for payload in manifest["payload"]:
                        if payload["path"]=="database/entp.db":
                            payload["size"] = len(legacy_bytes)
                            payload["sha256"] = hashlib.sha256(legacy_bytes).hexdigest()
                    data = json.dumps(manifest).encode()
                target.writestr(name,data)
        self.assertTrue(inspect_backup(v1).tasks)
        restore_workspace(v1,self.root/"v1-restored.db",self.root/"v1-md")
        restored = Database(self.root/"v1-restored.db",personal_workspace=True)
        try:
            self.assertEqual(restored.row("PRAGMA user_version")[0],219)
            self.assertEqual(restored.get_task(self.task)["title"],"真实技术工作")
            self.assertEqual(restored.rows("SELECT * FROM structure_events"),[])
        finally:
            restored.close()


if __name__=="__main__":
    unittest.main()
