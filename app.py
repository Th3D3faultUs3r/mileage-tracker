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
            date TEXT NOT NULL,
            platform TEXT NOT NULL,
            miles REAL NOT NULL,
            notes TEXT,
            start_time TEXT,
            end_time TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/trips', methods=['GET'])
def get_trips():
    conn = get_db()
    trips = conn.execute(
        'SELECT * FROM trips ORDER BY date DESC, created_at DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(t) for t in trips])

@app.route('/api/trips', methods=['POST'])
def log_trip():
    data = request.get_json()
    required = ['date', 'platform', 'miles']
    if not all(k in data for k in required):
        return jsonify({'error': 'Missing required fields'}), 400

    conn = get_db()
    conn.execute(
        'INSERT INTO trips (date, platform, miles, notes, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)',
        (data['date'], data['platform'], float(data['miles']),
         data.get('notes', ''), data.get('start_time', ''), data.get('end_time', ''))
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

@app.route('/api/summary')
def get_summary():
    year = request.args.get('year', datetime.now().year)
    month = request.args.get('month')
    conn = get_db()

    if month:
        rows = conn.execute(
            "SELECT * FROM trips WHERE strftime('%Y', date) = ? AND strftime('%m', date) = ?",
            (str(year), str(month).zfill(2))
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trips WHERE strftime('%Y', date) = ?",
            (str(year),)
        ).fetchall()

    conn.close()

    total_miles = sum(r['miles'] for r in rows)
    irs_rate = 0.70  # 2025 IRS standard mileage rate
    deduction = total_miles * irs_rate

    by_platform = {}
    for r in rows:
        p = r['platform']
        by_platform[p] = by_platform.get(p, 0) + r['miles']

    return jsonify({
        'total_miles': round(total_miles, 1),
        'trip_count': len(rows),
        'deduction': round(deduction, 2),
        'irs_rate': irs_rate,
        'by_platform': by_platform
    })

@app.route('/api/export')
def export_csv():
    year = request.args.get('year')
    conn = get_db()

    if year:
        rows = conn.execute(
            "SELECT * FROM trips WHERE strftime('%Y', date) = ? ORDER BY date",
            (year,)
        ).fetchall()
    else:
        rows = conn.execute('SELECT * FROM trips ORDER BY date').fetchall()

    conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Platform', 'Miles', 'Notes', 'Start Time', 'End Time'])
    for r in rows:
        writer.writerow([r['date'], r['platform'], r['miles'],
                        r['notes'], r['start_time'], r['end_time']])

    total = sum(r['miles'] for r in rows)
    writer.writerow([])
    writer.writerow(['TOTAL', '', round(total, 1), '', '', ''])
    writer.writerow(['TAX DEDUCTION @ $0.70/mi', '', f'${round(total * 0.70, 2)}', '', '', ''])

    response = make_response(output.getvalue())
    filename = f'mileage_{year or "all"}.csv'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    return response

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
