"""SQLite workflows for life structure; task and completion states stay independent."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta


STRUCTURE_TABLES = {
    "external_anchors", "autonomous_activities", "experiments",
    "experiment_iterations", "experiment_evidence", "waiting_items",
    "recovery_sessions", "worries", "daily_assessments", "structure_events",
}
WAIT_LABELS = {"actionable":"可行动", "waiting":"等待中", "check":"需要检查", "resolved":"已解决"}
ASSESS_LABELS = {"external_anchor":"有真实外部锚点", "autonomous_work":"推进过自主工作",
                 "complete_experiment":"进行过完整实验", "idle_unease":"空闲时感到不安",
                 "pressure":"主观压力", "recovery":"进行过恢复活动"}


def create_structure_schema(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS external_anchors (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('event','deadline')),
            anchor_date TEXT NOT NULL, start_at TEXT NOT NULL DEFAULT '',
            end_at TEXT NOT NULL DEFAULT '', consequence TEXT NOT NULL DEFAULT '',
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ended','cancelled')),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS autonomous_activities (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, activity_date TEXT NOT NULL,
            scheduled_time TEXT NOT NULL DEFAULT '',
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            question TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','paused','ended')),
            summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS experiment_iterations (
            id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id),
            round_no INTEGER NOT NULL, hypothesis TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL DEFAULT '', observation TEXT NOT NULL DEFAULT '',
            next_hypothesis TEXT NOT NULL DEFAULT '', parameters TEXT NOT NULL DEFAULT '',
            input_data TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'draft'
                CHECK(state IN ('draft','recorded')),
            execution_log_id INTEGER UNIQUE REFERENCES task_execution_logs(id) ON DELETE SET NULL,
            event_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(experiment_id, round_no)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_experiment_draft
            ON experiment_iterations(experiment_id) WHERE state='draft';
        CREATE TABLE IF NOT EXISTS experiment_evidence (
            id INTEGER PRIMARY KEY, iteration_id INTEGER NOT NULL REFERENCES experiment_iterations(id),
            kind TEXT NOT NULL CHECK(kind IN ('text','path','attachment')),
            value TEXT NOT NULL, created_at TEXT NOT NULL, event_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS waiting_items (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            facts TEXT NOT NULL DEFAULT '', waiting_for TEXT NOT NULL DEFAULT '',
            has_action INTEGER NOT NULL DEFAULT 0 CHECK(has_action IN (0,1)),
            action TEXT NOT NULL DEFAULT '', check_date TEXT,
            status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('actionable','waiting','check','resolved')),
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_waiting_check ON waiting_items(status, check_date, archived);
        CREATE TABLE IF NOT EXISTS recovery_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, ended_at TEXT,
            activity TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_open_recovery
            ON recovery_sessions((1)) WHERE ended_at IS NULL;
        CREATE TABLE IF NOT EXISTS worries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
            actionability TEXT NOT NULL DEFAULT 'uncertain' CHECK(actionability IN ('yes','no','uncertain')),
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            waiting_item_id INTEGER REFERENCES waiting_items(id) ON DELETE SET NULL,
            thought_id INTEGER REFERENCES thoughts(id) ON DELETE SET NULL,
            archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_assessments (
            assessment_date TEXT PRIMARY KEY,
            external_anchor INTEGER CHECK(external_anchor IN (0,1)),
            autonomous_work INTEGER CHECK(autonomous_work IN (0,1)),
            complete_experiment INTEGER CHECK(complete_experiment IN (0,1)),
            idle_unease INTEGER CHECK(idle_unease IN (0,1)),
            pressure TEXT CHECK(pressure IN ('轻','适中','高')),
            recovery INTEGER CHECK(recovery IN (0,1)),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS structure_events (
            id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            event_type TEXT NOT NULL, event_date TEXT NOT NULL, occurred_at TEXT NOT NULL,
            before_json TEXT, after_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_structure_entity
            ON structure_events(entity_type,entity_id,id);
        CREATE INDEX IF NOT EXISTS idx_structure_date ON structure_events(event_date,id);
        CREATE INDEX IF NOT EXISTS idx_iteration_date ON experiment_iterations(event_date,state);
    """)


