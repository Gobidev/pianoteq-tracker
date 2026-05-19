#!/usr/bin/env python3
import os
import glob
import re
import json
import logging
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
import mido

# Configure logging for better debug and error visibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def calc_stats_for_range(start_d, end_d, sessions):
    """
    Calculates practice statistics for a given date range.

    Args:
        start_d (datetime.date): The start date of the range (inclusive).
        end_d (datetime.date): The end date of the range (inclusive).
        sessions (list): A list of parsed session tuples:
                         (start_datetime, end_datetime, notes_count, duration_seconds, note_counts_dict)

    Returns:
        dict: A dictionary containing aggregated statistics for the range.
    """
    valid_sessions = [s for s in sessions if start_d <= s[0].date() <= end_d]
    
    total_practice = sum(s[3] for s in valid_sessions)
    max_session = max([s[3] for s in valid_sessions] + [0])
    total_notes = sum(s[2] for s in valid_sessions)
    total_sessions_count = len(valid_sessions)
    active_days = len(set(s[0].date() for s in valid_sessions))
    
    # Aggregate note hits for the heatmap
    note_counts = {i: 0 for i in range(21, 109)} # Standard 88-key piano range (A0 to C8)
    for s in valid_sessions:
        for note, count in s[4].items():
            if note in note_counts:
                note_counts[note] += count
            
    return {
        "practice_time": total_practice,
        "sessions": total_sessions_count,
        "active_days": active_days,
        "max_session": max_session,
        "total_notes": total_notes,
        "note_counts": note_counts
    }

