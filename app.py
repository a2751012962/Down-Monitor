from flask import Flask, render_template, jsonify
import requests
from datetime import datetime
import threading
import time
from collections import deque

app = Flask(__name__)

# UIUC websites to monitor
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

# Store status history (last 100 checks per site)
status_history = {site: deque(maxlen=100) for site in SITES}
current_status = {}
last_check_time = None

def check_website(name, url):
    """Check if a website is up and return status info"""
    try:
        start_time = time.time()
        response = requests.get(url, timeout=5, allow_redirects=True)
        response_time = round((time.time() - start_time) * 1000, 2)  # ms
        
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
            'status_code': None,
            'response_time': None,
            'error': 'Timeout',
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        return {
            'name': name,
            'url': url,
            'status': 'down',
            'status_code': None,
            'response_time': None,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }

def monitor_sites():
    """Background thread to monitor sites every 60 seconds"""
    global current_status, last_check_time
    
    while True:
        print(f"Checking sites at {datetime.now()}")
        for name, url in SITES.items():
            result = check_website(name, url)
            current_status[name] = result
            status_history[name].append(result)
        
        last_check_time = datetime.now()
        time.sleep(60)  # Check every 60 seconds

@app.route('/')
def index():
    """Main page showing current status"""
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """API endpoint to get current status of all sites"""
    uptime_stats = {}
    
    for site in SITES:
        history = list(status_history[site])
        if history:
            up_count = sum(1 for h in history if h['status'] == 'up')
            uptime_percentage = round((up_count / len(history)) * 100, 2)
            uptime_stats[site] = uptime_percentage
        else:
            uptime_stats[site] = 100
    
    return jsonify({
        'sites': current_status,
        'last_check': last_check_time.isoformat() if last_check_time else None,
        'uptime_stats': uptime_stats
    })

@app.route('/api/history/<site_name>')
def get_history(site_name):
    """Get historical data for a specific site"""
    if site_name in status_history:
        return jsonify({
            'site': site_name,
            'history': list(status_history[site_name])
        })
    return jsonify({'error': 'Site not found'}), 404

if __name__ == '__main__':
    # Start monitoring thread
    monitor_thread = threading.Thread(target=monitor_sites, daemon=True)
    monitor_thread.start()
    
    # Give it a second to get initial data
    time.sleep(2)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
