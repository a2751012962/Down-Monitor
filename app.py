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

import logging
import json
import os
import urllib3

# Suppress InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

# Global session for connection reuse
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0'
})

def check_website(name, url):
    try:
        start_time = time.time()
        
        # Increase timeout to 15 seconds & allow redirects
        # Verify=False is already set for Media Space compatibility
        response = session.get(url, timeout=15, verify=False, allow_redirects=True)
        
        response_time = round((time.time() - start_time) * 1000)
        
        # Consider 403 as potentially UP if it's just blocking bots, but ideally we want 200
        # For now, stick to standard status checks
        status = 'up' if response.status_code in [200, 301, 302] else 'down'
        
        if response.status_code == 403:
             # If 403, it might be WAF blocking. Let's mark as down but log it distinctively
             status = 'down'
             error_msg = f"403 Forbidden (WAF Block)"
             return {
                'status': status,
                'time': response_time,
                'code': response.status_code,
                'error': error_msg,
                'timestamp': datetime.now().isoformat()
            }

        return {
            'status': status,
            'time': response_time,
            'code': response.status_code,
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error checking {name}: {e}")
        return {
            'status': 'down',
            'time': 0,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
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
