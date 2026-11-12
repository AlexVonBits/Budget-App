import calendar as cal_mod
import json
import os
import sys
from datetime import date, datetime, timedelta

import flet as ft
from flet_charts import (
    BarChart,
    BarChartGroup,
    BarChartRod,
    ChartAxis,
    ChartAxisLabel,
    PieChart,
    PieChartSection,
)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DATA_FILE = os.path.join(app_dir(), "budget_data.json")
PDF_FILE = os.path.join(app_dir(), "budget_export.pdf")

PAY_FREQUENCIES = {
    "Weekly": 4.33,
    "Biweekly": 2.17,
    "Twice a Month": 2.0,
    "Monthly": 1.0,
}
PAY_STEP_DAYS = {"Weekly": 7, "Biweekly": 14}
DOW_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

DEFAULT_DATA = {
    "bills": [],
    "paychecks": [],
    "bank_balance": 0.0,
    "put_away": 0.0,
    "paid_this_week": False,
    "frequency": "Biweekly",
    "set_aside": 0.0,
    "gas": 0.0,
    "groceries": 0.0,
    "next_payday": "",
}

CHART_COLORS = [
    "#4C78A8", "#F58518", "#E45756", "#72B7B2", "#54A24B",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC",
]


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            data = {**DEFAULT_DATA, **saved}
            for b in data["bills"]:
                b.setdefault("kind", "monthly")
                b.setdefault("due_day", 1)
                b.setdefault("last_paid", None)
            if not data.get("paychecks") and data.get("paycheck"):
                data["paychecks"] = [{
                    "amount": float(data["paycheck"]),
                    "logged": date.today().isoformat(),
                }]
            data.pop("paycheck", None)
            return data
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def money(value):
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def parse_amount(text):
    text = (text or "").replace("$", "").replace(",", "").strip()
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def input_text(value):
    if not value:
        return ""
    return str(int(value)) if value == int(value) else str(value)


def parse_date(text):
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def avg_paycheck(data):
    checks = [p["amount"] for p in data["paychecks"] if p.get("amount", 0) > 0]
    return round(sum(checks) / len(checks), 2) if checks else 0.0


def skipped_payday(data):
    """Next scheduled payday >= today, when the user was already paid early."""
    if not data.get("paid_this_week"):
        return None
    anchor = parse_date(data["next_payday"])
    if not anchor:
        return None
    horizon = date.today() + timedelta(days=366)
    pdates = payday_dates(date.today(), horizon, data["frequency"], anchor)
    return pdates[0] if pdates else None


def next_payday_after(d, freq):
    if freq in PAY_STEP_DAYS:
        return d + timedelta(days=PAY_STEP_DAYS[freq])
    if freq == "Twice a Month":
        if d.day < 15:
            return d.replace(day=15)
        m, y = (d.month + 1, d.year) if d.month < 12 else (1, d.year + 1)
        return date(y, m, 1)
    m, y = (d.month + 1, d.year) if d.month < 12 else (1, d.year + 1)
    return date(y, m, min(d.day, cal_mod.monthrange(y, m)[1]))


def payday_dates(start, end, freq, anchor):
    if not anchor or anchor > end:
        return []
    dates = []
    if freq in PAY_STEP_DAYS:
        d = anchor
        while d <= end:
            if d >= start:
                dates.append(d)
            d += timedelta(days=PAY_STEP_DAYS[freq])
    else:
        d = anchor
        while d <= end:
            if d >= start:
                dates.append(d)
            d = next_payday_after(d, freq)
    dates.sort()
    return dates


def bill_occurrences(bill, start, end):
    paid_thru = parse_date(bill.get("last_paid"))
    kind = bill.get("kind", "monthly")
    if kind == "once" and paid_thru:
        return []
    if kind == "monthly":
        out = []
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            d = date(y, m, min(bill["due_day"], cal_mod.monthrange(y, m)[1]))
            if start <= d <= end and not (paid_thru and d <= paid_thru):
                out.append(d)
            m += 1
            if m > 12:
                y, m = y + 1, 1
        return out
    if kind == "weekly":
        delta = (bill.get("due_dow", 0) - start.weekday()) % 7
        d = start + timedelta(days=delta)
        out = []
        while d <= end:
            if not (paid_thru and d <= paid_thru):
                out.append(d)
            d += timedelta(days=7)
        return out
    try:
        d = date.fromisoformat(bill.get("due_date", ""))
    except (ValueError, TypeError):
        return []
    if paid_thru and d <= paid_thru:
        return []
    return [d] if start <= d <= end else []


def bill_label(bill):
    kind = bill.get("kind", "monthly")
    if kind == "monthly":
        return f"monthly, due the {ordinal(bill['due_day'])}"
    if kind == "weekly":
        return f"weekly, every {DOW_NAMES[bill.get('due_dow', 0)]}"
    try:
        d = date.fromisoformat(bill.get("due_date", ""))
        return f"one time, {d.strftime('%b %d')}"
    except (ValueError, TypeError):
        return "one time"


