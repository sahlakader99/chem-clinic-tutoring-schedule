"""
Chem Clinic Scheduler - web app

Anyone visiting the site clicks one button. It pulls current
responses straight from the Google Sheet (must be shared as
"Anyone with the link can view"), runs the OR-Tools solver,
and shows the resulting schedule.

CONFIG:
  Set SHEET_CSV_URL below to your response Sheet's public CSV export link.
  How to get it:
    1. Open the response Google Sheet
    2. File > Share > "Anyone with the link" > Viewer
    3. Look at the URL: https://docs.google.com/spreadsheets/d/SHEET_ID/edit#gid=GID
    4. Build the export link:
       https://docs.google.com/spreadsheets/d/SHEET_ID/export?format=csv&gid=GID
    5. Paste that as SHEET_CSV_URL below
"""

import requests
from flask import Flask, jsonify, render_template, request

from scheduler_core import (
    DAYS,
    SLOTS,
    load_tutors_from_csv_text,
    solve_schedule,
    result_to_grid,
)

app = Flask(__name__)

# EDIT THIS to your actual Sheet's CSV export URL
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1Sdx5xTlcQzOBXNOp6aLEAOUXJIBa92hu8PnLi5kKQTQ/export?format=csv&gid=0"

# EDIT THIS each semester - schedule won't auto-generate until this many
# tutors have submitted the form. Set to 0 to disable the requirement.
MIN_TUTORS_REQUIRED = 8


@app.route("/")
def index():
    return render_template("index.html", days=DAYS)


@app.route("/generate", methods=["POST"])
def generate():
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ChemClinicScheduler/1.0)"}
        resp = requests.get(SHEET_CSV_URL, timeout=15, headers=headers)
        resp.raise_for_status()
    except Exception as e:
        return jsonify({"error": f"Couldn't reach the Google Sheet: {e}"}), 500

    csv_text = resp.text
    tutors = load_tutors_from_csv_text(csv_text)

    if not tutors:
        return jsonify({"error": "No tutor responses found. Check the Sheet has data and the URL is correct."}), 400

    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))

    if len(tutors) < MIN_TUTORS_REQUIRED and not force:
        return jsonify({
            "not_ready": True,
            "tutor_count": len(tutors),
            "min_required": MIN_TUTORS_REQUIRED,
            "tutor_names": [t["name"] for t in tutors],
        }), 200

    result, uncovered = solve_schedule(tutors)

    if result is None:
        return jsonify({"error": "No feasible schedule found with current availability/settings."}), 400

    grid = result_to_grid(result)
    uncovered_labels = [f"{d} {s}" for d, s in uncovered] if uncovered else []

    return jsonify({
        "days": DAYS,
        "grid": grid,
        "tutor_count": len(tutors),
        "tutor_names": [t["name"] for t in tutors],
        "uncovered": uncovered_labels,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
