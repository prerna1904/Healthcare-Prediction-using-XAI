from flask import Flask, g, jsonify, request, render_template
import sqlite3, os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = os.path.join(os.path.dirname(__file__), "appointments.db")
IST = ZoneInfo("Asia/Kolkata")

app = Flask(__name__, static_folder="static", template_folder="templates")

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

def close_connection(exc):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()
app.teardown_appcontext(close_connection)

def table_has_column(db, table_name, column_name):
    cur = db.execute(f"PRAGMA table_info('{table_name}')")
    cols = [r["name"] for r in cur.fetchall()]
    return column_name in cols

def ensure_tables_and_seed(db):
    # Base tables
    db.execute("""
    CREATE TABLE IF NOT EXISTS doctors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        specialty TEXT NOT NULL
    );
    """)
    db.execute("""
    CREATE TABLE IF NOT EXISTS slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doctor_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        FOREIGN KEY(doctor_id) REFERENCES doctors(id)
    );
    """)
    db.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient TEXT,
        date TEXT,
        time TEXT
    );
    """)
    db.commit()

    # ensure expected appointment columns
    if not table_has_column(db, "appointments", "doctor_id"):
        db.execute("ALTER TABLE appointments ADD COLUMN doctor_id INTEGER;")
    if not table_has_column(db, "appointments", "slot_id"):
        db.execute("ALTER TABLE appointments ADD COLUMN slot_id INTEGER;")
    if not table_has_column(db, "appointments", "emergency"):
        db.execute("ALTER TABLE appointments ADD COLUMN emergency INTEGER DEFAULT 0;")
    if not table_has_column(db, "appointments", "created_at"):
        db.execute("ALTER TABLE appointments ADD COLUMN created_at TEXT;")
    db.commit()

    # seed many doctors
    cur = db.execute("SELECT COUNT(1) as cnt FROM doctors")
    if cur.fetchone()["cnt"] == 0:
        doctors = [
            ("Dr. Mehta", "Cardiologist"),
            ("Dr. Singh", "Dermatologist"),
            ("Dr. Patel", "General Physician"),
            ("Dr. Rao", "Pediatrician"),
            ("Dr. Kapoor", "Orthopedics"),
            ("Dr. Narang", "Neurologist"),
            ("Dr. Verma", "ENT"),
            ("Dr. Reddy", "Emergency Medicine"),
            ("Dr. Bose", "Gastroenterologist"),
            ("Dr. Iyer", "Pulmonologist"),
            ("Dr. Chawla", "Oncologist"),
            ("Dr. Thomas", "Urologist"),
            ("Dr. Jain", "Psychiatrist"),
            ("Dr. Sharma", "Nephrologist")
        ]
        for name, spec in doctors:
            db.execute("INSERT INTO doctors (name, specialty) VALUES (?, ?)", (name, spec))
        db.commit()

    # seed slots for normal booking (next 3 days)
    cur = db.execute("SELECT COUNT(1) as cnt FROM slots")
    if cur.fetchone()["cnt"] == 0:
        start_date = datetime.now(IST).date()
        dates = [(start_date + timedelta(days=i)).isoformat() for i in range(0, 3)]
        times = ["09:00","10:00","11:00","12:00","13:00","14:00","15:00"]
        cur = db.execute("SELECT id FROM doctors")
        doc_ids = [row["id"] for row in cur.fetchall()]
        for d in doc_ids:
            for date in dates:
                for t in times:
                    db.execute("INSERT INTO slots (doctor_id, date, time) VALUES (?, ?, ?)", (d, date, t))
        db.commit()

with app.app_context():
    ensure_tables_and_seed(get_db())

# utilities
def slot_is_booked(slot_id):
    db = get_db()
    cur = db.execute("SELECT COUNT(1) as c FROM appointments WHERE slot_id = ?", (slot_id,))
    return cur.fetchone()["c"] > 0

def slot_has_emergency(slot_id):
    db = get_db()
    cur = db.execute("SELECT COUNT(1) as c FROM appointments WHERE slot_id = ? AND emergency = 1", (slot_id,))
    return cur.fetchone()["c"] > 0

# Doctor handling emergency within last X minutes (60)
def doctor_recent_emergency_count(doctor_id, minutes=60):
    db = get_db()
    cutoff = (datetime.now(IST) - timedelta(minutes=minutes)).isoformat()
    cur = db.execute("SELECT COUNT(1) as c FROM appointments WHERE doctor_id = ? AND emergency = 1 AND created_at >= ?", (doctor_id, cutoff))
    return cur.fetchone()["c"]

def doctor_handling_emergency_flag(doctor_id, minutes=60):
    return doctor_recent_emergency_count(doctor_id, minutes) > 0

# pick doctor for emergency: prefer ones with lowest recent emergency count (IST-aware)
def pick_doctor_for_emergency(preferred_doctor_id=None):
    db = get_db()
    if preferred_doctor_id:
        cur = db.execute("SELECT * FROM doctors WHERE id = ?", (preferred_doctor_id,))
        if cur.fetchone():
            return preferred_doctor_id
    cutoff = (datetime.now(IST) - timedelta(minutes=60)).isoformat()
    cur = db.execute("""
        SELECT d.id,
               COALESCE( (SELECT COUNT(1) FROM appointments a WHERE a.doctor_id = d.id AND a.emergency = 1 AND a.created_at >= ?), 0) AS recent_em_count
        FROM doctors d
        ORDER BY recent_em_count ASC, d.id ASC
        LIMIT 1
    """, (cutoff,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = db.execute("SELECT id FROM doctors LIMIT 1")
    r = cur.fetchone()
    return r["id"] if r else None

# convert created_at string in DB (iso) to IST iso format
def to_ist_iso(ts_str):
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            # assume UTC if no tz
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(IST).isoformat()
    except Exception:
        return ts_str

# Routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/doctors", methods=["GET"])
def api_doctors():
    db = get_db()
    cur = db.execute("SELECT * FROM doctors ORDER BY specialty, name")
    docs = []
    for r in cur.fetchall():
        did = r["id"]
        docs.append({
            "id": did,
            "name": r["name"],
            "specialty": r["specialty"],
            "handling_emergency": doctor_handling_emergency_flag(did, minutes=60)
        })
    return jsonify(docs)

@app.route("/api/slots/<int:doctor_id>", methods=["GET"])
def api_slots_for_doctor(doctor_id):
    db = get_db()
    cur = db.execute("SELECT s.id as slot_id, s.date, s.time FROM slots s WHERE s.doctor_id = ? ORDER BY s.date, s.time", (doctor_id,))
    slots = []
    for r in cur.fetchall():
        slot_id = r["slot_id"]
        slots.append({
            "slot_id": slot_id,
            "date": r["date"],
            "time": r["time"],
            "booked": slot_is_booked(slot_id),
            "emergency": slot_has_emergency(slot_id)
        })
    # also add whether doctor is currently handling emergency
    doctor_em_handling = doctor_handling_emergency_flag(doctor_id, minutes=60)
    return jsonify({"doctor_handling_emergency": doctor_em_handling, "slots": slots})

@app.route("/api/appointments", methods=["GET"])
def api_list_appointments():
    db = get_db()
    cur = db.execute(
        "SELECT a.*, d.name as doctor_name, d.specialty as doctor_specialty "
        "FROM appointments a LEFT JOIN doctors d ON a.doctor_id = d.id "
        "ORDER BY COALESCE(emergency,0) DESC, datetime(created_at) DESC, date, time"
    )
    appts = []
    for r in cur.fetchall():
        created_at_ist = None
        if r["created_at"]:
            try:
                created_at_ist = datetime.fromisoformat(r["created_at"]).astimezone(IST).isoformat()
            except Exception:
                created_at_ist = r["created_at"]
        appts.append({
            "id": r["id"],
            "patient": r["patient"],
            "doctor_id": r["doctor_id"],
            "doctor_name": r["doctor_name"],
            "doctor_specialty": r["doctor_specialty"],
            "slot_id": r["slot_id"],
            "date": r["date"],
            "time": r["time"],
            "emergency": r["emergency"] or 0,
            "created_at_ist": created_at_ist
        })
    return jsonify(appts)

@app.route("/api/appointments", methods=["POST"])
def api_add_appointment():
    data = request.json or {}
    patient = (data.get("patient") or "").strip()
    doctor_id = data.get("doctor_id")              # optional
    slot_id = data.get("slot_id")                  # optional
    emergency = 1 if data.get("emergency") else 0

    if not patient:
        return jsonify({"error":"patient name required"}), 400

    db = get_db()

    if emergency:
        # choose doctor (may honor preferred)
        chosen = pick_doctor_for_emergency(preferred_doctor_id=doctor_id)
        if not chosen:
            return jsonify({"error":"No doctors available"}), 500
        now = datetime.now(IST)
        date = now.date().isoformat()
        time = now.strftime("%H:%M:%S")
        created = now.isoformat()
        cur = db.execute(
            "INSERT INTO appointments (patient, doctor_id, slot_id, date, time, emergency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (patient, chosen, None, date, time, 1, created)
        )
        db.commit()
        new_id = cur.lastrowid
        cur = db.execute("SELECT a.*, d.name as doctor_name FROM appointments a LEFT JOIN doctors d ON a.doctor_id = d.id WHERE a.id = ?", (new_id,))
        row = cur.fetchone()
        result = dict(row)
        result["created_at_ist"] = created
        result["time"] = time
        result["date"] = date
        return jsonify(result), 201

    # Normal booking: require doctor_id and slot_id
    if not doctor_id or not slot_id:
        return jsonify({"error":"For normal booking, pick a doctor and a pre-created slot."}), 400

    # verify slot belongs to doctor
    cur = db.execute("SELECT * FROM slots WHERE id = ? AND doctor_id = ?", (slot_id, doctor_id))
    if cur.fetchone() is None:
        return jsonify({"error":"Selected slot not valid for the chosen doctor."}), 400

    # reject if already booked
    cur = db.execute("SELECT COUNT(1) as c FROM appointments WHERE slot_id = ?", (slot_id,))
    if cur.fetchone()["c"] > 0:
        return jsonify({"error":"Slot already booked. First-come-first-served enforced."}), 409

    # get slot date/time
    cur = db.execute("SELECT date, time FROM slots WHERE id = ?", (slot_id,))
    r = cur.fetchone()
    date = r["date"]; time = r["time"]
    created = datetime.now(IST).isoformat()
    cur = db.execute(
        "INSERT INTO appointments (patient, doctor_id, slot_id, date, time, emergency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (patient, doctor_id, slot_id, date, time, 0, created)
    )
    db.commit()
    new_id = cur.lastrowid
    cur = db.execute("SELECT a.*, d.name as doctor_name FROM appointments a LEFT JOIN doctors d ON a.doctor_id = d.id WHERE a.id = ?", (new_id,))
    row = cur.fetchone()
    result = dict(row)
    result["created_at_ist"] = created
    return jsonify(result), 201

@app.route("/api/appointments/<int:appt_id>", methods=["DELETE"])
def api_delete_appointment(appt_id):
    db = get_db()
    cur = db.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,))
    if cur.fetchone() is None:
        return jsonify({"error":"Appointment not found"}), 404
    db.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
    db.commit()
    return jsonify({"success": True}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)
