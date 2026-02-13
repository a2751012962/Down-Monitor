from flask import Flask, render_template, jsonify
from flask_cors import CORS
import requests
from datetime import datetime
import threading
import time
from collections import deque
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

SITES = {
    'Self-Service': 'https://apps.uillinois.edu/selfservice',
    'Canvas': 'https://canvas.illinois.edu',
    'UIUC Mail': 'https://mail.illinois.edu',
    'MyIllini': 'https://myillini.illinois.edu',
    'NetFiles': 'https://netfiles.illinois.edu',
    'Enterprise': 'https://www.enterprise.illinois.edu',
    'Course Explorer': 'https://courses.illinois.edu',
    'UIUC Status': 'https://status.illinois.edu'
}

status_history = {site: deque(maxlen=100) for site in SITES}
current_status = {}
last_check_time = None

def check_website(name, url):
    try:
        start_time = time.time()
        # User-Agent header is important! Some sites block requests without it.
        headers = {'User-Agent': 'UIUC-Status-Monitor/1.0'}
        response = requests.get(url, timeout=10, allow_redirects=True, headers=headers)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        is_up = response.status_code == 200
        return {
            'name': name,
            'url': url,
            'status': 'up' if is_up else 'down',
            'status_code': response.status_code,
            'response_time': response_time,
            'timestamp': datetime.now().isoformat()
        }
    except requests.exceptions.Timeout:
        return {
            'name': name,
            'url': url,
            'status': 'down',
            'error': 'Timeout',
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error checking {name}: {e}")
        return {
            'name': name,
            'url': url,
            'status': 'down',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }

def monitor_loop():
    global last_check_time
    logger.info("Monitor thread started")
    while True:
        try:
            logger.info("Checking all sites...")
            for name, url in SITES.items():
                result = check_website(name, url)
                current_status[name] = result
                status_history[name].append(result)
            
            last_check_time = datetime.now()
            logger.info(f"Check complete at {last_check_time}")
            
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
        
        time.sleep(60)

# Start monitoring in a background thread
monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

@app.route('/')
def index():
    # Calculate stats exactly like in get_status
    uptime_stats = {}
    for site in SITES:
        history = list(status_history[site])
        if history:
            up_count = sum(1 for h in history if h['status'] == 'up')
            uptime_percentage = round((up_count / len(history)) * 100, 2)
            uptime_stats[site] = uptime_percentage
        else:
            uptime_stats[site] = 0

    # Create the data object
    initial_data = {
        'sites': current_status,
        'last_check': last_check_time.isoformat() if last_check_time else None,
        'uptime_stats': uptime_stats
    }
    
    # Pass it to the template
    return render_template('index.html', initial_data=initial_data)


@app.route('/api/status')
def get_status():
    uptime_stats = {}
    
    # Calculate uptime stats
    for site in SITES:
        history = list(status_history[site])
        if history:
            up_count = sum(1 for h in history if h['status'] == 'up')
            uptime_percentage = round((up_count / len(history)) * 100, 2)
            uptime_stats[site] = uptime_percentage
        else:
            uptime_stats[site] = 0 # Default to 0 if no history
            
    return jsonify({
        'sites': current_status,
        'last_check': last_check_time.isoformat() if last_check_time else None,
        'uptime_stats': uptime_stats
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
