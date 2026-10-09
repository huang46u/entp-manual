"""Shared colors and small building blocks for every Flet surface.

The main shell (``flet_app``) and the life-structure panels (``structure_ui``)
import from here so both halves of the app draw with the same palette,
radii and button density.
"""
from __future__ import annotations

import flet as ft


BLUE = "#316BEE"
BLUE_DARK = "#2457CC"
BLUE_SOFT = "#EEF3FF"
INK = "#171A21"
INK_SOFT = "#454B57"
MUTED = "#737986"
FAINT = "#A3A8B2"
LINE = "#E7E9EE"
SURFACE = "#FFFFFF"
SURFACE_SOFT = "#F7F8FB"
SIDEBAR = "#F7F8FB"
CANVAS = "#FBFCFE"
GREEN = "#37A46A"
GREEN_SOFT = "#EAF7EF"
AMBER = "#B87818"
AMBER_SOFT = "#FFF6DF"
PURPLE = "#7A5AE0"
PURPLE_SOFT = "#F2EEFF"
RED = "#E45959"
RED_SOFT = "#FDEEEE"

# Reading pages (lists and forms) stay narrow enough to scan; boards and
# two-column layouts use the wider limit on large monitors.
READING_WIDTH = 1080
FORM_WIDTH = 860
WIDE_WIDTH = 1640


def rounded(radius: int = 18) -> ft.RoundedRectangleBorder:
    return ft.RoundedRectangleBorder(radius=radius)


def surface(
    content: ft.Control,
    *,
    padding: int | ft.Padding = 20,
    radius: int = 18,
    bgcolor: str = SURFACE,
    border_color: str | None = LINE,
    **kwargs,
) -> ft.Container:
    """A flat outlined panel: the single card style used across the app."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=bgcolor,
        border=ft.Border.all(1, border_color) if border_color else None,
        border_radius=radius,
        **kwargs,
    )


def tool_button(label: str, icon=None, on_click=None, *, color: str = INK_SOFT, **kwargs) -> ft.TextButton:
    """Compact secondary action; content stays the plain label string."""
    return ft.TextButton(
        label,
        icon=icon,
        on_click=on_click,
        style=ft.ButtonStyle(
            color=color,
            icon_color=color,
            icon_size=17,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            shape=rounded(10),
            text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_500),
        ),
        **kwargs,
    )


def group_label(value: str) -> ft.Text:
    return ft.Text(value, size=12, weight=ft.FontWeight.W_600, color=FAINT)


def tag(value: str, *, color: str = MUTED, bgcolor: str = SURFACE_SOFT, icon=None) -> ft.Container:
    items: list[ft.Control] = []
    if icon is not None:
        items.append(ft.Icon(icon, size=13, color=color))
    items.append(ft.Text(value, size=12, weight=ft.FontWeight.W_600, color=color))
    return ft.Container(
        content=ft.Row(items, spacing=4, tight=True),
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        bgcolor=bgcolor,
        border_radius=99,
    )


def icon_badge(icon, *, color: str = BLUE, bgcolor: str = BLUE_SOFT, size: int = 32) -> ft.Container:
    return ft.Container(
        ft.Icon(icon, size=round(size * 0.55), color=color),
        width=size,
        height=size,
        bgcolor=bgcolor,
        border_radius=size * 0.32,
        alignment=ft.Alignment.CENTER,
    )


def panel_header(title: str, subtitle: str = "", *, icon=None, color: str = BLUE,
                 bgcolor: str = BLUE_SOFT, trailing: list[ft.Control] | None = None) -> ft.Row:
    texts: list[ft.Control] = [ft.Text(title, size=16, weight=ft.FontWeight.W_700, color=INK)]
    if subtitle:
        texts.append(ft.Text(subtitle, size=13, color=MUTED))
    lead: list[ft.Control] = []
    if icon is not None:
        lead.append(icon_badge(icon, color=color, bgcolor=bgcolor))
    lead.append(ft.Column(texts, spacing=2, tight=True))
    return ft.Row(
        [
            ft.Row(lead, spacing=12, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            *([ft.Row(trailing, spacing=4, tight=True, wrap=True)] if trailing else []),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        wrap=True,
    )


def page_title(title: str, subtitle: str = "") -> ft.Column:
    controls: list[ft.Control] = [ft.Text(title, size=27, weight=ft.FontWeight.W_700, color=INK)]
    if subtitle:
        controls.append(ft.Text(subtitle, size=15, color=MUTED))
    return ft.Column(controls, spacing=5)


def constrained(content: ft.Control, width: int) -> ft.Container:
    """Center ``content`` and cap its width; narrow windows still clamp it.

    Alignment loosens the child's constraints, so the fixed width acts as a
    maximum rather than forcing horizontal overflow.
    """
    return ft.Container(
        ft.Container(content, width=width),
        alignment=ft.Alignment.TOP_CENTER,
        expand=True,
    )
