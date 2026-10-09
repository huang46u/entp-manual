"""Small Flet panels integrated into the existing desktop navigation."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path

import flet as ft
from life_structure import ASSESS_LABELS, WAIT_LABELS


BLUE = "#316BEE"
INK = "#171A21"
MUTED = "#737986"


def text(value, *, small=False):
    return ft.Text(str(value), size=13 if small else 15, color=MUTED if small else INK, selectable=True)


def fit_actions(controls):
    result = []
    for control in controls:
        pending = [control]
        while pending:
            node = pending.pop()
            if isinstance(node,ft.FilledButton):
                node.style = ft.ButtonStyle(bgcolor=BLUE,color="#FFFFFF",shape=ft.RoundedRectangleBorder(radius=10))
            pending.extend(getattr(node,"controls",[]) or [])
            content = getattr(node,"content",None)
            if isinstance(content,ft.Control):
                pending.append(content)
        if isinstance(control,ft.FilledButton):
            control = ft.Row([control],wrap=True)
        result.append(control)
    return result


def editable_controls(root):
    pending = [root]
    while pending:
        node = pending.pop()
        if isinstance(node,(ft.TextField,ft.Dropdown)):
            yield node
        children = list(getattr(node,"controls",[]) or [])
        content = getattr(node,"content",None)
        if isinstance(content,ft.Control):
            children.append(content)
        pending.extend(reversed(children))


def card(controls):
    return ft.Card(content=ft.Container(ft.Column(fit_actions(controls), spacing=12,
                   horizontal_alignment=ft.CrossAxisAlignment.STRETCH), padding=18),
                   elevation=0, bgcolor="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=13),
                   variant=ft.CardVariant.OUTLINED)


def field(label, value="", *, multiline=False):
    return ft.TextField(label=label, value=str(value or ""), multiline=multiline,
                        min_lines=2 if multiline else 1, max_lines=6 if multiline else 1,
                        border_radius=12, width=float("inf"))


def select(label, options, value=None):
    return ft.Dropdown(label=label, value=value, options=[ft.DropdownOption(key=str(k),text=v) for k,v in options],
                       border_radius=12, width=float("inf"))


class StructureUI:
    NAV_WAITING = 5

    def _structure_init(self):
        self._quiet_mode = None
        self._structure_route = None
        self._structure_fields = {}
        self._structure_flush = None
        self._waiting_expanded = set()
        self.db.refresh_waiting_checks()

    def _structure_actions(self):
        mode = self.db.get_setting("activity_mode") or "advance"
        return ft.Row([
            text("当前方式：等待" if mode=="wait" else "当前方式：推进",small=True),
            ft.TextButton("进入恢复状态", on_click=lambda _: self.enter_recovery()),
            ft.TextButton("担忧收纳", on_click=lambda _: self.open_worries()),
            ft.TextButton("安静一下", on_click=lambda _: self.enter_quiet_worry()),
            ft.TextButton("切换为等待" if mode!="wait" else "重新进入推进",
                          on_click=lambda _: self.set_activity_mode("wait" if mode!="wait" else "advance")),
        ], wrap=True, spacing=6)

    def set_activity_mode(self, mode):
        if mode not in ("advance","wait"):
            raise ValueError("活动方式无效")
        self.db.set_setting("activity_mode", mode)
        self.show_view(self.active_index)

    def _task_selector(self, selected=None):
        options = [("", "不关联任务")]
        options.extend((str(r["id"]), f"{r['title']} · {r['mainline_name']}") for r in self.db.list_tasks())
        return select("关联现有任务（可选）", options, str(selected) if selected is not None else "")

    @staticmethod
    def _reference(control):
        return int(control.value) if control.value else None

    def _structure_surface(self, title, controls, *, route=None, fields=None, flush=None):
        self._structure_route = route
        self._structure_fields = fields or {}
        self._structure_flush = flush
        self.content_switcher.content = self._structure_shell(ft.Column([
            ft.Row([ft.TextButton("返回", on_click=lambda _: self._structure_back()),
                    ft.Text(title,size=23,weight=ft.FontWeight.W_700)],wrap=True),
            self._structure_actions(), *fit_actions(controls),
        ], spacing=14,scroll=ft.ScrollMode.AUTO,expand=True,horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        self.page.update()

    def _structure_shell(self,content):
        # Alignment loosens the child's width constraints: narrow windows clamp
        # naturally, while wide reading/editing panels stop at 1160 pixels.
        return self._page_shell(ft.Container(ft.Container(content,width=1160),
            alignment=ft.Alignment.TOP_CENTER,expand=True))

    def _structure_back(self):
        if self._structure_flush:
            self._structure_flush()
        route = getattr(self, "_structure_route", None)
        if route and route[0] in ("evidence", "summary"):
            if route[0] == "evidence":
                iteration = self.db.row("SELECT experiment_id FROM experiment_iterations WHERE id=?", (route[1],))
                experiment_id = iteration[0]
            else:
                experiment_id = route[1]
            self.open_experiment(experiment_id=experiment_id)
            return
        self._structure_route = None
        self._structure_fields = {}
        self._structure_flush = None
        self.show_view(self.active_index)

    def _structure_saved(self):
        self._sync_markdown()
        self._structure_back()

    def _today_structure(self, day):
        facts = self.db.structure_day(day)
        controls = [text("今日结构" if day==self.db.today_iso() else "当日结构")]
        for anchor in sorted(facts["anchors"], key=lambda r:r["start_at"] or r["anchor_date"]):
            stamp = datetime.fromisoformat(anchor["start_at"]).strftime("%H:%M") if anchor["start_at"] else "时间未指定"
            label = "截止" if anchor["kind"]=="deadline" else "事件"
            state = {"active":"", "ended":" · 已结束", "cancelled":" · 已取消"}[anchor["status"]]
            controls.append(ft.TextButton(f"{stamp} · {label} · {anchor['title']}{state}",
                on_click=lambda _,aid=anchor["id"]: self.open_anchor(aid)))
        if not facts["anchors"]:
            controls.append(text("今天没有必须在固定时间处理的外部安排。" if day==self.db.today_iso() else "这一天没有外部安排记录。",small=True))
        for activity in facts["activities"]:
            controls.append(ft.TextButton(f"自主选择 · {activity['scheduled_time']} {activity['title']}",
                on_click=lambda _,aid=activity["id"]: self.open_activity(aid)))
        for recovery in facts["recoveries"]:
            controls.append(text(f"恢复 · {recovery['activity'] or '未选择活动'} · {'已结束' if recovery['ended_at'] else '进行中'}",small=True))
        if day==self.db.today_iso():
            checks = self.db.rows("SELECT * FROM waiting_items WHERE status='check' AND archived=0")
            controls.append(ft.TextButton(f"等待事项 · {len(checks)} 项需要检查" if checks else "等待事项 · 当前没有需要检查的新信息",
                                          on_click=lambda _:self.show_view(self.NAV_WAITING)))
            controls.append(ft.Row([
                ft.TextButton("添加外部锚点", on_click=lambda _:self.open_anchor()),
                ft.TextButton("选择自主活动", on_click=lambda _:self.open_activity()),
            ],wrap=True))
        controls.extend([ft.TextButton("自愿记录状态",on_click=lambda _:self.open_assessment(day)), self._structure_actions()])
        return card(controls)

    def open_anchor(self, anchor_id=None, *, default_task_id=None):
        row = self.db.row("SELECT * FROM external_anchors WHERE id=?",(anchor_id,)) if anchor_id else None
        def value(key, default=""):
            return row[key] if row else default
        title = field("事件名称",value("title"))
        source = field("真实外部来源",value("source"))
        kind = select("约束类型",[("event","事件发生"),("deadline","真实截止")],value("kind","event"))
        day = field("日期 YYYY-MM-DD",value("anchor_date",self.db.today_iso()))
        start = field("开始 / 截止 HH:MM（可选）",datetime.fromisoformat(row["start_at"]).strftime("%H:%M") if row and row["start_at"] else "")
        end_day = field("结束日期（可选）",datetime.fromisoformat(row["end_at"]).date().isoformat() if row and row["end_at"] else "")
        end = field("结束 HH:MM（事件可选）",datetime.fromisoformat(row["end_at"]).strftime("%H:%M") if row and row["end_at"] else "")
        consequence = field("未处理的实际后果（可选）",value("consequence"),multiline=True)
        task = self._task_selector(value("task_id",default_task_id))
        status = select("状态",[("active","有效"),("ended","已结束"),("cancelled","已取消")],value("status","active"))
        fields = dict(title=title,source=source,kind=kind,day=day,start=start,end_day=end_day,end=end,consequence=consequence,task=task,status=status)
        def save(_):
            def stamp(day_value,time_value):
                if not time_value:
                    return ""
                try:
                    datetime.strptime(time_value.strip(),"%H:%M")
                    return datetime.fromisoformat(f"{day_value}T{time_value.strip()}:00").astimezone().isoformat(timespec="seconds")
                except ValueError as error:
                    raise ValueError("日期或时间无效，时间请填写 HH:MM") from error
            aid = self.db.save_anchor(title=title.value,source=source.value,kind=kind.value,anchor_date=day.value,
                start_at=stamp(day.value,start.value),end_at=stamp(end_day.value or day.value,end.value),
                consequence=consequence.value,task_id=self._reference(task),anchor_id=anchor_id,status=status.value)
            ended = status.value=="ended" and (not row or row["status"]!="ended")
            self._structure_saved()
            if ended:
                self._offer_recovery(aid)
        history = self.db.rows("SELECT * FROM structure_events WHERE entity_type='external_anchors' AND entity_id=? ORDER BY id",(str(anchor_id),)) if row else []
        details = ft.ExpansionTile(title=text("更多信息"),controls=[end_day,end,consequence,task,status,
            *[text(f"{r['occurred_at']} · {r['event_type']}",small=True) for r in history]])
        self._structure_surface("外部锚点",[text("自主安排请放在自主活动中。外部锚点不会创建或完成任务。",small=True),
            title,source,kind,day,start,details,ft.FilledButton("保存外部锚点",on_click=save)],route=("anchor",anchor_id),fields=fields)

    def _offer_recovery(self, anchor_id):
        # A single suggestion on the user's transition, never on page refresh.
        self.page.show_dialog(ft.SnackBar(content=ft.Row([text("事件已结束，可以给自己一点恢复空间。"),
            ft.TextButton("进入恢复状态",on_click=lambda _:self.enter_recovery())],wrap=True),duration=7000))

    def open_activity(self, activity_id=None):
        row = self.db.row("SELECT * FROM autonomous_activities WHERE id=?",(activity_id,)) if activity_id else None
        title = field("自主选择的活动",row["title"] if row else "")
        day = field("日期 YYYY-MM-DD",row["activity_date"] if row else self.db.today_iso())
        clock = field("安排时间 HH:MM（可选）",row["scheduled_time"] if row else "")
        task = self._task_selector(row["task_id"] if row else None)
        def save(_):
            self.db.save_activity(title.value,day.value,clock.value,self._reference(task),activity_id)
            self._structure_saved()
        self._structure_surface("自主活动",[title,day,clock,task,ft.FilledButton("保存自主活动",on_click=save)],
                                route=("activity",activity_id),fields=dict(title=title,day=day,clock=clock,task=task))

    def open_experiment(self, task_id=None, experiment_id=None):
        experiment = self.db.row("SELECT * FROM experiments WHERE id=?",(experiment_id,)) if experiment_id else self.db.experiment_for_task(task_id)
        if not experiment:
            question = field("当前要验证什么？",multiline=True)
            def create(_):
                eid = self.db.create_experiment(task_id,question.value)
                self.db.start_iteration(eid)
                self.open_experiment(experiment_id=eid)
            self._structure_surface("进入实验模式",[question,ft.FilledButton("开始记录实验",on_click=create)],
                                    route=("new_experiment",task_id),fields={"question":question})
            return
        eid = int(experiment["id"])
        ended = experiment["status"]=="ended"
        if not ended and not self.db.experiment_iterations(eid):
            self.db.start_iteration(eid)
        iterations = self.db.experiment_iterations(eid)
        controls = [text(experiment["question"]),text("运行在你的科研或编程环境中；这里保存真实观察，不要求把工作拆成微小步骤。",small=True)]
        task = self.db.get_task(experiment["task_id"]) if experiment["task_id"] else None
        controls.append(text(f"关联任务：{task['title'] if task else '原任务已删除，历史仍保留'}",small=True))
        draft = next((r for r in iterations if r["state"]=="draft"),None)
        fields = {}
        flush = None
        if draft and not ended:
            fields = {key:field(label,draft[key],multiline=True) for key,label in (
                ("hypothesis","假设 / 预期现象"),("method","准备运行什么实验？"),("observation","看到了什么结果？"),
                ("next_hypothesis","下一次实验 / 下一假设"),("parameters","实验参数（可选）"),("input_data","输入数据（可选）"))}
            def flush():
                self.db.save_iteration_draft(draft["id"],**{k:f.value or "" for k,f in fields.items()})
            # Persist typed drafts, not only blur, so window close cannot lose them.
            for control in fields.values():
                control.on_change = lambda _:flush()
            def record(_):
                flush()
                self.db.record_iteration(draft["id"])
                self._sync_markdown()
                self.open_experiment(experiment_id=eid)
            controls.append(card([text(f"第 {draft['round_no']} 轮 · 草稿"),fields["method"],fields["observation"],
                ft.ExpansionTile(title=text("假设、参数与下一次实验"),controls=[fields[k] for k in ("hypothesis","next_hypothesis","parameters","input_data")]),
                ft.FilledButton("保存实际观察",on_click=record)]))
        recorded = [r for r in iterations if r["state"]=="recorded"]
        for iteration in iterations:
            if iteration["state"]!="recorded":
                continue
            evidence = self.db.rows("SELECT * FROM experiment_evidence WHERE iteration_id=? ORDER BY id",(iteration["id"],))
            controls.append(ft.ExpansionTile(title=text(f"第 {iteration['round_no']} 轮 · {iteration['event_date']}"),
                expanded=bool(recorded and iteration["id"]==recorded[-1]["id"]),
                expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[text(f"方法：{iteration['method']}"),text(f"观察：{iteration['observation']}"),
                          *([text(f"假设：{iteration['hypothesis']}",small=True)] if iteration["hypothesis"] else []),
                          *([text(f"下一假设：{iteration['next_hypothesis']}",small=True)] if iteration["next_hypothesis"] else []),
                          *([text(f"参数：{iteration['parameters']}\n输入：{iteration['input_data']}",small=True)] if iteration["parameters"] or iteration["input_data"] else []),
                          *[text(f"证据 · {e['value']}",small=True) for e in evidence],
                          ft.TextButton("追加结果证据",on_click=lambda _,iid=iteration["id"]:self.open_evidence(iid))]))
        def pause(_):
            if flush:
                flush()
            self.db.set_experiment_status(eid,"paused")
            self.active_index = self.NAV_CURRENT
            self._structure_saved()
        def next_round(_):
            if flush:
                flush()
            self.db.set_experiment_status(eid,"active")
            self.db.start_iteration(eid)
            self.open_experiment(experiment_id=eid)
        if not ended:
            controls.append(ft.Row([ft.TextButton("继续下一次实验",on_click=next_round),
                ft.TextButton("暂停并返回当前主线",on_click=pause),
                ft.TextButton("结束实验并生成总结",on_click=lambda _:self.open_experiment_summary(eid))],wrap=True))
        else:
            controls.append(text(experiment["summary"] or "尚未填写总结"))
        self._structure_surface("实验闭环",controls,route=("experiment",eid),fields=fields,flush=flush)

    def _expand_waiting_focus(self,task_id):
        if not hasattr(self,"_waiting_expanded"):
            self._waiting_expanded = set()
        self._waiting_expanded.add(task_id)
        self.refresh_current_sections()

    def open_task_experiments(self,task_id):
        controls = [ft.FilledButton("新建实验",on_click=lambda _:self._new_task_experiment(task_id))]
        for row in self.db.rows("SELECT * FROM experiments WHERE task_id=? ORDER BY id DESC",(task_id,)):
            controls.append(ft.TextButton(f"{row['question']} · { {'active':'进行中','paused':'暂停','ended':'已结束'}[row['status']]}",
                on_click=lambda _,eid=row["id"]:self.open_experiment(experiment_id=eid)))
        self._structure_surface("任务实验历史",controls,route=("task_experiments",task_id))

    def _new_task_experiment(self,task_id):
        question = field("当前要验证什么？",multiline=True)
        def create(_):
            eid = self.db.create_experiment(task_id,question.value)
            self.open_experiment(experiment_id=eid)
        self._structure_surface("新建实验",[question,ft.FilledButton("开始记录实验",on_click=create)],
            route=("new_experiment",task_id),fields={"question":question})

    def open_experiment_summary(self, experiment_id):
        if self._structure_flush:
            self._structure_flush()
        summary = field("实验总结（可修改）",self.db.experiment_summary(experiment_id),multiline=True)
        def finish(_):
            self.db.set_experiment_status(experiment_id,"ended",summary.value)
            self._sync_markdown()
            self.open_experiment(experiment_id=experiment_id)
        self._structure_surface("结束实验",[summary,text("实验结束不会完成关联任务。",small=True),
            ft.FilledButton("保存总结并结束",on_click=finish)],route=("summary",experiment_id),fields={"summary":summary})

    def open_evidence(self, iteration_id):
        iteration = self.db.row("SELECT * FROM experiment_iterations WHERE id=?",(iteration_id,))
        value = field("数字、日志、补充观察或文件路径",multiline=True)
        kind = select("证据类型",[("text","数字 / 文本"),("path","外部文件路径")],"text")
        def save(_):
            self.db.add_experiment_evidence(iteration_id,value.value,kind.value)
            self._sync_markdown()
            self.open_experiment(experiment_id=iteration["experiment_id"])
        async def import_file(_):
            files = await self.file_picker.pick_files(dialog_title="选择要纳入备份的实验文件",allow_multiple=False,
                                                      initial_directory=str(self.db.path.parent))
            if not files or not files[0].path:
                return
            self.import_experiment_file(iteration_id,Path(files[0].path))
            self._sync_markdown()
            self.open_experiment(experiment_id=iteration["experiment_id"])
        self._structure_surface("追加证据",[value,kind,text("外部路径只保存引用；导入文件会复制到工作区并纳入备份。",small=True),
            ft.Row([ft.FilledButton("保存证据",on_click=save),ft.TextButton("导入文件到备份",on_click=import_file)],wrap=True)],
            route=("evidence",iteration_id),fields=dict(value=value,kind=kind))

    def import_experiment_file(self, iteration_id, source):
        source = Path(source)
        if not source.is_file():
            raise ValueError("找不到实验文件")
        directory = self.markdown.root / "_assets" / "experiments" / str(iteration_id)
        directory.mkdir(parents=True,exist_ok=True)
        target = directory / (uuid.uuid4().hex + source.suffix)
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            shutil.copyfile(source,temporary)
            temporary.replace(target)
            self.db.add_experiment_evidence(iteration_id,target.relative_to(self.markdown.root).as_posix(),"attachment")
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def _waiting_view(self):
        self.db.refresh_waiting_checks()
        archived = getattr(self,"_show_waiting_archive",False)
        rows = self.db.rows("SELECT * FROM waiting_items WHERE archived=? ORDER BY updated_at DESC,id DESC",(int(archived),))
        controls = [ft.Text("等待事项",size=27,weight=ft.FontWeight.W_700),self._structure_actions(),
            ft.Row([ft.FilledButton("创建等待事项",on_click=lambda _:self.open_waiting()),
                ft.TextButton("返回当前事项" if archived else "查看归档",on_click=lambda _:self._toggle_waiting_archive())],wrap=True)]
        for state in ("check","waiting","actionable","resolved"):
            items = [r for r in rows if r["status"]==state]
            if not items:
                continue
            cards = []
            for r in items:
                cards.append(card([text(r["title"]),text(f"等待：{r['waiting_for']} · 检查日期：{r['check_date'] or '未安排'}",small=True),
                    text(r["action"] if r["has_action"] else "当前没有新的可处理信息。",small=True),
                    ft.Row([ft.TextButton("查看 / 编辑",on_click=lambda _,rid=r["id"]:self.open_waiting(rid)),
                        ft.TextButton("恢复" if archived else "归档",on_click=lambda _,rid=r["id"]:self._archive_waiting_ui(rid,not archived))],wrap=True)]))
            controls.append(ft.ExpansionTile(title=text(f"{WAIT_LABELS[state]} · {len(items)} 项"),controls=cards,
                                             expanded=state!="resolved"))
        if not rows:
            controls.append(text("这里还没有等待事项。无需为了填满页面而创建。",small=True))
        return self._structure_shell(ft.Column(controls,spacing=14,scroll=ft.ScrollMode.AUTO,expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH))

    def _toggle_waiting_archive(self):
        self._show_waiting_archive = not getattr(self,"_show_waiting_archive",False)
        self.show_view(self.NAV_WAITING)

    def _archive_waiting_ui(self, item_id, archived):
        self.db.archive_waiting(item_id,archived)
        self._sync_markdown()
        self.show_view(self.NAV_WAITING)

    def open_waiting(self, item_id=None):
        row = self.db.row("SELECT * FROM waiting_items WHERE id=?",(item_id,)) if item_id else None
        def value(key,default=""):
            return row[key] if row else default
        title = field("事项标题",value("title"))
        who = field("正在等待谁采取行动",value("waiting_for"))
        facts = field("当前已确认事实",value("facts"),multiline=True)
        has_action = select("当前是否有有效行动",[("0","没有"),("1","有")],str(value("has_action",0)))
        action = field("有效行动（有行动时填写）",value("action"),multiline=True)
        check = field("下一次合理检查日期 YYYY-MM-DD（可选）",value("check_date"))
        state = select("状态",list(WAIT_LABELS.items()),value("status","waiting"))
        task = self._task_selector(value("task_id",None))
        def save(_):
            self.db.save_waiting_item(title=title.value,waiting_for=who.value,facts=facts.value,
                has_action=has_action.value=="1",action=action.value,check_date=check.value or None,
                status=state.value,task_id=self._reference(task),item_id=item_id,archived=bool(value("archived",False)))
            self._structure_saved()
        history = self.db.rows("SELECT * FROM structure_events WHERE entity_type='waiting_items' AND entity_id=? ORDER BY id",(str(item_id),)) if row else []
        controls = [title,who,facts,state,has_action,action,check,
            ft.ExpansionTile(title=text("关联任务与更新记录"),controls=[task,*[text(
                f"{h['occurred_at']} · {WAIT_LABELS.get(json.loads(h['after_json'])['status'],'')} · {json.loads(h['after_json'])['facts']}",small=True) for h in history]]),
            ft.FilledButton("保存等待事项",on_click=save)]
        self._structure_surface("等待事项",controls,route=("waiting",item_id),
            fields=dict(title=title,who=who,facts=facts,state=state,has_action=has_action,action=action,check=check,task=task))

    def open_worries(self):
        rows = self.db.rows("SELECT * FROM worries ORDER BY archived,id DESC")
        controls = [ft.FilledButton("留下一个担忧",on_click=lambda _:self.open_worry()),
                    text("这里保存现实问题；灵感继续留在候审区。",small=True)]
        for row in rows:
            controls.append(card([text(row["content"]),text("已归档" if row["archived"] else {"yes":"有可执行行动","no":"目前没有行动","uncertain":"暂时不确定"}[row["actionability"]],small=True),
                ft.TextButton("重新查看 / 编辑",on_click=lambda _,wid=row["id"]:self.open_worry(wid))]))
        self._structure_surface("担忧收纳",controls,route=("worries",None))

    def open_worry(self, worry_id=None):
        row = self.db.row("SELECT * FROM worries WHERE id=?",(worry_id,)) if worry_id else None
        content = field("现在有什么事情一直占着你的注意力？",row["content"] if row else "",multiline=True)
        decision = select("这件事现在有可执行的行动吗？",[("yes","有"),("no","没有"),("uncertain","暂时不确定")],row["actionability"] if row else "uncertain")
        task = self._task_selector(row["task_id"] if row else None)
        waiting = select("关联等待事项（可选）",[("","不关联")]+[(str(r["id"]),r["title"]) for r in self.db.rows("SELECT * FROM waiting_items ORDER BY id DESC")],str(row["waiting_item_id"]) if row and row["waiting_item_id"] else "")
        thought = select("手动关联灵感（可选）",[("","不关联")]+[(str(r["id"]),r["title"]) for r in self.db.list_thoughts()],str(row["thought_id"]) if row and row["thought_id"] else "")
        new_action = field("创建行动的标题（有行动时可选）")
        def save(archived=False):
            if not content.value.strip():
                raise ValueError("请先留下担忧原文")
            task_id = self._reference(task)
            if decision.value=="yes" and new_action.value.strip():
                # One explicit task creation, never automatic classification.
                task_id = self.db.create_task(self.current_mid,new_action.value.strip())
                task.value = str(task_id)
                new_action.value = ""
            self.db.save_worry(content.value,decision.value,task_id,self._reference(waiting),self._reference(thought),archived,worry_id)
            self._sync_markdown()
            self.open_worries()
        controls = [content,decision,ft.ExpansionTile(title=text("关联已有记录或创建行动"),controls=[task,waiting,thought,new_action]),
            ft.Row([ft.FilledButton("保存",on_click=lambda _:save(bool(row["archived"]) if row else False)),
                ft.TextButton("恢复" if row and row["archived"] else "归档",on_click=lambda _:save(not bool(row["archived"]) if row else True)),
                *([ft.TextButton("删除",on_click=lambda _:self._delete_worry_ui(worry_id))] if row else [])],wrap=True)]
        self._structure_surface("担忧收纳",controls,route=("worry",worry_id),fields=dict(content=content,decision=decision,task=task,waiting=waiting,thought=thought,new_action=new_action))

    def _delete_worry_ui(self,worry_id):
        self.db.delete_worry(worry_id)
        self._sync_markdown()
        self.open_worries()

    def open_assessment(self,day):
        row = self.db.row("SELECT * FROM daily_assessments WHERE assessment_date=?",(day,))
        fields = {}
        for key,label in ASSESS_LABELS.items():
            options = [("","未记录")]+([(v,v) for v in ("轻","适中","高")] if key=="pressure" else [("1","是"),("0","否")])
            value = str(row[key]) if row and row[key] is not None else ""
            fields[key] = select(label,options,value)
        def save(_):
            values = {k:(f.value if k=="pressure" else int(f.value)) if f.value else None for k,f in fields.items()}
            self.db.save_daily_assessment(day,**values)
            self._structure_saved()
        self._structure_surface(f"{day} · 自愿状态记录",[text("可以只填一项，也可以不填。未记录不会被解释成零压力或没有工作。",small=True),
            *fields.values(),ft.FilledButton("保存状态记录",on_click=save)],route=("assessment",day),fields=fields)

    def _structure_review_panel(self):
        days = self.db.structure_review()
        controls = [text("最近 14 天 · 结构观察"),text("只展示已记录事实；空白日期保持为空。",small=True)]
        count = sum(bool(d["assessment"] and any(d["assessment"][k] is not None for k in ASSESS_LABELS)) for d in days)
        controls.append(text(f"主动填写状态：{count} / 14 天",small=True))
        for d in days:
            parts = []
            for key,label in (("anchors","外部锚点"),("activities","自主选择"),("iterations","实验观察"),("waiting_events","等待变化"),("recoveries","恢复")):
                if d[key]:
                    parts.append(f"{label} {len(d[key])}")
            if d["assessment"] and d["assessment"]["pressure"] is not None:
                parts.append("自评压力 "+d["assessment"]["pressure"])
            controls.append(ft.TextButton(f"{d['day']} · {' · '.join(parts) or '未记录结构信息'}",
                on_click=lambda _,day=d["day"]:self.open_structure_day(day)))
        controls.append(ft.TextButton("所选日期的结构与状态",on_click=lambda _:self.open_structure_day(self.calendar_selected_day.isoformat())))
        return card(controls)

    def open_structure_day(self,day):
        d = self.db.structure_day(day)
        controls = []
        for r in self.db.list_daily_entries(day):
            controls.append(text(f"任务 · {r['task_title_snapshot']} · {r['state']}"))
        for r in d["anchors"]:
            controls.append(text(f"外部锚点 · {r['title']} · 来源：{r['source']} · {r['status']}"))
        for r in d["activities"]:
            controls.append(text(f"自主活动 · {r['title']}"))
        for r in d["iterations"]:
            controls.append(ft.TextButton(f"实验第 {r['round_no']} 轮 · {r['observation']}",
                on_click=lambda _,eid=r["experiment_id"]:self.open_experiment(experiment_id=eid)))
        for r in d["waiting_events"]:
            after = json.loads(r["after_json"])
            controls.append(text(f"等待变化 · {after['title']} · {WAIT_LABELS[after['status']]} · {after['facts']}"))
        for r in d["recoveries"]:
            controls.append(text(f"恢复 · {r['activity'] or '未选择活动'} · {r['started_at']} → {r['ended_at'] or '尚未结束'}"))
        for key,label in ASSESS_LABELS.items():
            value = d["assessment"][key] if d["assessment"] else None
            controls.append(text(f"{label}：{'未记录' if value is None else value if key=='pressure' else '是' if value else '否'}",small=True))
        controls.append(ft.Row([ft.TextButton("查看当日账本",on_click=lambda _:self.open_daily_ledger(date.fromisoformat(day))),
            ft.TextButton("编辑自愿记录",on_click=lambda _:self.open_assessment(day))],wrap=True))
        self._structure_surface(f"{day} · 结构与状态",controls,route=("structure_day",day))

    def _capture_work_context(self):
        snapshot = self._interaction_state_snapshot()
        snapshot = {k:v.isoformat() if isinstance(v,date) else v for k,v in snapshot.items()}
        snapshot["route"] = getattr(self,"_structure_route",None)
        snapshot["fields"] = {k:f.value for k,f in getattr(self,"_structure_fields",{}).items()}
        snapshot["quick_inputs"] = {name:getattr(self,name).value for name in ("quick_task_input","quick_today_input","inline_inspiration_input") if hasattr(self,name)}
        snapshot["expanded_task_ids"] = sorted(getattr(self,"expanded_task_ids",set()))
        snapshot["subtask_input_parent_id"] = getattr(self,"subtask_input_parent_id",None)
        snapshot["page_inputs"] = [dict(type=type(c).__name__,label=str(c.label or getattr(c,"hint_text","") or ""),value=c.value)
                                   for c in editable_controls(self.content_switcher.content)] if not snapshot["route"] else []
        return snapshot

    def _resume_work_context(self,context):
        dates = {"selected_day","calendar_month","calendar_selected_day"}
        for k,v in context.items():
            if k in dates:
                setattr(self,k,date.fromisoformat(v))
            elif k in ("inspiration_capture_open","today_priority_sort","today_collapsed","subtask_input_parent_id"):
                setattr(self,k,v)
        self.expanded_task_ids = set(context.get("expanded_task_ids",[]))
        self.current_mid = self.db.current_mainline_id()
        self.show_view(context.get("active_index",self.NAV_CURRENT))
        route = context.get("route")
        if route:
            kind,ref = route
            handlers = {"anchor":self.open_anchor,"activity":self.open_activity,"waiting":self.open_waiting,
                "worry":self.open_worry,"assessment":self.open_assessment,"structure_day":self.open_structure_day,
                "evidence":self.open_evidence,"summary":self.open_experiment_summary}
            if kind=="experiment":
                self.open_experiment(experiment_id=ref)
            elif kind=="new_experiment":
                self._new_task_experiment(ref)
            elif kind=="worries":
                self.open_worries()
            elif kind=="task_experiments":
                self.open_task_experiments(ref)
            elif kind in handlers:
                handlers[kind](ref)
            for key,value in context.get("fields",{}).items():
                if key in self._structure_fields:
                    self._structure_fields[key].value = value
        for key,value in context.get("quick_inputs",{}).items():
            if hasattr(self,key):
                getattr(self,key).value = value
        saved_inputs = list(context.get("page_inputs",[]))
        for control in editable_controls(self.content_switcher.content):
            key = (type(control).__name__,str(control.label or getattr(control,"hint_text","") or ""))
            saved = next((r for r in saved_inputs if (r["type"],r["label"])==key),None)
            if saved is not None:
                control.value = saved["value"]
                saved_inputs.remove(saved)

    def enter_recovery(self):
        if getattr(self,"_quiet_mode",None):
            return
        if getattr(self,"_structure_flush",None):
            self._structure_flush()
        context = self._capture_work_context()
        session_id = self.db.start_recovery(context=context)
        self._show_quiet("recovery",session_id)

    def enter_quiet_worry(self):
        if getattr(self,"_quiet_mode",None):
            return
        context = self._capture_work_context()
        self.db.set_setting("quiet_context",json.dumps(dict(context=context,kind="worry",session_id=None),ensure_ascii=False))
        self._show_quiet("worry",None)

    def _show_quiet(self,kind,session_id):
        self._quiet_mode = kind
        self._quiet_session_id = session_id
        self._normal_controls = list(self.page.controls)
        # Keep the original tree mounted but hidden: text values, scroll and
        # editor state survive without reconstructing the working page.
        for control in self._normal_controls:
            control.visible = False
        self._quiet_dialogs = []
        dialogs = getattr(getattr(self.page,"_dialogs",None),"controls",[])
        for dialog in dialogs:
            if getattr(dialog,"open",False):
                if isinstance(dialog,ft.AlertDialog):
                    self._quiet_dialogs.append(dialog)
                dialog.open = False
        if kind=="recovery":
            row = self.db.row("SELECT * FROM recovery_sessions WHERE id=?",(session_id,)) if session_id else None
            activity = field("你想选择什么恢复活动？（可选）",row["activity"] if row else "")
            self._quiet_activity = activity
            def choose(value):
                activity.value = value
                if self._quiet_session_id:
                    self.db.update_recovery(self._quiet_session_id,value)
                self.page.update()
            activity.on_change = lambda _:self.db.update_recovery(self._quiet_session_id,activity.value) if self._quiet_session_id else None
            controls = [ft.Text("暂时恢复",size=27),text("可以走一走、听音乐，或安静休息。时间由你决定。"),
                text("如果愿意，可以给自己 30–60 分钟；这里没有倒计时。",small=True),activity,
                ft.Row([ft.TextButton(label,on_click=lambda _,s=label:choose(s)) for label in
                    ("出去走一走","听音乐","安静休息","轻松阅读","无需产出的个人兴趣")],wrap=True),
                ft.TextButton("跳过恢复记录",on_click=lambda _:self._skip_recovery()),
                ft.FilledButton("退出恢复状态",on_click=lambda _:self.exit_quiet())]
        else:
            worry = field("现在有什么事情一直占着你的注意力？",multiline=True)
            decision = select("这件事现在有可执行的行动吗？",[("yes","有"),("no","没有"),("uncertain","暂时不确定")],"uncertain")
            self._quiet_worry = worry
            self._quiet_decision = decision
            def save(_):
                self.db.save_worry(worry.value,decision.value)
                worry.value = ""
                self.page.update()
            controls = [ft.Text("先安静一下",size=27),text("可以先喝点水、离开屏幕，或找信任的人说说眼前的事情。"),
                worry,decision,ft.FilledButton("把原文留下",on_click=save),ft.TextButton("返回原来的页面",on_click=lambda _:self.exit_quiet())]
        self._quiet_feedback = text("",small=True)
        self._quiet_control = ft.Container(ft.Column([*fit_actions(controls),self._quiet_feedback],spacing=18,scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=28,bgcolor="#F7F8FB",expand=True,width=float("inf"))
        self.page.controls.append(self._quiet_control)
        self.page.update()

    def _skip_recovery(self):
        if self._quiet_session_id:
            saved = json.loads(self.db.get_setting("quiet_context"))
            saved["session_id"] = None
            self.db.skip_recovery_record(self._quiet_session_id,quiet_context=json.dumps(saved,ensure_ascii=False))
            self._quiet_session_id = None
            self._sync_markdown(show_error=False)
        self._quiet_activity.on_change = None
        self.page.update()

    def exit_quiet(self):
        if self._quiet_mode=="recovery" and self._quiet_session_id:
            self.db.update_recovery(self._quiet_session_id,self._quiet_activity.value or "")
            self.db.end_recovery(self._quiet_session_id)
        self.page.controls.remove(self._quiet_control)
        for control in self._normal_controls:
            control.visible = True
        for dialog in self._quiet_dialogs:
            dialog.open = True
        self._quiet_mode = None
        self.db.set_setting("quiet_context","")
        self._sync_markdown(show_error=False)
        self.page.update()

    def _restore_quiet_startup(self):
        value = self.db.get_setting("quiet_context")
        if not value:
            return
        saved = json.loads(value)
        self._resume_work_context(saved["context"])
        if saved["kind"]=="recovery" and saved["session_id"]:
            row = self.db.row("SELECT ended_at FROM recovery_sessions WHERE id=?", (saved["session_id"],))
            if row is not None and row["ended_at"] is not None:
                self.db.set_setting("quiet_context","")
                return
            if row is None:
                saved["session_id"] = None
                self.db.set_setting("quiet_context",json.dumps(saved,ensure_ascii=False))
        self._show_quiet(saved["kind"],saved["session_id"])