class LifeStructure:
    """Methods mixed into Database, sharing its connection and local date helpers."""

    def _structure_event(self, table, entity_id, event, before, after):
        self.conn.execute(
            """INSERT INTO structure_events(entity_type,entity_id,event_type,event_date,
               occurred_at,before_json,after_json) VALUES (?,?,?,?,?,?,?)""",
            (table, str(entity_id), event, self.today_iso(), self.local_timestamp(),
             json.dumps(dict(before), ensure_ascii=False) if before else None,
             json.dumps(dict(after), ensure_ascii=False) if after else None),
        )

    def _structure_write(self, table, values, entity_id=None, *, event="updated"):
        if table not in STRUCTURE_TABLES - {"structure_events", "daily_assessments"}:
            raise ValueError("不支持的数据类型")
        columns = {r["name"] for r in self.conn.execute(f'PRAGMA table_info("{table}")')}
        if not set(values) <= columns - {"id", "created_at", "updated_at"}:
            raise ValueError("不支持的字段")
        now = self.local_timestamp()
        with self.conn:
            before = self.row(f'SELECT * FROM "{table}" WHERE id=?', (entity_id,)) if entity_id else None
            if entity_id is not None and before is None:
                raise ValueError("记录不存在")
            # Repeated transitions and unchanged form submissions add no events.
            if before and all(before[k] == v for k, v in values.items()):
                return int(entity_id)
            values = dict(values, updated_at=now)
            if entity_id is None:
                values["created_at"] = now
                names = ",".join(values)
                cur = self.conn.execute(
                    f'INSERT INTO "{table}"({names}) VALUES ({",".join("?" for _ in values)})',
                    tuple(values.values()),
                )
                entity_id = int(cur.lastrowid)
                event = "created"
            else:
                self.conn.execute(
                    f'UPDATE "{table}" SET {",".join(k+"=?" for k in values)} WHERE id=?',
                    (*values.values(), entity_id),
                )
            after = self.row(f'SELECT * FROM "{table}" WHERE id=?', (entity_id,))
            # Draft typing is mutable working context, not an executed fact.
            if not (table == "experiment_iterations" and event == "updated"):
                self._structure_event(table, entity_id, event, before, after)
        return int(entity_id)

    def _require_day(self, value):
        if not self._valid_day(value) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("请输入有效日期，例如 2026-10-09")
        return value

    def _require_task(self, task_id):
        if task_id is not None and self.get_task(task_id) is None:
            raise ValueError("关联任务不存在")

    def save_anchor(self, *, title, source, kind, anchor_date, start_at="", end_at="",
                    consequence="", task_id=None, anchor_id=None, status="active"):
        if not title.strip() or not source.strip():
            raise ValueError("请填写事件名称和真实外部来源；自主安排请使用自主活动")
        self._require_day(anchor_date)
        self._require_task(task_id)
        if kind not in ("event", "deadline") or status not in ("active", "ended", "cancelled"):
            raise ValueError("外部锚点类型或状态无效")
        parsed = []
        for stamp in (start_at, end_at):
            if stamp:
                try:
                    dt = datetime.fromisoformat(stamp)
                except ValueError as error:
                    raise ValueError("时间格式无效") from error
                if dt.utcoffset() is None:
                    raise ValueError("时间需要包含本地时区")
                parsed.append(dt)
        if start_at and datetime.fromisoformat(start_at).date().isoformat() != anchor_date:
            raise ValueError("开始或截止时间需要与所选日期一致")
        if kind == "deadline" and end_at:
            raise ValueError("截止事项只填写截止时间")
        if end_at and not start_at:
            raise ValueError("填写结束时间前请先填写开始时间")
        if len(parsed) == 2 and parsed[1] < parsed[0]:
            raise ValueError("结束时间不能早于开始时间")
        return self._structure_write("external_anchors", dict(
            title=title.strip(), source=source.strip(), kind=kind, anchor_date=anchor_date,
            start_at=start_at, end_at=end_at, consequence=consequence.strip(), task_id=task_id, status=status,
        ), anchor_id)

    def set_anchor_status(self, anchor_id, status):
        if status not in ("active", "ended", "cancelled"):
            raise ValueError("外部锚点状态无效")
        return self._structure_write("external_anchors", {"status": status}, anchor_id, event=status)

    def save_activity(self, title, activity_date, scheduled_time="", task_id=None, activity_id=None):
        if not title.strip():
            raise ValueError("请填写主动选择的活动")
        self._require_day(activity_date)
        self._require_task(task_id)
        if scheduled_time:
            try:
                datetime.strptime(scheduled_time, "%H:%M")
            except ValueError as error:
                raise ValueError("时间请填写 HH:MM，也可以留空") from error
        return self._structure_write("autonomous_activities", dict(
            title=title.strip(), activity_date=activity_date, scheduled_time=scheduled_time, task_id=task_id,
        ), activity_id)

    def create_experiment(self, task_id, question):
        self._require_task(task_id)
        if task_id is None or not question.strip():
            raise ValueError("请关联任务并填写技术问题")
        return self._structure_write("experiments", {"task_id": task_id, "question": question.strip()})

    def experiment_for_task(self, task_id):
        return self.row("SELECT * FROM experiments WHERE task_id=? AND status<>'ended' ORDER BY id DESC LIMIT 1", (task_id,))

    def experiment_iterations(self, experiment_id):
        return self.rows("SELECT * FROM experiment_iterations WHERE experiment_id=? ORDER BY round_no", (experiment_id,))

    def start_iteration(self, experiment_id):
        experiment = self.row("SELECT * FROM experiments WHERE id=?", (experiment_id,))
        if not experiment or experiment["status"] == "ended":
            raise ValueError("实验不存在或已经结束")
        draft = self.row("SELECT * FROM experiment_iterations WHERE experiment_id=? AND state='draft'", (experiment_id,))
        if draft:
            return int(draft["id"])
        previous = self.row("SELECT * FROM experiment_iterations WHERE experiment_id=? ORDER BY round_no DESC LIMIT 1", (experiment_id,))
        return self._structure_write("experiment_iterations", {
            "experiment_id": experiment_id, "round_no": int(previous["round_no"]) + 1 if previous else 1,
            "hypothesis": previous["next_hypothesis"] if previous else "",
        })

    def save_iteration_draft(self, iteration_id, **values):
        allowed = {"hypothesis", "method", "observation", "next_hypothesis", "parameters", "input_data"}
        if not set(values) <= allowed:
            raise ValueError("不支持的实验字段")
        row = self.row("SELECT * FROM experiment_iterations WHERE id=?", (iteration_id,))
        if not row or row["state"] != "draft":
            raise ValueError("已记录的实验不能覆盖，请继续下一轮或追加证据")
        experiment = self.row("SELECT * FROM experiments WHERE id=?", (row["experiment_id"],))
        if experiment["status"] == "ended":
            raise ValueError("实验已经结束")
        return self._structure_write("experiment_iterations", {k: str(v).strip() for k,v in values.items()}, iteration_id)

    def record_iteration(self, iteration_id):
        row = self.row("SELECT * FROM experiment_iterations WHERE id=?", (iteration_id,))
        if not row:
            raise ValueError("实验轮次不存在")
        if row["state"] == "recorded":
            return row["execution_log_id"]
        if not row["method"].strip() or not row["observation"].strip():
            raise ValueError("请填写实际运行的方法与观察结果")
        experiment = self.row("SELECT * FROM experiments WHERE id=?", (row["experiment_id"],))
        if experiment["status"] == "ended":
            raise ValueError("实验已经结束")
        with self.conn:
            log_id = None
            if experiment["task_id"] is not None:
                log_id = self._add_task_execution_log(
                    experiment["task_id"], action=row["method"], result=row["observation"],
                    next_action="", complete=False,
                )
            self.conn.execute("""UPDATE experiment_iterations SET state='recorded', execution_log_id=?,
                event_date=?,updated_at=? WHERE id=?""", (log_id,self.today_iso(),self.local_timestamp(),iteration_id))
            after = self.row("SELECT * FROM experiment_iterations WHERE id=?", (iteration_id,))
            self._structure_event("experiment_iterations", iteration_id, "recorded", row, after)
            self.conn.execute("UPDATE experiments SET updated_at=? WHERE id=?", (self.local_timestamp(), experiment["id"]))
        return log_id

    def add_experiment_evidence(self, iteration_id, value, kind="text"):
        if not self.row("SELECT 1 FROM experiment_iterations WHERE id=?", (iteration_id,)):
            raise ValueError("实验轮次不存在")
        if not value.strip() or kind not in ("text", "path", "attachment"):
            raise ValueError("请填写结果证据")
        if kind == "attachment":
            from pathlib import PurePosixPath
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or "\\" in value or not value.startswith("_assets/experiments/"):
                raise ValueError("附件必须位于实验的受管理目录")
        with self.conn:
            cur = self.conn.execute("""INSERT INTO experiment_evidence(iteration_id,kind,value,created_at,event_date)
                VALUES (?,?,?,?,?)""", (iteration_id,kind,value.strip(),self.local_timestamp(),self.today_iso()))
            row = self.row("SELECT * FROM experiment_evidence WHERE id=?", (cur.lastrowid,))
            self._structure_event("experiment_evidence", cur.lastrowid, "created", None, row)
        return int(cur.lastrowid)

    def set_experiment_status(self, experiment_id, status, summary=None):
        if status not in ("active", "paused", "ended"):
            raise ValueError("实验状态无效")
        values = {"status": status}
        if summary is not None:
            values["summary"] = summary.strip()
        return self._structure_write("experiments", values, experiment_id, event=status)

    def experiment_summary(self, experiment_id):
        experiment = self.row("SELECT * FROM experiments WHERE id=?", (experiment_id,))
        if not experiment:
            raise ValueError("实验不存在")
        lines = [experiment["question"]]
        for iteration in self.experiment_iterations(experiment_id):
            if iteration["state"] == "recorded":
                lines.append(f"第 {iteration['round_no']} 轮：{iteration['method']}\n观察：{iteration['observation']}\n下一假设：{iteration['next_hypothesis']}")
        return "\n\n".join(lines)

    def save_waiting_item(self, *, title, waiting_for, facts="", task_id=None, has_action=False,
                          action="", check_date=None, status="waiting", archived=False, item_id=None):
        if not title.strip() or not waiting_for.strip():
            raise ValueError("请填写事项标题和正在等待谁")
        if status not in ("actionable", "waiting", "check", "resolved"):
            raise ValueError("等待状态无效")
        if check_date:
            self._require_day(check_date)
        self._require_task(task_id)
        if has_action and not action.strip():
            raise ValueError("请写下当前有效行动")
        if status == "actionable" and not has_action:
            raise ValueError("可行动状态需要填写有效行动")
        return self._structure_write("waiting_items", dict(
            title=title.strip(),waiting_for=waiting_for.strip(),facts=facts.strip(),task_id=task_id,
            has_action=int(bool(has_action)),action=action.strip(),check_date=check_date or None,
            status=status,archived=int(bool(archived)),
        ), item_id)

    def refresh_waiting_checks(self, today=None):
        today = self._require_day(today or self.today_iso())
        rows = self.rows("SELECT * FROM waiting_items WHERE archived=0 AND status='waiting' AND check_date<=?", (today,))
        with self.conn:
            for row in rows:
                self.conn.execute("UPDATE waiting_items SET status='check',updated_at=? WHERE id=?", (self.local_timestamp(),row["id"]))
                after = self.row("SELECT * FROM waiting_items WHERE id=?", (row["id"],))
                self._structure_event("waiting_items", row["id"], "check_due", row, after)
        return len(rows)

    def archive_waiting(self, item_id, archived=True):
        return self._structure_write("waiting_items", {"archived": int(bool(archived))}, item_id, event="archived" if archived else "restored")

    def task_is_waiting(self, task_id):
        items = self.rows("SELECT * FROM waiting_items WHERE task_id=? AND archived=0 AND status<>'resolved'", (task_id,))
        return bool(items) and all(r["status"] in ("waiting", "check") and not r["has_action"] for r in items)

    def start_recovery(self, activity="", *, context=None):
        with self.conn:
            opened = self.row("SELECT * FROM recovery_sessions WHERE ended_at IS NULL")
            if opened:
                session_id = int(opened["id"])
            else:
                now = self.local_timestamp()
                cur = self.conn.execute("""INSERT INTO recovery_sessions(started_at,activity,created_at,updated_at)
                    VALUES (?,?,?,?)""", (now,activity.strip(),now,now))
                session_id = int(cur.lastrowid)
                after = self.row("SELECT * FROM recovery_sessions WHERE id=?", (session_id,))
                self._structure_event("recovery_sessions", session_id, "created", None, after)
            if context is not None:
                value = json.dumps(dict(context=context,kind="recovery",session_id=session_id),ensure_ascii=False)
                self.conn.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES ('quiet_context',?)", (value,))
        return session_id

    def update_recovery(self, session_id, activity):
        return self._structure_write("recovery_sessions", {"activity": activity.strip()}, session_id)

    def end_recovery(self, session_id):
        row = self.row("SELECT * FROM recovery_sessions WHERE id=?", (session_id,))
        if not row:
            raise ValueError("恢复记录不存在")
        if row["ended_at"] is not None:
            return session_id
        return self._structure_write("recovery_sessions", {"ended_at": self.local_timestamp()}, session_id, event="ended")

    def skip_recovery_record(self, session_id, *, quiet_context=None):
        # Skipping removes the activity facts, including their audit copies.
        with self.conn:
            self.conn.execute("DELETE FROM structure_events WHERE entity_type='recovery_sessions' AND entity_id=?", (str(session_id),))
            self.conn.execute("DELETE FROM recovery_sessions WHERE id=?", (session_id,))
            if quiet_context is not None:
                self.conn.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES ('quiet_context',?)", (quiet_context,))

    def save_worry(self, content, actionability="uncertain", task_id=None, waiting_item_id=None,
                   thought_id=None, archived=False, worry_id=None):
        if not content.strip() or actionability not in ("yes", "no", "uncertain"):
            raise ValueError("请留下原文，并选择是否有行动")
        self._require_task(task_id)
        for table, ref in (("waiting_items",waiting_item_id),("thoughts",thought_id)):
            if ref is not None and not self.row(f"SELECT 1 FROM {table} WHERE id=?", (ref,)):
                raise ValueError("关联记录不存在")
        return self._structure_write("worries", dict(content=content.strip(),actionability=actionability,
            task_id=task_id,waiting_item_id=waiting_item_id,thought_id=thought_id,archived=int(bool(archived))), worry_id)

    def delete_worry(self, worry_id):
        with self.conn:
            self.conn.execute("DELETE FROM structure_events WHERE entity_type='worries' AND entity_id=?", (str(worry_id),))
            self.conn.execute("DELETE FROM worries WHERE id=?", (worry_id,))

    def save_daily_assessment(self, day, **values):
        self._require_day(day)
        allowed = {"external_anchor", "autonomous_work", "complete_experiment", "idle_unease", "pressure", "recovery"}
        if not set(values) <= allowed:
            raise ValueError("不支持的自评字段")
        for key,value in values.items():
            if value is not None and (value not in ("轻","适中","高") if key=="pressure" else type(value) not in (int,bool) or value not in (0,1)):
                raise ValueError("自评值无效")
        with self.conn:
            before = self.row("SELECT * FROM daily_assessments WHERE assessment_date=?", (day,))
            if before and all(before[k] == v for k,v in values.items()):
                return
            now = self.local_timestamp()
            self.conn.execute("INSERT OR IGNORE INTO daily_assessments(assessment_date,created_at,updated_at) VALUES (?,?,?)", (day,now,now))
            if values:
                self.conn.execute("UPDATE daily_assessments SET " + ",".join(k+"=?" for k in values) + ",updated_at=? WHERE assessment_date=?", (*values.values(),now,day))
            after = self.row("SELECT * FROM daily_assessments WHERE assessment_date=?", (day,))
            self._structure_event("daily_assessments", day, "updated", before, after)

    def _entity_history(self, table):
        events = self.rows("SELECT * FROM structure_events WHERE entity_type=? ORDER BY id", (table,))
        grouped = {}
        for event in events:
            grouped.setdefault(event["entity_id"], []).append(event)
        return grouped

    def _facts_as_of(self, table, day):
        facts = []
        for events in self._entity_history(table).values():
            applicable = [e for e in events if e["event_date"] <= day]
            # Initial imported/scheduled data can refer to a past date. Only the
            # first recorded version is used then; subsequent revisions stay dated.
            event = applicable[-1] if applicable else events[0]
            if event["after_json"]:
                facts.append(json.loads(event["after_json"]))
        return facts

    def structure_day(self, day):
        self._require_day(day)
        anchors = []
        for row in self._facts_as_of("external_anchors", day):
            start = row["anchor_date"]
            end = datetime.fromisoformat(row["end_at"]).astimezone().date().isoformat() if row["end_at"] else start
            if start <= day <= end:
                anchors.append(row)
        activities = [r for r in self._facts_as_of("autonomous_activities", day) if r["activity_date"]==day]
        recoveries = []
        for r in self.rows("SELECT * FROM recovery_sessions ORDER BY id"):
            first = datetime.fromisoformat(r["started_at"]).astimezone().date().isoformat()
            last = datetime.fromisoformat(r["ended_at"]).astimezone().date().isoformat() if r["ended_at"] else self.today_iso()
            if first <= day <= last:
                recoveries.append(dict(r))
        iterations = [dict(r) for r in self.rows("SELECT * FROM experiment_iterations WHERE state='recorded' AND event_date=? ORDER BY id", (day,))]
        waiting = [dict(r) for r in self.rows("SELECT * FROM structure_events WHERE entity_type='waiting_items' AND event_date=? ORDER BY id", (day,))]
        assessment = self.row("SELECT * FROM daily_assessments WHERE assessment_date=?", (day,))
        return {"day":day,"anchors":anchors,"activities":activities,"iterations":iterations,
                "waiting_events":waiting,"recoveries":recoveries,"assessment":dict(assessment) if assessment else None}

    def structure_review(self, end_day=None):
        end = date.fromisoformat(self._require_day(end_day or self.today_iso()))
        return [self.structure_day((end-timedelta(days=n)).isoformat()) for n in range(13,-1,-1)]

    def structure_dates(self):
        days = {r["event_date"] for r in self.rows("SELECT DISTINCT event_date FROM structure_events")}
        days.update(r["anchor_date"] for r in self.rows("SELECT anchor_date FROM external_anchors"))
        for r in self.rows("SELECT start_at,end_at FROM external_anchors WHERE end_at<>''"):
            start = datetime.fromisoformat(r["start_at"]).date()
            end = datetime.fromisoformat(r["end_at"]).date()
            while start <= end:
                days.add(start.isoformat()); start += timedelta(days=1)
        days.update(r["activity_date"] for r in self.rows("SELECT activity_date FROM autonomous_activities"))
        days.update(r["assessment_date"] for r in self.rows("SELECT assessment_date FROM daily_assessments"))
        # Include original dates retained in edits, not just current scheduling.
        for r in self.rows("SELECT before_json,after_json FROM structure_events WHERE entity_type IN ('external_anchors','autonomous_activities')"):
            for snapshot in (r["before_json"],r["after_json"]):
                if snapshot:
                    data = json.loads(snapshot)
                    days.add(data.get("anchor_date", data.get("activity_date")))
        for r in self.rows("SELECT started_at,ended_at FROM recovery_sessions"):
            start = datetime.fromisoformat(r["started_at"]).astimezone().date()
            end = datetime.fromisoformat(r["ended_at"]).astimezone().date() if r["ended_at"] else date.fromisoformat(self.today_iso())
            while start <= end:
                days.add(start.isoformat()); start += timedelta(days=1)
        return sorted(days, reverse=True)
