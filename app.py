from flask import Flask, render_template, jsonify
from flask_cors import CORS
import requests
from datetime import datetime
import threading
import time
from collections import deque
import logging
import json
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
HISTORY_FILE = 'history.json'
HISTORY_LENGTH = 20  # 20 items * 30 sec = 10 mins
UPDATE_INTERVAL = 30 # Seconds

SITES = {
    'Self-Service': 'https://apps.uillinois.edu/selfservice',
    'Canvas': 'https://canvas.illinois.edu',
    'MyIllini': 'https://myillini.illinois.edu',
    'Course Explorer': 'https://courses.illinois.edu',
    'UIUC Status': 'https://status.illinois.edu',
    'Media Space': 'https://mediaspace.illinois.edu',
    'APPS Directory': 'https://apps.uillinois.edu',
    'Illinois.edu': 'https://illinois.edu',
    'Student Affairs': 'https://studentaffairs.illinois.edu',
    'Admissions': 'https://admissions.illinois.edu',
    'University Housing': 'https://housing.illinois.edu',
    'Library': 'https://library.illinois.edu',
    'Technology Services': 'https://techservices.illinois.edu',
    'Box': 'https://uofi.box.com',
    'Webstore': 'https://webstore.illinois.edu'
}

# --- DATA PERSISTENCE ---
# We use a dictionary of lists instead of deques for JSON compatibility
status_history = {} 
current_status = {}
last_check_time = None

def load_history():
    """Load history from JSON file on startup"""
    global status_history, last_check_time, current_status
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                data = json.load(f)
                # Convert lists back to deque-like behavior (keep last 20)
                loaded_history = data.get('history', {})
                status_history = {site: list(loaded_history.get(site, []))[-HISTORY_LENGTH:] for site in SITES}
                
                # Load last known status
                current_status = data.get('current', {})
                last_check_string = data.get('last_check')
                last_check_time = datetime.fromisoformat(last_check_string) if last_check_string else None
                logger.info("Loaded history from file.")
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            status_history = {site: [] for site in SITES}
    else:
        status_history = {site: [] for site in SITES}

def save_history():
    """Save current state to JSON file"""
    try:
        data = {
            'history': status_history,
            'current': current_status,
            'last_check': last_check_time.isoformat() if last_check_time else None
        }
        with open(HISTORY_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to save history: {e}")

# Load immediately on start
load_history()

def check_website(name, url):
    try:
        start_time = time.time()
        headers = {'User-Agent': 'UIUC-Status-Monitor/1.0'}
        # Shorter timeout to prevent hanging
        response = requests.get(url, timeout=5, headers=headers)
        response_time = round((time.time() - start_time) * 1000)
        
        return {
            'status': 'up',
            'time': response_time,
            'code': response.status_code
        }
    except requests.RequestException as e:
        return {
            'status': 'down',
            'error': str(e),
            'time': 0
        }

def update_loop():
    global last_check_time
    while True:
        logger.info("Starting status check...")
        for name, url in SITES.items():
            result = check_website(name, url)
            
            # Update current status cache
            current_status[name] = result
            
            # Update history
            if name not in status_history:
                status_history[name] = []
            
            status_history[name].append(result)
            if len(status_history[name]) > HISTORY_LENGTH:
                status_history[name].pop(0)
        
        last_check_time = datetime.now()
        save_history()
        logger.info("Status check complete.")
        time.sleep(UPDATE_INTERVAL)

def calculate_uptime(name):
    history = status_history.get(name, [])
    if not history:
        return 0
    # Avoid division by zero
    if len(history) == 0:
        return 0
    up_count = sum(1 for entry in history if entry.get('status') == 'up')
    return round((up_count / len(history)) * 100)

# Start background thread
checker_thread = threading.Thread(target=update_loop, daemon=True)
checker_thread.start()

@app.route('/')
def index():
    # Construct data object similar to API response
    data = {
        'last_check': last_check_time.isoformat() if last_check_time else None,
        'sites': {
            name: {
                'current': current_status.get(name, {}),
                'history': status_history.get(name, []),
                'url': url,
                'uptime': calculate_uptime(name)
            } for name, url in SITES.items()
        }
    }
    return render_template('index.html', initial_data=data)

@app.route('/api/status')
def status():
    return jsonify({
        'last_check': last_check_time.isoformat() if last_check_time else None,
        'sites': {
            name: {
                'current': current_status.get(name, {}),
                'history': status_history.get(name, []),
                'url': url,
                'uptime': calculate_uptime(name)
            } for name, url in SITES.items()
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
