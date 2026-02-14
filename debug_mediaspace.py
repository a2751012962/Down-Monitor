import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = 'https://mediaspace.illinois.edu'
headers = {'User-Agent': 'UIUC-Status-Monitor/1.0'}

print(f"Testing connection to {url} with verify=False...")

try:
    response = requests.get(url, timeout=10, headers=headers, verify=False)
    print(f"Status Code: {response.status_code}")
    print("Success!")
except Exception as e:
    print(f"Error: {e}")
