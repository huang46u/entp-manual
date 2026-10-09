"""Focused scenarios driven through callbacks in the real Flet desktop client.

The resume pass is a separate process against the same isolated database.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import flet as ft

from tests.desktop_e2e import _walk


async def run_structure_scenarios(ui,report_path: Path,*,resume=False):
    report_path.parent.mkdir(parents=True,exist_ok=True)
    cases = []
    async def screenshot(name):
        ui.page.update()
        await asyncio.sleep(0.6)
        target = report_path.parent / f"{report_path.stem}-{name}.png"
        target.write_bytes(await ui.page.take_screenshot(pixel_ratio=1.0))
        return str(target)

    def click(label):
        for c in _walk(ui.content_switcher.content):
            if isinstance(c,(ft.TextButton,ft.FilledButton,ft.OutlinedButton)) and c.content==label:
                c.on_click(SimpleNamespace(control=c))
                return
        raise AssertionError(f"找不到操作：{label}")

    async def case(name,action):
        try:
            result = action()
            if hasattr(result,"__await__"):
                result = await result
            cases.append({"name":name,"status":"PASS","evidence":result or "通过"})
        except Exception:
            import traceback
            cases.append({"name":name,"status":"FAIL","evidence":traceback.format_exc()})

    async def restart():
        assert ui._quiet_mode=="recovery"
        assert ui._structure_route[0]=="experiment"
        assert ui._structure_fields["method"].value=="重启后继续的修正方案"
        assert ui.quick_task_input.value=="恢复前未提交的任务"
        assert ui._quiet_activity.value=="听音乐"
        await screenshot("recovery-resumed")
        ui.exit_quiet()
        assert ui._structure_fields["method"].value=="重启后继续的修正方案"
        await screenshot("experiment-resumed")
        return "独立进程重启后恢复降落界面，退出后还原实验草稿和快速输入"

    async def research():
        ui.show_view(ui.NAV_CURRENT)
        ui.quick_task_input.value="QA：网格科研全流程"
        ui.quick_task_input.on_submit(SimpleNamespace(control=ui.quick_task_input))
        task = ui.db.row("SELECT id FROM tasks WHERE title='QA：网格科研全流程' ORDER BY id DESC")[0]
        ui.set_focus_task(task)
        click("进入实验模式")
        ui._structure_fields["question"].value="参数是否改变局部拓扑？"
        click("开始记录实验")
        for n in range(2):
            if n:
                click("继续下一次实验")
                assert ui._structure_fields["hypothesis"].value=="修正局部符号"
            ui._structure_fields["method"].value=f"实际运行方案 {n+1}"
            ui._structure_fields["observation"].value=f"非流形边：{2 if not n else 0}"
            ui._structure_fields["next_hypothesis"].value="修正局部符号"
            click("保存实际观察")
        eid = ui._structure_route[1]
        assert len(ui.db.task_execution_logs(task))==2
        click("继续下一次实验")
        ui._structure_fields["method"].value="重启后继续的修正方案"
        ui._structure_fields["method"].on_change(SimpleNamespace(control=ui._structure_fields["method"]))
        await screenshot("experiment")
        ui.db.set_setting("structure_qa_task",str(task))
        ui.db.set_setting("structure_qa_experiment",str(eid))
        return "两轮观察独立保存，第三轮草稿留待重启"

    async def waiting():
        task = int(ui.db.get_setting("structure_qa_task"))
        before = dict(ui.db.get_task(task))
        ui.show_view(ui.NAV_WAITING)
        click("创建等待事项")
        f = ui._structure_fields
        for key,value in dict(title="QA：等待 HR 提供薪酬",who="HR",facts="已经发送资料",task=str(task),check=(date.today()+timedelta(days=3)).isoformat()).items():
            f[key].value=value
        click("保存等待事项")
        wid = ui.db.row("SELECT id FROM waiting_items ORDER BY id DESC LIMIT 1")[0]
        ui.show_view(ui.NAV_CURRENT)
        assert any(isinstance(c,ft.Text) and "依赖外部输入" in str(c.value) for c in _walk(ui.focus_holder))
        await screenshot("waiting-focus")
        ui.show_view(ui.NAV_WAITING)
        ui.open_waiting(wid)
        ui._structure_fields["check"].value=date.today().isoformat()
        click("保存等待事项")
        assert ui.db.row("SELECT status FROM waiting_items WHERE id=?",(wid,))[0]=="check"
        await screenshot("waiting-check")
        ui.open_waiting(wid)
        f = ui._structure_fields
        for key,value in dict(facts="收到薪酬方案",state="actionable",has_action="1",action="回复方案").items():
            f[key].value=value
        click("保存等待事项")
        assert dict(ui.db.get_task(task))==before
        return "等待→需要检查→可行动，焦点和任务状态未改变"

    async def pressure():
        ui.show_view(ui.NAV_TODAY)
        ui.open_anchor()
        f = ui._structure_fields
        for key,value in dict(title="QA：外部高压交流事件",source="QA 场景中的公司组织方",day=date.today().isoformat(),start="10:00").items():
            f[key].value=value
        click("保存外部锚点")
        aid = ui.db.row("SELECT id FROM external_anchors ORDER BY id DESC LIMIT 1")[0]
        await screenshot("today-structure")
        ui.open_anchor(aid)
        ui._structure_fields["status"].value="ended"
        click("保存外部锚点")
        previous = ui.content_switcher.content
        ui.quick_today_input.value="恢复前的今日输入"
        ui.enter_recovery()
        assert not ui.page.controls[0].visible
        ui._quiet_activity.value="出去走一走"
        await screenshot("recovery")
        ui.exit_quiet()
        assert ui.content_switcher.content is previous
        assert ui.quick_today_input.value=="恢复前的今日输入"
        assert ui.db.row("SELECT activity FROM recovery_sessions ORDER BY id DESC LIMIT 1")[0]=="出去走一走"
        return "外部事件结束后主动恢复，覆盖任务界面，退出返回同一控件树"

    async def review():
        ui.open_worry()
        ui._structure_fields["content"].value="QA：等待答复占据注意力"
        click("保存")
        ui.open_assessment(date.today().isoformat())
        ui._structure_fields["pressure"].value="适中"
        click("保存状态记录")
        ui.show_view(ui.NAV_CALENDAR)
        assert len(ui.db.structure_review())==14
        await screenshot("review")
        return "担忧原文、自愿状态与 14 天回顾均有真实记录"

    async def checkpoint():
        eid = int(ui.db.get_setting("structure_qa_experiment"))
        ui.show_view(ui.NAV_CURRENT)
        ui.open_experiment(experiment_id=eid)
        ui.quick_task_input.value="恢复前未提交的任务"
        ui.enter_recovery()
        ui._quiet_activity.value="听音乐"
        ui._quiet_activity.on_change(SimpleNamespace(control=ui._quiet_activity))
        await screenshot("restart-checkpoint")
        return "开放恢复会话与实验草稿已保存，供下一独立进程验证"

    if resume:
        await case("跨进程重启与工作上下文",restart)
    else:
        for name,action in (("科研实验闭环",research),("等待外部反馈",waiting),("高压事件结束与恢复",pressure),
                            ("担忧与状态回顾",review),("保存重启检查点",checkpoint)):
            await case(name,action)
    total,missing = ui.interaction_boundary_audit()
    result = {"driver":"real Flet desktop callback integration; native screenshot verification",
        "database":str(ui.db.path),"window":f"{ui.page.window.width}x{ui.page.window.height}",
        "failed":sum(c["status"]=="FAIL" for c in cases),"cases":cases,
        "callback_count":total,"unprotected_callbacks":missing}
    if missing:
        result["failed"]+=1
    report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result
