#!/opt/n8n-by-zabbix/venv/bin/python3

import os
import json
import requests
import sys
import configparser

N8N_URL = 'http://localhost:5678'
CREDENTIALS_FILE = '/etc/zabbix/.n8n_api_creds'


def load_credentials():
    config = configparser.ConfigParser()
    try:
        config.read(CREDENTIALS_FILE)
        return {
            'API_KEY_LABEL': config.get('API', 'N8N_API_KEY_LABEL'),
            'API_KEY_SECRET': config.get('API', 'N8N_API_KEY_SECRET')
        }
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        print(f"Error reading credentials file {CREDENTIALS_FILE}: {e}", file=sys.stderr)
        return None


def discover_workflows():
    creds = load_credentials()
    if not creds:
        print("Error: API credentials not loaded or incomplete.", file=sys.stderr)
        return []

    headers = {
        #'X-N8N-API-KEY-ID': creds['API_KEY_LABEL'],
        'accept': 'application/json',
        'X-N8N-API-KEY': creds['API_KEY_SECRET']
    }
    url = f"{N8N_URL}/api/v1/workflows?active=true"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        workflows = response.json()

        zabbix_data = []
        for wf in workflows['data']:
            zabbix_data.append({
                "{#WORKFLOW_ID}": wf['id'],
                "{#WORKFLOW_NAME}": wf['name']
            })
        return zabbix_data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching n8n workflows: {e}", file=sys.stderr)
        return []


if __name__ == "__main__":
    discovery_result = discover_workflows()
    print(json.dumps(discovery_result, indent=4))