def monthly_items(data):
    items = []
    for b in data["bills"]:
        if b["amount"] <= 0:
            continue
        if b.get("kind", "monthly") == "weekly":
            items.append((f"{b['name']} (wk)", round(b["amount"] * 4.33, 2)))
        elif b.get("kind", "monthly") == "monthly":
            items.append((b["name"], b["amount"]))
    if data["gas"] > 0:
        items.append(("Gas", data["gas"]))
    if data["groceries"] > 0:
        items.append(("Groceries", data["groceries"]))
    return items


def projection(data, bank, avg_pay, set_aside, gas, groceries, end):
    today = date.today()
    anchor = parse_date(data["next_payday"])
    pdates = payday_dates(today, end, data["frequency"], anchor) if avg_pay > 0 else []
    skip = skipped_payday(data)
    if skip:
        pdates = [d for d in pdates if d != skip]

    events = {}

    def event(d):
        return events.setdefault(d, {"pay": 0.0, "bills": 0.0, "ess": 0.0})

    for d in pdates:
        event(d)["pay"] += max(0.0, avg_pay - set_aside)
    for b in data["bills"]:
        for d in bill_occurrences(b, today, end):
            event(d)["bills"] += b["amount"]
    weekly_ess = (gas + groceries) / 4.33
    if weekly_ess > 0:
        d = today
        while d <= end:
            event(d)["ess"] += weekly_ess
            d += timedelta(days=7)

    days = sorted(events)
    running = bank
    bal_by_day = {}
    for d in days:
        running += events[d]["pay"] - events[d]["bills"] - events[d]["ess"]
        bal_by_day[d] = running
    safe = min([bank] + list(bal_by_day.values()))

    dip_day = min(bal_by_day, key=bal_by_day.get) if bal_by_day else None
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    dip_week = None
    if safe < 0 and dip_day is not None:
        for k in range(6):
            ws = this_sunday + timedelta(days=7 * k)
            if ws <= dip_day <= ws + timedelta(days=6):
                dip_week = ws.strftime("%b %d")
                break

    # weekly free-to-spend plan:
    # C(d) = cumulative net from today; d_k = worst dip inside week k;
    # D_k = worst dip from start of week k to horizon (relative to week start).
    # Spending backward-constrained so every future bill still clears.
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    week_bounds = [(this_sunday + timedelta(days=7 * k),
                    this_sunday + timedelta(days=7 * k + 6)) for k in range(4)]

    cum = {today: 0.0}
    run = 0.0
    for d in days:
        run += events[d]["pay"] - events[d]["bills"] - events[d]["ess"]
        cum[d] = run

    nets, dips = [], []
    for ws, we in week_bounds:
        lo = max(ws, today)
        wdays = [d for d in days if lo <= d <= we]
        nets.append(sum(events[d]["pay"] - events[d]["bills"] - events[d]["ess"]
                        for d in wdays))
        if ws <= today:
            c_before = 0.0
        else:
            earlier = [d for d in days if d < ws]
            c_before = cum[max(earlier)] if earlier else 0.0
        dips.append(min([0.0] + [cum[d] - c_before for d in wdays]))

    we_last = week_bounds[-1][1]
    after = [d for d in days if d > we_last]
    if after:
        c_at_end = cum[max(d for d in days if d <= we_last)] \
            if any(d <= we_last for d in days) else 0.0
        D = [0.0] * 5
        D[4] = min(cum[d] - c_at_end for d in after)
    else:
        D = [0.0] * 5
    for k in range(3, -1, -1):
        D[k] = min(dips[k], nets[k] + D[k + 1])

    weeks = []
    B = bank
    for k, (ws, we) in enumerate(week_bounds):
        lo = max(ws, today)
        b_sum = sum(e["bills"] for d, e in events.items() if lo <= d <= we)
        e_sum = sum(e["ess"] for d, e in events.items() if lo <= d <= we)
        p_sum = sum(e["pay"] for d, e in events.items() if lo <= d <= we)
        free = max(0.0, min(nets[k], B + dips[k], B + nets[k] + D[k + 1]))
        weeks.append({
            "label": ws.strftime("%b %d"),
            "bills": b_sum,
            "ess": e_sum,
            "pay": p_sum,
            "net": nets[k],
            "free": free,
            "kept": max(0.0, nets[k] - free),
            # only a real shortfall if this week's own balance goes negative
            "short": max(0.0, -(B + dips[k])),
        })
        B += nets[k] - free
    return {"safe": safe, "events": events, "paydays": pdates,
            "weeks": weeks, "dip_week": dip_week}


