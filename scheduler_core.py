"""
Core scheduling logic: parses tutor availability CSV text and runs
the OR-Tools CP-SAT solver. Shared by the Flask web app.
"""

import csv
import io
import re
from ortools.sat.python import cp_model

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

DAY_START = "10:00"   # 24hr format
DAY_END = "18:00"      # 24hr format

TUTORS_PER_SLOT = 2

NAME_COLUMN = "Name"
MAX_HOURS_COLUMN = "Max hours per week"
UNAVAILABLE_DAYS_COLUMN = "Days completely unavailable"


def day_column_name(day):
    return f"Availability - {day} [Available Time Slots]"


def time_to_minutes(t):
    t = t.strip()
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def build_slots(start, end):
    start_min = time_to_minutes(start)
    end_min = time_to_minutes(end)
    slots = []
    t = start_min
    while t < end_min:
        h1, m1 = divmod(t, 60)
        h2, m2 = divmod(t + 30, 60)
        label1 = f"{((h1 - 1) % 12) + 1}:{m1:02d}"
        label2 = f"{((h2 - 1) % 12) + 1}:{m2:02d}"
        slots.append(f"{label1}-{label2}")
        t += 30
    return slots


SLOTS = build_slots(DAY_START, DAY_END)


def normalize(s):
    return re.sub(r"\s+", "", s).lower()


def load_tutors_from_csv_text(csv_text):
    tutors = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        name = (row.get(NAME_COLUMN) or "").strip()
        if not name:
            continue

        max_hours_raw = (row.get(MAX_HOURS_COLUMN) or "").strip()
        match = re.search(r"[\d.]+", max_hours_raw)
        max_hours = float(match.group()) if match else 999

        unavailable_days = set()
        raw_days = row.get(UNAVAILABLE_DAYS_COLUMN, "") or ""
        for day in DAYS:
            if day.lower() in raw_days.lower():
                unavailable_days.add(day)

        availability = {}
        for day in DAYS:
            col = day_column_name(day)
            raw = row.get(col, "") or ""
            checked = [normalize(x) for x in raw.split(",") if x.strip()]
            avail_slots = set()
            if day not in unavailable_days:
                for slot in SLOTS:
                    if normalize(slot) in checked:
                        avail_slots.add(slot)
            availability[day] = avail_slots

        tutors.append({
            "name": name,
            "max_hours": max_hours,
            "availability": availability,
        })
    return tutors


def solve_schedule(tutors, tutors_per_slot=None):
    if tutors_per_slot is None:
        tutors_per_slot = TUTORS_PER_SLOT

    model = cp_model.CpModel()
    x = {}

    for ti, tutor in enumerate(tutors):
        for day in DAYS:
            for si, slot in enumerate(SLOTS):
                if slot in tutor["availability"][day]:
                    x[ti, day, si] = model.NewBoolVar(f"x_{ti}_{day}_{si}")

    shortfall = {}
    for day in DAYS:
        for si in range(len(SLOTS)):
            assigned = [x[ti, day, si] for ti in range(len(tutors)) if (ti, day, si) in x]
            shortfall[day, si] = model.NewIntVar(0, tutors_per_slot, f"short_{day}_{si}")
            if assigned:
                model.Add(sum(assigned) + shortfall[day, si] >= tutors_per_slot)
                model.Add(sum(assigned) <= tutors_per_slot)
            else:
                model.Add(shortfall[day, si] == tutors_per_slot)

    for ti, tutor in enumerate(tutors):
        assigned_slots = [x[ti, day, si] for day in DAYS for si in range(len(SLOTS)) if (ti, day, si) in x]
        if assigned_slots:
            model.Add(sum(assigned_slots) * 30 <= int(tutor["max_hours"] * 60))

    block_starts = []
    for ti in range(len(tutors)):
        for day in DAYS:
            for si in range(len(SLOTS)):
                if (ti, day, si) not in x:
                    continue
                if si == 0 or (ti, day, si - 1) not in x:
                    block_starts.append(x[ti, day, si])
                else:
                    start_var = model.NewBoolVar(f"start_{ti}_{day}_{si}")
                    model.Add(start_var >= x[ti, day, si] - x[ti, day, si - 1])
                    model.Add(start_var <= x[ti, day, si])
                    block_starts.append(start_var)

    total_shortfall = sum(shortfall.values())
    total_block_starts = sum(block_starts)
    model.Minimize(total_shortfall * 1000 + total_block_starts)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None

    result = {}
    for day in DAYS:
        for si in range(len(SLOTS)):
            names = [tutors[ti]["name"] for ti in range(len(tutors)) if (ti, day, si) in x and solver.Value(x[ti, day, si])]
            result[day, si] = names

    uncovered = [(d, SLOTS[s]) for (d, s), v in shortfall.items() if solver.Value(v) > 0]

    return result, uncovered


def result_to_grid(result):
    """Returns a list of rows: [{'time': slot_label, 'Monday': 'Name1, Name2', ...}, ...]"""
    grid = []
    for si, slot in enumerate(SLOTS):
        row = {"time": slot}
        for day in DAYS:
            row[day] = ", ".join(result.get((day, si), []))
        grid.append(row)
    return grid