def generate_dashboard(input_dir='.', output_file='index.html'):
    """
    Main function to parse MIDI files, calculate statistics, and generate the interactive HTML dashboard.
    """
    logging.info(f"Starting Pianoteq Tracker in '{input_dir}'...")
    
    # Regex to extract date, time, notes, and duration from Pianoteq MIDI filenames
    pattern = re.compile(r'(\d{4}-\d{2}-\d{2}) (\d{4}) \([A-Za-z]+\) (\d+) notes, (\d+) seconds\.mid')
    search_path = os.path.join(input_dir, '**', '*.mid')
    files = glob.glob(search_path, recursive=True)
    logging.info(f"Found {len(files)} MIDI files in the directory.")
    
    # Data structures to hold aggregated time distributions
    daily_practice = defaultdict(float)
    weekly_duration = defaultdict(float)
    hourly_duration = defaultdict(float)
    day_of_week_duration = defaultdict(float)
    hour_day_agg = defaultdict(float)
    
    sessions = []
    
    # ---------------------------------------------------------
    # 1. Parse all MIDI files
    # ---------------------------------------------------------
    logging.info("Parsing files and extracting MIDI data...")
    successful_files = 0
    
    for f in files:
        name = os.path.basename(f)
        match = pattern.match(name)
        if match:
            date_str = match.group(1)
            time_str = match.group(2)
            notes = int(match.group(3))
            seconds = int(match.group(4))
            
            try:
                start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H%M")
                end_dt = start_dt + timedelta(seconds=seconds)
                
                # Read MIDI file to extract specific note usage for the Heatmap
                session_note_counts = defaultdict(int)
                mid = mido.MidiFile(f)
                for msg in mid:
                    if msg.type == 'note_on' and msg.velocity > 0:
                        session_note_counts[msg.note] += 1
                        
                sessions.append((start_dt, end_dt, notes, seconds, session_note_counts))
                successful_files += 1
                
            except Exception as e:
                logging.error(f"Failed to process MIDI data for {name}: {e}")
                continue
                
    # Sort all sessions chronologically
    sessions.sort(key=lambda x: x[0])
    logging.info(f"Successfully processed {successful_files} practice sessions.")
    
    # Build raw session data for client-side chart recalculation
    logging.info("Formatting data payloads for JS frontend...")
    js_sessions = []
    for s_start, s_end, notes, seconds, counts in sessions:
        js_sessions.append({
            "start": s_start.isoformat(),
            "end": s_end.isoformat(),
            "duration": seconds,
            "notes": notes,
            "counts": dict(counts)
        })
    
    # ---------------------------------------------------------
    # 2. Generate Static HTML for the Piano Keyboard Heatmap
    # ---------------------------------------------------------
    logging.info("Generating piano keyboard HTML structure...")
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    keyboard_html = '<div class="piano-container"><div class="piano">\n'
    note = 21 # A0
    while note <= 108: # C8
        n_mod = note % 12
        name = f"{note_names[n_mod]}{(note // 12) - 1}"
        has_black = n_mod in [0, 2, 5, 7, 9] and note < 108
        
        keyboard_html += '  <div class="key-group">\n'
        keyboard_html += f'    <div id="key-{note}" class="white-key" data-note="{name}" data-hits="0"></div>\n'
        
        if has_black:
            black_note = note + 1
            black_n_mod = black_note % 12
            black_name = f"{note_names[black_n_mod]}{(black_note // 12) - 1}"
            keyboard_html += f'    <div id="key-{black_note}" class="black-key" data-note="{black_name}" data-hits="0"></div>\n'
            note += 2
        else:
            note += 1
            
        keyboard_html += '  </div>\n'
    keyboard_html += '</div></div>'
    
    # ---------------------------------------------------------
    # 3. Calculate Boundaries and Time Distributions
    # ---------------------------------------------------------
    logging.info("Calculating time distributions and generating quick stats...")
    today_d = datetime.now().date()
    week_d = today_d - timedelta(days=today_d.weekday())
    month_d = today_d.replace(day=1)
    
    # Generate stats for the top interactive toggles
    quick_stats = {
        "today": calc_stats_for_range(today_d, datetime.max.date(), sessions),
        "week": calc_stats_for_range(week_d, datetime.max.date(), sessions),
        "month": calc_stats_for_range(month_d, datetime.max.date(), sessions),
        "all": calc_stats_for_range(datetime.min.date(), datetime.max.date(), sessions)
    }

    # Generate custom stats for every single unique day and week available in the data
    # (used by the custom Date Picker dropdown)
    unique_days = set(s[0].date() for s in sessions)
    all_daily_stats = {d.strftime('%Y-%m-%d'): calc_stats_for_range(d, d, sessions) for d in unique_days}
    
    unique_weeks = set(s[0].date() - timedelta(days=s[0].date().weekday()) for s in sessions)
    all_weekly_stats = {w.strftime('%Y-%m-%d'): calc_stats_for_range(w, w + timedelta(days=6), sessions) for w in unique_weeks}
    
    # Distribute the exact duration of each session across the relevant day/hour boundaries
    # (e.g., if a session spans from 1:50 PM to 2:10 PM, split the time proportionally)
    for s_start, s_end, s_notes, s_seconds, s_counts in sessions:
        curr_time = s_start
        while curr_time < s_end:
            next_hour = (curr_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            chunk_end = min(s_end, next_hour)
            chunk_duration = (chunk_end - curr_time).total_seconds()
            
            date_str = curr_time.strftime("%Y-%m-%d")
            daily_practice[date_str] += chunk_duration
            
            week_start = curr_time - timedelta(days=curr_time.weekday())
            week_str = week_start.strftime("%Y-%m-%d")
            weekly_duration[week_str] += chunk_duration
            
            hourly_duration[curr_time.hour] += chunk_duration
            day_of_week_duration[curr_time.weekday()] += chunk_duration
            hour_day_agg[(curr_time.weekday(), curr_time.hour)] += chunk_duration
            
            curr_time = chunk_end

    # Ensure the calendar matrix covers a perfect 365-day rolling window
    if daily_practice:
        end_date = datetime.strptime(max(daily_practice.keys()), "%Y-%m-%d")
    else:
        end_date = datetime.now()
    
    start_date = end_date - timedelta(days=364)
    curr_date = start_date
    while curr_date <= end_date:
        d_str = curr_date.strftime("%Y-%m-%d")
        if d_str not in daily_practice:
            daily_practice[d_str] = 0.0
        curr_date += timedelta(days=1)
        
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
        
    # Format the data for ECharts payload injection
    logging.debug("Formatting data payloads for ECharts...")
    calendar_data = [[date, round(secs / 60, 2)] for date, secs in daily_practice.items() if start_date_str <= date <= end_date_str]
    
    punchcard_data = []
    for (weekday, hour), secs in hour_day_agg.items():
        punchcard_data.append([hour, weekday, round(secs / 60, 2)])
        
    hourly_data = [round(hourly_duration[h] / 60, 2) for h in range(24)]
    day_of_week_data = [round(day_of_week_duration[d] / 60, 2) for d in range(7)]
    
    weekly_labels = sorted(weekly_duration.keys())
    weekly_data = [round(weekly_duration[k] / 60, 2) for k in weekly_labels]
    
    # ---------------------------------------------------------
    # 4. Generate HTML Output
    # ---------------------------------------------------------
    logging.info("Constructing the HTML layout...")
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pianoteq Tracker Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <style>
        body {{ background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
        .card {{ margin-bottom: 24px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); border: none; border-radius: 0.5rem; }}
        .metric-value {{ font-size: 1.75rem; font-weight: 700; color: #1f2937; }}
        .metric-label {{ font-size: 0.875rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
        .chart-container {{ position: relative; width: 100%; }}
        .chart-lg {{ height: 400px; }}
        .chart-md {{ height: 350px; }}
        .chart-calendar {{ height: 200px; min-width: 850px; }}
        .scrollable-x {{ overflow-x: auto; overflow-y: hidden; }}
        
        /* Piano Keyboard Heatmap CSS */
        .piano-container {{ width: 100%; overflow-x: auto; padding: 10px 0; }}
        .piano {{
            position: relative;
            height: 140px;
            width: 100%;
            min-width: 850px;
            white-space: nowrap;
            font-size: 0;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
            border-radius: 4px;
            border: 2px solid #222;
            background: #222;
            padding-top: 2px;
            padding-bottom: 2px;
        }}
        .key-group {{
            display: inline-block;
            width: calc(100% / 52);
            height: 100%;
            position: relative;
        }}
        .white-key {{
            width: 100%;
            height: 100%;
            box-sizing: border-box;
            border: 1px solid #ccc;
            border-bottom: 2px solid #ccc;
            background-color: #ffffff;
            border-radius: 0 0 4px 4px;
            transition: background-color 0.5s ease, filter 0.2s;
            cursor: pointer;
        }}
        .white-key:hover {{ filter: brightness(0.85); }}
        .black-key {{
            position: absolute;
            width: 65%;
            height: 60%;
            background-color: #000000;
            right: -32.5%;
            top: 0;
            z-index: 10;
            box-sizing: border-box;
            border: 1px solid #111;
            border-radius: 0 0 3px 3px;
            box-shadow: 2px 2px 3px rgba(0,0,0,0.3);
            transition: background-color 0.5s ease, filter 0.2s;
            cursor: pointer;
        }}
        .black-key:hover {{ filter: brightness(2.5) contrast(1.2); }} 
    </style>
</head>
<body>
    <div id="piano-tooltip" style="position: fixed; display: none; background: rgba(0,0,0,0.85); color: #fff; padding: 6px 12px; border-radius: 6px; font-size: 13px; pointer-events: none; z-index: 9999; transform: translate(-50%, -100%); margin-top: -15px; white-space: nowrap; box-shadow: 0 4px 6px rgba(0,0,0,0.1);"></div>

    <div class="container py-4" style="max-width: 1400px;">
        <!-- Header & Quick Range Selector -->
        <div class="d-flex flex-column flex-md-row justify-content-between align-items-center mb-4">
            <h2 class="fw-bold text-gray-800 m-0 mb-3 mb-md-0">Piano Practice Dashboard</h2>
            <div class="d-flex flex-wrap gap-2 justify-content-center">
                <div class="btn-group shadow-sm" role="group">
                    <button id="btn-today" type="button" class="btn btn-outline-primary timeframe-btn" onclick="setQuickStats('today')">Today</button>
                    <button id="btn-week" type="button" class="btn btn-outline-primary timeframe-btn" onclick="setQuickStats('week')">This Week</button>
                    <button id="btn-month" type="button" class="btn btn-outline-primary timeframe-btn" onclick="setQuickStats('month')">This Month</button>
                    <button id="btn-all" type="button" class="btn btn-outline-primary timeframe-btn active" onclick="setQuickStats('all')">All Time</button>
                </div>
                
                <!-- Custom Date Picker with Arrow Navigation -->
                <div class="input-group shadow-sm w-auto">
                    <button class="btn btn-outline-primary" type="button" onclick="shiftDate(-1)" title="Previous">&#8592;</button>
                    <select id="custom-type" class="form-select form-select-sm" style="max-width: 90px; border-color: #0d6efd;" onchange="setCustomStats()">
                        <option value="day">Day</option>
                        <option value="week">Week</option>
                    </select>
                    <input type="date" id="custom-date" class="form-control form-control-sm" style="border-color: #0d6efd;" onchange="setCustomStats()">
                    <button class="btn btn-outline-primary" type="button" onclick="shiftDate(1)" title="Next">&#8594;</button>
                </div>
            </div>
        </div>
        
        <!-- Metrics Row -->
        <div class="row text-center mb-2">
            <div class="col-6 col-md-4 col-xl-2">
                <div class="card p-3">
                    <div class="metric-value text-success" id="val-pure-time">0m</div>
                    <div class="metric-label">Practice Time</div>
                </div>
            </div>
            <div class="col-6 col-md-4 col-xl-2">
                <div class="card p-3">
                    <div class="metric-value" id="val-sessions">0</div>
                    <div class="metric-label">Sessions</div>
                </div>
            </div>
            <div class="col-6 col-md-4 col-xl-2">
                <div class="card p-3">
                    <div class="metric-value" id="val-active-days">0</div>
                    <div class="metric-label">Active Days</div>
                </div>
            </div>
            <div class="col-6 col-md-4 col-xl-2">
                <div class="card p-3">
                    <div class="metric-value" id="val-max-block">0m</div>
                    <div class="metric-label">Longest Session</div>
                </div>
            </div>
            <div class="col-6 col-md-4 col-xl-2">
                <div class="card p-3">
                    <div class="metric-value" id="val-total-notes">0</div>
                    <div class="metric-label">Total Notes</div>
                </div>
            </div>
            <div class="col-6 col-md-4 col-xl-2">
                <div class="card p-3">
                    <div class="metric-value" id="val-avg-session">0m</div>
                    <div class="metric-label">Avg Session</div>
                </div>
            </div>
        </div>
        
        <!-- Piano Heatmap Row -->
        <div class="row">
            <div class="col-12">
                <div class="card p-4 border-top border-danger border-4">
                    <h5 class="card-title fw-bold text-secondary mb-3">88-Key Piano Usage Heatmap (Hover keys for info)</h5>
                    {keyboard_html}
                </div>
            </div>
        </div>

        <!-- Dynamic Charts Row 1 -->
        <div class="row">
            <div class="col-lg-6">
                <div class="card p-4">
                    <h5 class="card-title fw-bold text-secondary mb-3">Time in a Day (Practice Time - Polar)</h5>
                    <div class="chart-container chart-md" id="timeOfDayChart"></div>
                </div>
            </div>
            <div class="col-lg-6">
                <div class="card p-4">
                    <h5 class="card-title fw-bold text-secondary mb-3">Which Day of a Week (Practice Time)</h5>
                    <div class="chart-container chart-md" id="dayOfWeekChart"></div>
                </div>
            </div>
        </div>
        
        <!-- Dynamic Charts Row 2 -->
        <div class="row">
            <div class="col-12">
                <div class="card p-4">
                    <h5 class="card-title fw-bold text-secondary mb-3">Practice Time Trend</h5>
                    <div class="chart-container chart-md" id="weeklyChart"></div>
                </div>
            </div>
        </div>

        <hr class="my-4">
        <h4 class="fw-bold text-gray-800 mb-4">All-Time Historical Heatmaps</h4>

        <!-- Static Heatmaps Rows -->
        <div class="row">
            <div class="col-12">
                <div class="card p-4 border-top border-success border-4">
                    <h5 class="card-title fw-bold text-secondary mb-3">Total Practice Time per Day (1-Year View)</h5>
                    <div class="scrollable-x">
                        <div class="chart-container chart-calendar" id="calendarChartPractice"></div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-12">
                <div class="card p-4">
                    <h5 class="card-title fw-bold text-secondary mb-0">Punchcard Heatmap (Time of Day vs Day of Week)</h5>
                    <div class="chart-container chart-md" id="punchcardChart"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Application Logic -->
    <script>
        // Inject Python data objects
        const quickStats = {json.dumps(quick_stats)};
        const allDaily = {json.dumps(all_daily_stats)};
        const allWeekly = {json.dumps(all_weekly_stats)};
        const allSessions = {json.dumps(js_sessions)};
        
        const noteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
        
        function formatTime(minutes) {{
            if (minutes === 0) return '0m';
            if (minutes >= 60) {{
                const h = Math.floor(minutes / 60);
                const m = Math.round(minutes % 60);
                return h + 'h' + (m > 0 ? ' ' + m + 'm' : '');
            }}
            return Math.round(minutes) + 'm';
        }}
        
        function getEmptyStats() {{
            return {{
                practice_time: 0, sessions: 0, active_days: 0,
                max_session: 0, total_notes: 0, note_counts: {{}}
            }};
        }}

        // Updates HTML elements with the provided statistics payload
        function renderStats(data) {{
            document.getElementById('val-pure-time').innerText = formatTime(data.practice_time / 60);
            document.getElementById('val-sessions').innerText = data.sessions;
            document.getElementById('val-active-days').innerText = data.active_days;
            document.getElementById('val-max-block').innerText = formatTime(data.max_session / 60);
            document.getElementById('val-total-notes').innerText = data.total_notes.toLocaleString();
            document.getElementById('val-avg-session').innerText = data.sessions > 0 ? formatTime(data.practice_time / 60 / data.sessions) : '0m';
            
            let maxCount = 1;
            for (let i = 21; i <= 108; i++) {{
                if ((data.note_counts[i] || 0) > maxCount) maxCount = data.note_counts[i];
            }}
            
            for (let i = 21; i <= 108; i++) {{
                let el = document.getElementById('key-' + i);
                if (!el) continue;
                
                let count = data.note_counts[i] || 0;
                let n_mod = i % 12;
                let isBlack = [1, 3, 6, 8, 10].includes(n_mod);
                
                el.setAttribute('data-hits', count.toLocaleString());
                
                if (count === 0) {{
                    el.style.backgroundColor = isBlack ? "#000000" : "#ffffff";
                }} else {{
                    let mathA = Math.sqrt(count / maxCount);
                    if (isBlack) {{
                        let r = Math.max(60, Math.floor(255 * mathA));
                        el.style.backgroundColor = `rgb(${{r}}, 0, 0)`;
                    }} else {{
                        let gb = Math.floor(255 * (1 - mathA));
                        el.style.backgroundColor = `rgb(255, ${{gb}}, ${{gb}})`;
                    }}
                }}
            }}
        }}

        // Recalculate dynamic charts from filtered session data
        function updateCharts(filtered) {{
            let hourly = new Array(24).fill(0);
            let dayOfWeek = new Array(7).fill(0);
            let weekly = {{}};
            
            filtered.forEach(s => {{
                let curr = new Date(s.start);
                let end = new Date(s.end);
                while (curr < end) {{
                    let nextH = new Date(curr);
                    nextH.setHours(curr.getHours() + 1, 0, 0, 0);
                    let chunkEnd = new Date(Math.min(end, nextH));
                    let chunkSecs = (chunkEnd - curr) / 1000;
                    
                    hourly[curr.getHours()] += chunkSecs;
                    let dow = (curr.getDay() + 6) % 7;
                    dayOfWeek[dow] += chunkSecs;
                    
                    let ws = new Date(curr);
                    ws.setDate(curr.getDate() - dow);
                    let wsStr = ws.getFullYear() + '-' + String(ws.getMonth()+1).padStart(2,'0') + '-' + String(ws.getDate()).padStart(2,'0');
                    
                    if (!weekly[wsStr]) weekly[wsStr] = 0;
                    weekly[wsStr] += chunkSecs;
                    curr = chunkEnd;
                }}
            }});
            
            timeOfDayChart.setOption({{ series: [{{ data: hourly.map(s => Math.round(s/60)) }}] }});
            dayOfWeekChart.setOption({{ series: [{{ data: dayOfWeek.map(s => Math.round(s/60)) }}] }});
            
            let sortedWeeks = Object.keys(weekly).sort();
            weeklyChart.setOption({{
                xAxis: {{ data: sortedWeeks }},
                series: [{{ data: sortedWeeks.map(w => Math.round(weekly[w]/60)) }}]
            }});
        }}

        // Handlers for the "Today", "This Week", etc. quick buttons
        function setQuickStats(tf) {{
            document.querySelectorAll('.timeframe-btn').forEach(b => {{
                b.classList.remove('active', 'btn-primary');
                b.classList.add('btn-outline-primary');
            }});
            const btn = document.getElementById('btn-' + tf);
            if(btn) {{
                btn.classList.remove('btn-outline-primary');
                btn.classList.add('active', 'btn-primary');
            }}
            document.getElementById('custom-date').value = '';
            
            renderStats(quickStats[tf]);
            
            let now = new Date();
            let startD, endD;
            
            if (tf === 'today') {{
                startD = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                endD = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
            }} else if (tf === 'week') {{
                let day = now.getDay();
                let diff = now.getDate() - day + (day === 0 ? -6 : 1);
                startD = new Date(now.getFullYear(), now.getMonth(), diff);
                endD = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
            }} else if (tf === 'month') {{
                startD = new Date(now.getFullYear(), now.getMonth(), 1);
                endD = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
            }} else {{
                startD = new Date(0);
                endD = new Date(8640000000000000);
            }}
            
            let filtered = allSessions.filter(s => {{
                let d = new Date(s.start);
                return d >= startD && d <= endD;
            }});
            updateCharts(filtered);
        }}

        // Handler for custom date picker selections
        function setCustomStats() {{
            const dateVal = document.getElementById('custom-date').value;
            if (!dateVal) return;

            document.querySelectorAll('.timeframe-btn').forEach(b => {{
                b.classList.remove('active', 'btn-primary');
                b.classList.add('btn-outline-primary');
            }});

            const type = document.getElementById('custom-type').value;
            let data;
            let startD, endD;
            
            if (type === 'day') {{
                data = allDaily[dateVal] || getEmptyStats();
                startD = new Date(dateVal + 'T00:00:00Z');
                endD = new Date(dateVal + 'T23:59:59Z');
            }} else {{
                let d = new Date(dateVal + 'T00:00:00Z');
                let day = d.getUTCDay();
                let diff = d.getUTCDate() - day + (day === 0 ? -6 : 1);
                let monday = new Date(d.setUTCDate(diff));
                let mondayStr = monday.toISOString().split('T')[0];
                data = allWeekly[mondayStr] || getEmptyStats();
                startD = new Date(mondayStr + 'T00:00:00Z');
                endD = new Date(mondayStr + 'T23:59:59Z');
                endD.setUTCDate(endD.getUTCDate() + 6);
            }}
            renderStats(data);
            
            let filtered = allSessions.filter(s => {{
                let d = new Date(s.start);
                return d >= startD && d <= endD;
            }});
            updateCharts(filtered);
        }}

        // Helper function triggered by the Arrow (< / >) buttons
        function shiftDate(direction) {{
            const dateInput = document.getElementById('custom-date');
            
            if (!dateInput.value) {{
                dateInput.value = new Date().toISOString().split('T')[0];
            }} else {{
                const type = document.getElementById('custom-type').value;
                let d = new Date(dateInput.value + 'T00:00:00Z'); 
                
                if (type === 'day') {{
                    d.setUTCDate(d.getUTCDate() + direction);
                }} else {{
                    d.setUTCDate(d.getUTCDate() + (direction * 7));
                }}
                dateInput.value = d.toISOString().split('T')[0];
            }}
            
            setCustomStats();
        }}

        // --- Tooltip Logic for Piano Heatmap ---
        const tooltip = document.getElementById('piano-tooltip');
        document.querySelectorAll('.white-key, .black-key').forEach(key => {{
            key.addEventListener('mouseenter', (e) => {{
                const noteName = key.getAttribute('data-note');
                const hits = key.getAttribute('data-hits');
                tooltip.innerHTML = '<strong>' + noteName + '</strong>: ' + hits + ' hits';
                tooltip.style.display = 'block';
            }});
            key.addEventListener('mousemove', (e) => {{
                tooltip.style.left = e.clientX + 'px';
                tooltip.style.top = e.clientY + 'px';
            }});
            key.addEventListener('mouseleave', () => {{
                tooltip.style.display = 'none';
            }});
        }});

        // --- Initialize ECharts Instances (Dynamic Charts) ---
        const hours = ['12am', '1am', '2am', '3am', '4am', '5am', '6am', '7am', '8am', '9am', '10am', '11am', '12pm', '1pm', '2pm', '3pm', '4pm', '5pm', '6pm', '7pm', '8pm', '9pm', '10pm', '11pm'];
        const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

        const timeOfDayChart = echarts.init(document.getElementById('timeOfDayChart'));
        timeOfDayChart.setOption({{
            tooltip: {{ trigger: 'item', formatter: p => p.name + '<br/>' + formatTime(p.value) }},
            polar: {{ radius: ['15%', '80%'] }},
            angleAxis: {{ type: 'category', data: hours, startAngle: 90, clockwise: false, boundaryGap: false, splitLine: {{ show: true, lineStyle: {{ color: '#e5e7eb', type: 'dashed' }} }}, axisLabel: {{ fontSize: 10, color: '#6b7280' }} }},
            radiusAxis: {{ min: 0, axisLine: {{ show: false }}, axisLabel: {{ show: false }}, splitLine: {{ show: false }} }},
            series: [{{ type: 'bar', coordinateSystem: 'polar', name: 'Practice Time', itemStyle: {{ color: '#6366f1' }} }}]
        }});

        const dayOfWeekChart = echarts.init(document.getElementById('dayOfWeekChart'));
        dayOfWeekChart.setOption({{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }}, formatter: p => p[0].name + '<br/>' + formatTime(p[0].value) }},
            grid: {{ left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true }},
            xAxis: {{ type: 'category', data: days, axisTick: {{ alignWithLabel: true }} }},
            yAxis: {{ type: 'value', name: 'Practice Time', axisLabel: {{ formatter: val => formatTime(val) }} }},
            series: [{{ type: 'bar', barWidth: '60%', itemStyle: {{ color: '#10b981', borderRadius: [4, 4, 0, 0] }} }}]
        }});

        const weeklyChart = echarts.init(document.getElementById('weeklyChart'));
        weeklyChart.setOption({{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }}, formatter: p => p[0].name + '<br/>' + formatTime(p[0].value) }},
            grid: {{ left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true }},
            xAxis: {{ type: 'category', data: [] }},
            yAxis: {{ type: 'value', name: 'Practice Time', axisLabel: {{ formatter: val => formatTime(val) }} }},
            series: [{{ type: 'line', smooth: true, areaStyle: {{ color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [ {{ offset: 0, color: 'rgba(59,130,246,0.5)' }}, {{ offset: 1, color: 'rgba(59,130,246,0.1)' }} ]) }}, itemStyle: {{ color: '#3b82f6' }}, lineStyle: {{ width: 3 }} }}]
        }});

        // --- Static ECharts (All-Time Historical Views) ---
        const calDataPractice = {json.dumps(calendar_data)};
        const punchcardData = {json.dumps(punchcard_data)};
        
        const maxPunchcardVal = Math.max(...punchcardData.map(d => d[2]), 1);

        const practiceVisualMap = {{ type: 'piecewise', orient: 'horizontal', left: 'right', top: -10, pieces: [ {{value: 0, color: '#ebedf0'}}, {{min: 0.01, max: 15, color: '#a7f3d0'}}, {{min: 15.01, max: 45, color: '#34d399'}}, {{min: 45.01, max: 90, color: '#10b981'}}, {{min: 90.01, color: '#047857'}} ], show: false }};

        const calendarOptions = {{
            top: 30, left: 40, right: 20, bottom: 20, cellSize: [16, 16], range: ['{start_date_str}', '{end_date_str}'],
            itemStyle: {{ borderWidth: 3, borderColor: '#fff', color: '#ebedf0' }},
            splitLine: {{ show: false }}, yearLabel: {{ show: false }},
            dayLabel: {{ firstDay: 1, nameMap: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], color: '#768390', fontSize: 10 }},
            monthLabel: {{ nameMap: 'en', color: '#768390', fontSize: 12 }}
        }};

        const calendarChartPractice = echarts.init(document.getElementById('calendarChartPractice'));
        calendarChartPractice.setOption({{ tooltip: {{ formatter: p => p.data[0] + '<br/>' + formatTime(p.data[1]) }}, visualMap: practiceVisualMap, calendar: calendarOptions, series: [{{ type: 'heatmap', coordinateSystem: 'calendar', data: calDataPractice }}] }});

        const punchcardChart = echarts.init(document.getElementById('punchcardChart'));
        punchcardChart.setOption({{ tooltip: {{ position: 'top', formatter: p => days[p.data[1]] + ' at ' + hours[p.data[0]] + '<br/>' + formatTime(p.data[2]) }}, grid: {{ top: 20, bottom: 40, left: 80, right: 20 }}, xAxis: {{ type: 'category', data: hours, splitArea: {{ show: true }} }}, yAxis: {{ type: 'category', data: days, splitArea: {{ show: true }} }}, visualMap: {{ min: 0, max: maxPunchcardVal, calculable: true, orient: 'horizontal', left: 'center', bottom: -10, inRange: {{ color: ['#f6faaa', '#FEE08B', '#FDAE61', '#F46D43', '#D53E4F', '#9E0142'] }} }}, series: [{{ name: 'Practice Time', type: 'heatmap', data: punchcardData, label: {{ show: false }}, emphasis: {{ itemStyle: {{ shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' }} }} }}] }});

        // Initialize on load - populates all metrics, piano, and dynamic charts
        setQuickStats('all');

        window.addEventListener('resize', function() {{ 
            timeOfDayChart.resize(); 
            dayOfWeekChart.resize(); 
            weeklyChart.resize(); 
            calendarChartPractice.resize(); 
            punchcardChart.resize(); 
        }});
    </script>
</body>
</html>
"""
    try:
        with open(output_file, 'w') as f:
            f.write(html_content)
        logging.info(f"Dashboard generated successfully! Output written to '{output_file}'.")
    except Exception as e:
        logging.error(f"Failed to write output to file: {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Pianoteq Practice Tracker 🎹 - Generates a visual dashboard from MIDI files.",
        epilog="Example: python3 tracker.py -i ./my_midi_files -o ./dashboard.html"
    )
    parser.add_argument("-i", "--input", default=".", help="Input directory containing Pianoteq MIDI files (default: current directory)")
    parser.add_argument("-o", "--output", default="index.html", help="Output HTML file path (default: index.html)")
    args = parser.parse_args()
    
    generate_dashboard(args.input, args.output)