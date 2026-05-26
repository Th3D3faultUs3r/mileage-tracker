import os
import csv
import json
import sqlite3
from datetime import datetime
from io import StringIO
from flask import Flask, request, jsonify, send_from_directory, make_response

app = Flask(__name__, static_folder='static')

DB_PATH = os.environ.get('DB_PATH', 'miles.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL DEFAULT 'default',
            date TEXT NOT NULL,
            platform TEXT NOT NULL,
            miles REAL NOT NULL,
            notes TEXT,
            start_time TEXT,
            end_time TEXT,
            route_points TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Migrations — add new columns to existing DB if upgrading
    for col_sql in [
        'ALTER TABLE trips ADD COLUMN user_name TEXT NOT NULL DEFAULT "default"',
        'ALTER TABLE trips ADD COLUMN route_points TEXT DEFAULT "[]"',
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass

    conn.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL DEFAULT 'default',
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/guide')
def guide():
    return send_from_directory('static', 'guide.html')

# ── Trips ──────────────────────────────────────────────────────────────────────

@app.route('/api/trips', methods=['GET'])
def get_trips():
    user = request.args.get('user', 'default')
    conn = get_db()
    trips = conn.execute(
        'SELECT * FROM trips WHERE user_name = ? ORDER BY date DESC, created_at DESC',
        (user,)
    ).fetchall()
    conn.close()
    return jsonify([dict(t) for t in trips])

@app.route('/api/trips', methods=['POST'])
def log_trip():
    data = request.get_json()
    if not all(k in data for k in ['date', 'platform', 'miles']):
        return jsonify({'error': 'Missing required fields'}), 400
    user = data.get('user', 'default')
    route_points = json.dumps(data.get('route_points', []))
    conn = get_db()
    conn.execute(
        '''INSERT INTO trips
           (user_name, date, platform, miles, notes, start_time, end_time, route_points)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (user, data['date'], data['platform'], float(data['miles']),
         data.get('notes', ''), data.get('start_time', ''), data.get('end_time', ''),
         route_points)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/trips/<int:trip_id>', methods=['DELETE'])
def delete_trip(trip_id):
    conn = get_db()
    conn.execute('DELETE FROM trips WHERE id = ?', (trip_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Expenses ───────────────────────────────────────────────────────────────────

@app.route('/api/expenses', methods=['GET'])
def get_expenses():
    user = request.args.get('user', 'default')
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM expenses WHERE user_name = ? ORDER BY date DESC, created_at DESC',
        (user,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/expenses', methods=['POST'])
def log_expense():
    data = request.get_json()
    if not all(k in data for k in ['date', 'category', 'amount']):
        return jsonify({'error': 'Missing required fields'}), 400
    user = data.get('user', 'default')
    conn = get_db()
    conn.execute(
        'INSERT INTO expenses (user_name, date, category, amount, notes) VALUES (?, ?, ?, ?, ?)',
        (user, data['date'], data['category'], float(data['amount']), data.get('notes', ''))
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/expenses/<int:expense_id>', methods=['DELETE'])
def delete_expense(expense_id):
    conn = get_db()
    conn.execute('DELETE FROM expenses WHERE id = ?', (expense_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Summary ────────────────────────────────────────────────────────────────────

@app.route('/api/summary')
def get_summary():
    user = request.args.get('user', 'default')
    year = request.args.get('year', datetime.now().year)
    month = request.args.get('month')
    conn = get_db()

    if month:
        trips = conn.execute(
            "SELECT * FROM trips WHERE user_name=? AND strftime('%Y',date)=? AND strftime('%m',date)=?",
            (user, str(year), str(month).zfill(2))
        ).fetchall()
        exps = conn.execute(
            "SELECT * FROM expenses WHERE user_name=? AND strftime('%Y',date)=? AND strftime('%m',date)=?",
            (user, str(year), str(month).zfill(2))
        ).fetchall()
    else:
        trips = conn.execute(
            "SELECT * FROM trips WHERE user_name=? AND strftime('%Y',date)=?",
            (user, str(year))
        ).fetchall()
        exps = conn.execute(
            "SELECT * FROM expenses WHERE user_name=? AND strftime('%Y',date)=?",
            (user, str(year))
        ).fetchall()
    conn.close()

    total_miles = sum(r['miles'] for r in trips)
    irs_rate = 0.70
    by_platform = {}
    for r in trips:
        by_platform[r['platform']] = by_platform.get(r['platform'], 0) + r['miles']

    total_expenses = sum(e['amount'] for e in exps)
    by_category = {}
    for e in exps:
        by_category[e['category']] = by_category.get(e['category'], 0) + e['amount']

    return jsonify({
        'total_miles': round(total_miles, 1),
        'trip_count': len(trips),
        'deduction': round(total_miles * irs_rate, 2),
        'irs_rate': irs_rate,
        'by_platform': by_platform,
        'total_expenses': round(total_expenses, 2),
        'by_category': by_category
    })

# ── Export ─────────────────────────────────────────────────────────────────────

@app.route('/api/export')
def export_csv():
    user = request.args.get('user', 'default')
    year = request.args.get('year')
    conn = get_db()

    if year:
        trips = conn.execute(
            "SELECT * FROM trips WHERE user_name=? AND strftime('%Y',date)=? ORDER BY date",
            (user, year)
        ).fetchall()
        exps = conn.execute(
            "SELECT * FROM expenses WHERE user_name=? AND strftime('%Y',date)=? ORDER BY date",
            (user, year)
        ).fetchall()
    else:
        trips = conn.execute(
            'SELECT * FROM trips WHERE user_name=? ORDER BY date', (user,)
        ).fetchall()
        exps = conn.execute(
            'SELECT * FROM expenses WHERE user_name=? ORDER BY date', (user,)
        ).fetchall()
    conn.close()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([f'Mileage & Expense Log — {user} — {year or "All Years"}'])
    writer.writerow([])
    writer.writerow(['MILEAGE'])
    writer.writerow(['Date', 'Platform', 'Miles', 'Deduction (@$0.70/mi)', 'Notes', 'Start Time', 'End Time'])
    for r in trips:
        writer.writerow([r['date'], r['platform'], r['miles'],
                         f'${round(r["miles"]*0.70,2)}',
                         r['notes'], r['start_time'], r['end_time']])
    total_miles = sum(r['miles'] for r in trips)
    writer.writerow([])
    writer.writerow(['TOTAL MILES', '', round(total_miles,1), f'${round(total_miles*0.70,2)}'])

    writer.writerow([])
    writer.writerow(['EXPENSES'])
    writer.writerow(['Date', 'Category', 'Amount', 'Notes'])
    for e in exps:
        writer.writerow([e['date'], e['category'], f'${e["amount"]}', e['notes']])
    total_exp = sum(e['amount'] for e in exps)
    writer.writerow([])
    writer.writerow(['TOTAL EXPENSES', '', f'${round(total_exp,2)}'])

    response = make_response(output.getvalue())
    fname = f'mileage_{user}_{year or "all"}.csv'
    response.headers['Content-Disposition'] = f'attachment; filename={fname}'
    response.headers['Content-Type'] = 'text/csv'
    return response

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