def main(page: ft.Page):
    page.title = "Budget"
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    data = load_data()
    today = date.today()
    cal_year, cal_month = today.year, today.month

    safe_text = ft.Text(size=22, weight=ft.FontWeight.BOLD)
    safe_sub_text = ft.Text(size=13, color=ft.Colors.GREY_600)
    weekly_column = ft.Column(spacing=2)
    bank_text = ft.Text(size=14)
    put_away_text = ft.Text(size=14)
    bills_per_paycheck_text = ft.Text(size=14)
    set_aside_text = ft.Text(size=14)
    spending_text = ft.Text(size=16, weight=ft.FontWeight.BOLD)
    total_bills_text = ft.Text(size=14, weight=ft.FontWeight.BOLD)
    bills_list = ft.Column(spacing=2)
    paychecks_list = ft.Column(spacing=2)
    avg_pay_text = ft.Text(size=14, weight=ft.FontWeight.BOLD)
    calendar_area = ft.Column(spacing=3)
    form_error = ft.Text(size=12, color=ft.Colors.RED_400)
    pay_error = ft.Text(size=12, color=ft.Colors.RED_400)
    status_text = ft.Text(size=12)
    paid_early_text = ft.Text(size=12, color=ft.Colors.ORANGE_700)

    pie_chart = PieChart(
        width=220,
        height=220,
        sections=[],
        sections_space=2,
        center_space_radius=0,
    )
    pie_legend = ft.Column(spacing=4)

    bar_chart = BarChart(
        width=360,
        height=240,
        groups=[],
        bottom_axis=ChartAxis(labels=[], label_size=32),
        left_axis=ChartAxis(label_size=40),
        max_y=1,
        interactive=True,
    )

    def set_status(message, error=False):
        status_text.value = message
        status_text.color = ft.Colors.RED_400 if error else ft.Colors.GREEN_700
        page.update()

    def refresh_results(c):
        has_payday = bool(parse_date(data["next_payday"]))
        if avg_paycheck(data) == 0 or not has_payday:
            safe_sub_text.value = "Log a paycheck and set your next payday so future checks count in the projection."
        elif c["safe"] >= 0:
            safe_text.value = f"Safe to spend right now: {money(c['safe'])}"
            safe_text.color = ft.Colors.GREEN_600
            safe_sub_text.value = "Keeps every upcoming bill covered for the next 2 months."
        else:
            if c["dip_week"]:
                safe_text.value = (
                    f"You're {money(-c['safe'])} short for the week of {c['dip_week']}"
                )
            else:
                safe_text.value = f"You're {money(-c['safe'])} short for upcoming bills"
            safe_text.color = ft.Colors.RED_600
            safe_sub_text.value = (
                "Every week below is already holding back its spare cash for bills — "
                "you'll still need a lower bill, a moved due date, or extra income."
            )

        weekly_column.controls = []
        for w in c["weeks"]:
            if w["short"] > 0:
                head = (f"Week of {w['label']}:  bills {money(w['bills'])} · "
                        f"gas/food {money(w['ess'])} · pay {money(w['pay'])} · short ")
                val, val_color = money(w["short"]), ft.Colors.RED_600
            else:
                head = (f"Week of {w['label']}:  bills {money(w['bills'])} · "
                        f"gas/food {money(w['ess'])} · pay {money(w['pay'])} · free to spend ")
                val = money(w["free"])
                val_color = (ft.Colors.GREEN_600 if w["kept"] <= 0
                             else ft.Colors.ORANGE_600)
            spans = [ft.TextSpan(val, ft.TextStyle(
                color=val_color, weight=ft.FontWeight.BOLD))]
            if w["kept"] > 0:
                spans.append(ft.TextSpan(
                    f"  (keep {money(w['kept'])} back for bills ahead)",
                    ft.TextStyle(color=ft.Colors.GREY_600, size=11),
                ))
            weekly_column.controls.append(ft.Text(head, size=13, spans=spans))

        left = c["total_funds"] - c["monthly_total"]
        if left >= 0:
            bank_text.value = f"Money for bills covers this month's bills & essentials with {money(left)} to spare."
            bank_text.color = ft.Colors.GREEN_600
        else:
            bank_text.value = f"You're {money(-left)} short for this month's bills & essentials."
            bank_text.color = ft.Colors.RED_600
        if c["put_away"] > 0:
            put_away_text.value = (f"Put away for future bills: {money(c['put_away'])} "
                                   f"— total for bills: {money(c['total_funds'])}")
            put_away_text.color = ft.Colors.BLUE_700
        else:
            put_away_text.value = ""

        skip_d = c.get("skip_payday")
        if skip_d:
            paid_early_text.value = (
                f"Marked already paid for this week — the {skip_d.strftime('%b %d')} "
                "paycheck is excluded from the projection."
            )
        else:
            paid_early_text.value = ""
        bills_per_paycheck_text.value = (
            f"Avg bills per paycheck (incl. gas & groceries): {money(c['per_paycheck'])}"
        )
        set_aside_text.value = f"Set aside: {money(c['set_aside'])}"
        spending_text.value = f"Avg free money per paycheck: {money(c['spending'])}"
        spending_text.color = (
            ft.Colors.GREEN_600 if c["spending"] >= 0 else ft.Colors.RED_600
        )
        total_bills_text.value = (
            f"Total recurring monthly bills: {money(c['monthly_bills'])}"
        )

    def refresh_charts(c):
        items = monthly_items(data)

        if not items:
            pie_chart.sections = []
            pie_legend.controls = [
                ft.Text("Add a bill to see the breakdown.",
                        color=ft.Colors.GREY_500, size=12)
            ]
        else:
            total = sum(amount for _, amount in items)
            sections, legend = [], []
            for i, (name, amount) in enumerate(items):
                color = CHART_COLORS[i % len(CHART_COLORS)]
                pct = amount / total * 100
                sections.append(PieChartSection(
                    value=amount,
                    title=f"{pct:.0f}%" if pct >= 8 else "",
                    title_style=ft.TextStyle(
                        color=ft.Colors.WHITE, size=11,
                        weight=ft.FontWeight.BOLD,
                    ),
                    color=color,
                    radius=62,
                ))
                legend.append(ft.Row([
                    ft.Container(width=10, height=10, bgcolor=color,
                                 border_radius=2),
                    ft.Text(f"{name} — {money(amount)}", size=12),
                ], spacing=6))
            pie_chart.sections = sections
            pie_legend.controls = legend

        bar_values = [
            ("Bills", c["per_paycheck"], "#4C78A8"),
            ("Set aside", c["set_aside"], "#F58518"),
            ("Free money", c["spending"],
             "#54A24B" if c["spending"] >= 0 else "#E45756"),
        ]
        if all(v == 0 for _, v, _ in bar_values):
            bar_chart.groups = []
            bar_chart.bottom_axis = ChartAxis(labels=[], label_size=32)
        else:
            peak = max(max(v for _, v, _ in bar_values), 1.0)
            bar_chart.groups = [
                BarChartGroup(x=i, rods=[BarChartRod(
                    from_y=0, to_y=max(0, v), width=26, color=color,
                    tooltip=money(v), border_radius=4,
                )])
                for i, (_, v, color) in enumerate(bar_values)
            ]
            bar_chart.bottom_axis = ChartAxis(
                labels=[ChartAxisLabel(value=i, label=ft.Text(label, size=11))
                        for i, (label, _, _) in enumerate(bar_values)],
                label_size=32,
            )
            bar_chart.max_y = peak * 1.25

    def refresh_calendar(c):
        first = date(cal_year, cal_month, 1)
        month_name = date(cal_year, cal_month, 1).strftime("%B %Y")
        dim = cal_mod.monthrange(cal_year, cal_month)[1]
        last = date(cal_year, cal_month, dim)
        anchor = parse_date(data["next_payday"])
        paydays = set(payday_dates(first, last, data["frequency"], anchor)
                      ) if avg_paycheck(data) > 0 else set()
        paydays.discard(skipped_payday(data))

        due = {}
        for i, b in enumerate(data["bills"]):
            for d in bill_occurrences(b, first, last):
                due.setdefault(d, []).append((i, b))

        controls = [
            ft.Row([
                ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=cal_prev,
                              icon_size=20),
                ft.Text(month_name, size=18, weight=ft.FontWeight.BOLD,
                        expand=True, text_align=ft.TextAlign.CENTER),
                ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=cal_next,
                              icon_size=20),
            ], spacing=4),
            ft.Row([
                ft.Container(ft.Text(d, size=11, weight=ft.FontWeight.BOLD,
                                     color=ft.Colors.GREY_500,
                                     text_align=ft.TextAlign.CENTER),
                             expand=True)
                for d in DOW_NAMES
            ]),
        ]

        start_col = (first.weekday() + 1) % 7
        cells = [None] * start_col + [
            date(cal_year, cal_month, d) for d in range(1, dim + 1)
        ]
        while len(cells) % 7:
            cells.append(None)

        for week_start in range(0, len(cells), 7):
            row = []
            for cell in cells[week_start:week_start + 7]:
                row.append(day_cell(cell, due, paydays))
            controls.append(ft.Row(row, spacing=3))

        calendar_area.controls = controls

    def day_cell(cell, due, paydays):
        if cell is None:
            return ft.Container(expand=True)
        is_today = cell == today
        is_weekend = cell.weekday() >= 5
        entries = []
        day_bills = sorted(due.get(cell, []),
                           key=lambda ib: -ib[1]["amount"])
        for i, b in day_bills[:2]:
            entries.append(ft.Row([
                ft.Container(width=6, height=6, border_radius=3,
                             bgcolor=CHART_COLORS[i % len(CHART_COLORS)]),
                ft.Text(f"{b['amount']:,.0f} {b['name'][:10]}",
                        size=9, color=ft.Colors.GREY_900),
            ], spacing=2, tight=True))
        if len(day_bills) > 2:
            entries.append(ft.Text(f"+{len(day_bills) - 2} more", size=8,
                                   color=ft.Colors.GREY_500))
        if cell in paydays:
            entries.append(ft.Text(
                f"+{avg_paycheck(data):,.0f} pay", size=9,
                color=ft.Colors.GREEN_600, weight=ft.FontWeight.BOLD))
        return ft.Container(
            expand=True,
            height=74,
            padding=5,
            border_radius=8,
            bgcolor=ft.Colors.BLUE_200 if is_today else (
                ft.Colors.BLUE_GREY_300 if is_weekend else ft.Colors.BLUE_GREY_200),
            border=ft.Border.all(
                2 if is_today else 1,
                ft.Colors.BLUE_700 if is_today else ft.Colors.BLUE_GREY_400,
            ),
            content=ft.Column([
                ft.Text(str(cell.day), size=11,
                        weight=ft.FontWeight.BOLD if is_today else None,
                        color=ft.Colors.BLUE_900 if is_today
                        else ft.Colors.GREY_800),
                *entries,
            ], spacing=1, tight=True),
        )

    def refresh_bills():
        if data["bills"]:
            bills_list.controls = [
                ft.Row([
                    ft.Container(width=10, height=10, border_radius=2,
                                 bgcolor=CHART_COLORS[i % len(CHART_COLORS)]),
                    ft.Text(f"{b['name']} — {bill_label(b)}", expand=True,
                            size=13),
                    ft.Text(money(b["amount"]), size=13),
                    ft.Text(f"paid thru "
                            f"{parse_date(b['last_paid']).strftime('%b %d')}"
                            if b.get("last_paid") else "",
                            size=11, color=ft.Colors.GREEN_600),
                    ft.IconButton(
                        ft.Icons.CHECK_CIRCLE_OUTLINE if not b.get("last_paid")
                        else ft.Icons.CHECK_CIRCLE,
                        tooltip="Mark paid" if not b.get("last_paid")
                        else "Undo paid",
                        icon_color=ft.Colors.GREEN_600,
                        on_click=toggle_paid(i),
                    ),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE,
                                  icon_color=ft.Colors.RED_400,
                                  on_click=delete_bill(i)),
                ], spacing=6)
                for i, b in enumerate(data["bills"])
            ]
        else:
            bills_list.controls = [ft.Text("No bills yet.",
                                           color=ft.Colors.GREY_500)]
        page.update()

    def refresh_paychecks():
        if data["paychecks"]:
            paychecks_list.controls = [
                ft.Row([
                    ft.Text(f"{p['logged']}", size=12,
                            color=ft.Colors.GREY_600, expand=True),
                    ft.Text(money(p["amount"]), size=13),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE,
                                  icon_color=ft.Colors.RED_400,
                                  on_click=delete_paycheck(i)),
                ], spacing=6)
                for i, p in enumerate(data["paychecks"])
            ]
        else:
            paychecks_list.controls = [ft.Text("No paychecks logged yet.",
                                               color=ft.Colors.GREY_500)]
        n = len(data["paychecks"])
        avg = avg_paycheck(data)
        avg_pay_text.value = (
            f"Average paycheck: {money(avg)} (from {n} logged)"
            if n else "Average paycheck: —"
        )
        page.update()

    def refresh_all():
        save_data(data)
        c = compute()
        refresh_results(c)
        refresh_charts(c)
        refresh_calendar(c)
        refresh_bills()
        refresh_paychecks()
        page.update()

    def compute():
        bank = parse_amount(bank_field.value)
        put_away = parse_amount(put_away_field.value)
        total_funds = bank + put_away
        avg = avg_paycheck(data)
        set_aside = parse_amount(set_aside_field.value)
        gas = parse_amount(gas_field.value)
        groceries = parse_amount(groceries_field.value)
        items = monthly_items(data)
        monthly_bills = sum(amount for _, amount in items
                            if not _.startswith(("Gas", "Groceries")))
        monthly_total = sum(amount for _, amount in items)
        ppm = PAY_FREQUENCIES[data["frequency"]]
        per_paycheck = monthly_total / ppm
        spending = avg - per_paycheck - set_aside
        proj = projection(data, total_funds, avg, set_aside, gas, groceries,
                          today + timedelta(days=60))
        return {
            "skip_payday": skipped_payday(data),
            "bank": bank, "put_away": put_away, "total_funds": total_funds,
            "avg_pay": avg, "n_checks": len(data["paychecks"]),
            "set_aside": set_aside, "gas": gas, "groceries": groceries,
            "monthly_bills": monthly_bills, "monthly_total": monthly_total,
            "ppm": ppm, "per_paycheck": per_paycheck, "spending": spending,
            **proj,
        }

    def bind_amount(key):
        def handler(e):
            data[key] = parse_amount(e.control.value)
            refresh_all()
        return handler

    def bind_payday(e):
        data["next_payday"] = (payday_field.value or "").strip()
        refresh_all()

    def freq_changed(e):
        data["frequency"] = (freq_selector.selected or [data["frequency"]])[0]
        refresh_all()

    def open_date_picker(e, target_field):
        def picked(ev):
            value = getattr(ev.control, "value", None)
            if value:
                target_field.value = value.strftime("%m/%d/%Y")
                target_field.on_change(ev) if hasattr(
                    target_field, "on_change") and target_field.on_change else None
                page.update()
        try:
            page.show_dialog(ft.DatePicker(
                first_date=date(2000, 1, 1),
                last_date=date(2100, 12, 31),
                current_date=today,
                on_change=picked,
            ))
        except Exception as ex:
            set_status(f"Date picker unavailable — type MM/DD/YYYY instead. ({ex})",
                       error=True)

    def add_bill(e):
        name = (name_field.value or "").strip()
        amount = parse_amount(amount_field.value)
        picked = parse_date(due_field.value)
        kind = (repeats_dropdown.value or "monthly").lower().replace(" ", "")
        kind = {"monthly": "monthly", "weekly": "weekly",
                "onetime": "once"}.get(kind, "monthly")
        if not name or amount <= 0 or not picked:
            form_error.value = "Need a bill name, an amount, and a due date."
            page.update()
            return
        bill = {"name": name, "amount": amount, "kind": kind}
        if kind == "monthly":
            bill["due_day"] = picked.day
        elif kind == "weekly":
            bill["due_dow"] = picked.weekday()
        else:
            bill["due_date"] = picked.isoformat()
        data["bills"].append(bill)
        data["bills"].sort(key=lambda b: (
            b.get("due_day", 99), b.get("due_dow", 99), b.get("due_date", "9999")
        ))
        name_field.value = ""
        amount_field.value = ""
        due_field.value = ""
        repeats_dropdown.value = "Monthly"
        form_error.value = ""
        refresh_all()

    def toggle_paid(i):
        def handler(e):
            b = data["bills"][i]
            if b.get("last_paid"):
                b["last_paid"] = None
            else:
                upcoming = [d for d in bill_occurrences(b, today,
                            today + timedelta(days=400)) if d >= today]
                b["last_paid"] = (upcoming[0].isoformat() if upcoming
                                  else today.isoformat())
            refresh_all()
        return handler

    def delete_bill(i):
        def handler(e):
            data["bills"].pop(i)
            refresh_all()
        return handler

    def log_paycheck(e):
        amount = parse_amount(paycheck_field.value)
        if amount <= 0:
            pay_error.value = "Enter the paycheck amount first."
            page.update()
            return
        data["paychecks"].append({
            "amount": amount, "logged": today.isoformat(),
        })
        anchor = parse_date(data["next_payday"])
        if anchor and anchor <= today:
            data["next_payday"] = next_payday_after(
                anchor, data["frequency"]).strftime("%m/%d/%Y")
            payday_field.value = data["next_payday"]
        paycheck_field.value = ""
        pay_error.value = ""
        refresh_all()

    def delete_paycheck(i):
        def handler(e):
            data["paychecks"].pop(i)
            refresh_all()
        return handler

    def cal_prev(e):
        nonlocal cal_month, cal_year
        cal_month -= 1
        if cal_month < 1:
            cal_month, cal_year = 12, cal_year - 1
        refresh_calendar(compute())
        page.update()

    def cal_next(e):
        nonlocal cal_month, cal_year
        cal_month += 1
        if cal_month > 12:
            cal_month, cal_year = 1, cal_year + 1
        refresh_calendar(compute())
        page.update()

    def export_pdf(e):
        try:
            from fpdf import FPDF
        except ImportError:
            set_status("PDF export needs fpdf2 — run: pip install fpdf2",
                       error=True)
            return

        c = compute()
        pdf = FPDF()
        pdf.add_page()

        def line(text, style="", size=11):
            pdf.set_font("Helvetica", style, size)
            pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")

        line("Budget Summary", "B", 16)
        line(datetime.now().strftime("Generated %B %d, %Y"), size=9)
        pdf.ln(2)
        if c["n_checks"]:
            line(f"Average paycheck: {money(c['avg_pay'])} "
                 f"({c['n_checks']} logged, {data['frequency']}, "
                 f"{c['ppm']} paychecks/month)")
        else:
            line("Average paycheck: none logged")
        line(f"Next payday: {data['next_payday'] or 'not set'}")
        if data.get("paid_this_week") and c.get("skip_payday"):
            line(f"Already paid for this week — the "
                 f"{c['skip_payday'].strftime('%b %d')} paycheck is excluded "
                 "from the projection")
        line(f"Money in bank: {money(c['bank'])}")
        line(f"Already put away for future bills: {money(c['put_away'])}")
        line(f"Total for bills (bank + put away): {money(c['total_funds'])}")
        pdf.ln(2)
        line("Bills", "B", 13)
        if data["bills"]:
            for b in data["bills"]:
                paid = ""
                if b.get("last_paid"):
                    lp = parse_date(b["last_paid"])
                    if lp:
                        paid = f" — paid thru {lp.strftime('%b %d')}"
                line(f"  {b['name']} ({bill_label(b)}): "
                     f"{money(b['amount'])}{paid}")
        else:
            line("  (none)")
        line(f"  Gas: {money(c['gas'])}")
        line(f"  Groceries: {money(c['groceries'])}")
        line(f"Recurring monthly total: {money(c['monthly_total'])}", "B")
        pdf.ln(2)
        line("Per paycheck (average)", "B", 13)
        line(f"Bills (incl. gas & groceries): {money(c['per_paycheck'])}")
        line(f"Set aside: {money(c['set_aside'])}")
        line(f"Free money: {money(c['spending'])}", "B", 12)
        pdf.ln(2)
        if c["safe"] >= 0:
            line(f"Safe to spend right now: {money(c['safe'])}", "B", 13)
        else:
            line(f"Short for upcoming bills: {money(-c['safe'])}", "B", 13)

        line("Weekly outlook", "B", 13)
        for w in c["weeks"]:
            if w["short"] > 0:
                line(f"  Week of {w['label']}: bills {money(w['bills'])} · "
                     f"gas/food {money(w['ess'])} · pay {money(w['pay'])} · "
                     f"short {money(w['short'])}")
            else:
                extra = f" (keep {money(w['kept'])} back)" if w["kept"] > 0 else ""
                line(f"  Week of {w['label']}: bills {money(w['bills'])} · "
                     f"gas/food {money(w['ess'])} · pay {money(w['pay'])} · "
                     f"free to spend {money(w['free'])}{extra}")

        pdf.add_page()
        pdf.set_auto_page_break(False)
        items = monthly_items(data)
        line("Where the money goes (monthly)", "B", 13)
        y0 = pdf.get_y()
        if items:
            total = sum(amount for _, amount in items)
            cx, cy, r = 45, y0 + 40, 32
            start = 90.0
            for i, (name, amount) in enumerate(items):
                rgb = tuple(int(CHART_COLORS[i % len(CHART_COLORS)][j:j + 2], 16)
                            for j in (1, 3, 5))
                pdf.set_fill_color(*rgb)
                sweep = amount / total * 360
                if sweep > 0:
                    pdf.arc(cx, cy, r, start, start - sweep,
                            clockwise=True, start_from_center=True,
                            end_at_center=True, style="F")
                start -= sweep
                pdf.set_fill_color(*rgb)
                pdf.rect(95, y0 + 6 + i * 8, 5, 5, style="F")
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Helvetica", "", 10)
                pdf.set_xy(104, y0 + 3 + i * 8)
                pdf.cell(80, 8, f"{name}: {money(amount)}")
            pdf.set_y(cy + r + 12)
        else:
            line("  (no bills yet)")
            pdf.set_y(y0 + 12)

        line("Per paycheck split (average)", "B", 13)
        bars = [
            ("Bills", c["per_paycheck"], (76, 120, 168)),
            ("Set aside", c["set_aside"], (245, 133, 24)),
            ("Free money", max(0, c["spending"]), (84, 162, 75)),
        ]
        base_y = pdf.get_y() + 52
        peak = max(v for _, v, _ in bars) or 1
        pdf.set_draw_color(130, 130, 130)
        pdf.set_line_width(0.3)
        pdf.line(20, base_y, 190, base_y)
        x = 45
        for label, v, color in bars:
            h = v / peak * 44
            if h > 0:
                pdf.set_fill_color(*color)
                pdf.rect(x, base_y - h, 25, h, style="F")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.set_xy(x - 6, base_y - max(h, 9) - 7)
            pdf.cell(37, 5, money(v))
            pdf.set_text_color(0, 0, 0)
            pdf.set_xy(x - 6, base_y + 2)
            pdf.cell(37, 5, label)
            x += 50

        pdf.output(PDF_FILE)
        set_status(f"Exported to {PDF_FILE}")
        try:
            os.startfile(PDF_FILE)
        except AttributeError:
            pass

    name_field = ft.TextField(label="Bill name", width=150)
    amount_field = ft.TextField(label="Amount ($)", width=110,
                                keyboard_type=ft.KeyboardType.NUMBER)
    due_field = ft.TextField(label="Due date (MM/DD/YYYY)", width=170,
                             keyboard_type=ft.KeyboardType.TEXT)
    due_date_btn = ft.IconButton(ft.Icons.CALENDAR_MONTH_OUTLINED,
                                 tooltip="Pick a date",
                                 on_click=lambda e: open_date_picker(
                                     e, due_field))
    repeats_dropdown = ft.Dropdown(
        label="Repeats", width=130,
        options=[ft.dropdown.Option("Monthly"), ft.dropdown.Option("Weekly"),
                 ft.dropdown.Option("One time")],
        value="Monthly",
    )
    paycheck_field = ft.TextField(label="Log paycheck ($)", width=150,
                                  keyboard_type=ft.KeyboardType.NUMBER)
    payday_field = ft.TextField(label="Next payday (MM/DD/YYYY)", width=170,
                                keyboard_type=ft.KeyboardType.TEXT,
                                value=data["next_payday"],
                                on_change=bind_payday)
    payday_btn = ft.IconButton(ft.Icons.CALENDAR_MONTH_OUTLINED,
                               tooltip="Pick a date",
                               on_click=lambda e: open_date_picker(
                                   e, payday_field))
    freq_selector = ft.SegmentedButton(
        segments=[ft.Segment(value=k, label=ft.Text(k))
                  for k in PAY_FREQUENCIES],
        selected=[data["frequency"]],
        allow_empty_selection=False,
        on_change=freq_changed,
    )
    set_aside_field = ft.TextField(
        label="Set aside per paycheck ($)", width=280,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=bind_amount("set_aside"),
        value=input_text(data["set_aside"]),
    )
    bank_field = ft.TextField(
        label="Money in bank now", width=280,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=bind_amount("bank_balance"),
        value=input_text(data["bank_balance"]),
    )
    put_away_field = ft.TextField(
        label="Already put away for future bills ($)", width=280,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=bind_amount("put_away"),
        value=input_text(data["put_away"]),
    )
    def toggle_paid_early(e):
        data["paid_this_week"] = bool(paid_early_check.value)
        refresh_all()

    paid_early_check = ft.Checkbox(
        label="I was already paid for this week (skip next paycheck)",
        value=bool(data.get("paid_this_week")),
        on_change=toggle_paid_early,
    )

    gas_field = ft.TextField(
        label="Gas ($/month)", width=200,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=bind_amount("gas"),
        value=input_text(data["gas"]),
    )
    groceries_field = ft.TextField(
        label="Groceries ($/month)", width=200,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=bind_amount("groceries"),
        value=input_text(data["groceries"]),
    )

    page.add(
        ft.Text("Budget", size=28, weight=ft.FontWeight.BOLD),
        ft.Container(height=8),
        ft.Text("Bills", size=16, weight=ft.FontWeight.BOLD),
        ft.Row([
            name_field, amount_field, due_field, due_date_btn,
            repeats_dropdown, ft.Button("Add bill", on_click=add_bill),
        ], spacing=8, wrap=True),
        form_error,
        bills_list,
        total_bills_text,
        ft.Divider(),
        ft.Text("Paychecks", size=16, weight=ft.FontWeight.BOLD),
        ft.Row([
            paycheck_field, ft.Button("Log paycheck", on_click=log_paycheck),
        ], spacing=8, wrap=True),
        pay_error,
        paychecks_list,
        avg_pay_text,
        ft.Container(height=8),
        ft.Row([payday_field, payday_btn], spacing=8, wrap=True),
        freq_selector,
        paid_early_check,
        paid_early_text,
        set_aside_field,
        bank_field,
        put_away_field,
        ft.Divider(),
        ft.Text("Monthly essentials", size=16, weight=ft.FontWeight.BOLD),
        ft.Row([gas_field, groceries_field], spacing=10, wrap=True),
        ft.Divider(),
        safe_text,
        safe_sub_text,
        ft.Container(height=8),
        weekly_column,
        ft.Container(height=8),
        bank_text,
        ft.Container(height=8),
        bills_per_paycheck_text,
        set_aside_text,
        spending_text,
        ft.Divider(),
        ft.Text("Bill calendar", size=16, weight=ft.FontWeight.BOLD),
        calendar_area,
        ft.Divider(),
        ft.Text("Where the money goes (monthly)", size=16,
                weight=ft.FontWeight.BOLD),
        ft.Row([pie_chart, pie_legend], spacing=30, wrap=True,
               vertical_alignment=ft.CrossAxisAlignment.START),
        ft.Container(height=10),
        ft.Text("Per paycheck (average)", size=16, weight=ft.FontWeight.BOLD),
        bar_chart,
        ft.Container(height=10),
        ft.Button("Export as PDF", icon=ft.Icons.PICTURE_AS_PDF_OUTLINED,
                  on_click=export_pdf),
        status_text,
    )
    refresh_all()


if __name__ == "__main__":
    ft.run(main)
