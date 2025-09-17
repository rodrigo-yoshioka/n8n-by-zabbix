#!/opt/n8n-by-zabbix/venv/bin/python3

import sqlite3
import json
import requests
import sys
import configparser
from datetime import datetime, timezone, timedelta

# --- Constantes de Configuração ---
CONFIG_FILE = '/etc/zabbix/n8n_monitor.conf'
ZABBIX_ITEM_PREFIX = "n8n.workflow."
COLLECTION_INTERVAL_SECONDS = 3600  # 1 hora

# --- Funções de Configuração e Zabbix API ---

def load_config():
    """Carrega as configurações do arquivo .conf."""
    config = configparser.ConfigParser()
    if not config.read(CONFIG_FILE):
        print(f"Erro: Arquivo de configuração não encontrado em {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    return config

def zabbix_api_request(config, method, params):
    """Envia uma requisição genérica para a API do Zabbix."""
    headers = {
        'Authorization': f'Bearer {config['ZABBIX']['AUTH_TOKEN']}',
        'Content-Type': 'application/json'
    }
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1 # ID da requisição
    }
    url = config['ZABBIX']['API_URL']
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=500.0)
        response.raise_for_status()
        result = response.json()
        if 'error' in result:
            print(f"Erro na API do Zabbix ({method}): {result['error']['message']}", file=sys.stderr)
            return None
        return result.get('result')
    except requests.exceptions.RequestException as e:
        print(f"Erro de rede ao chamar API Zabbix ({method}): {e}", file=sys.stderr)
        return None
    except KeyError:
        print(f"Erro: Resposta inesperada da API do Zabbix para {method}.", file=sys.stderr)
        return None

def create_zabbix_item(config, headers, workflow_id, workflow_name, field_name, field_value):
    """Cria ou atualiza um item no Zabbix."""
    zabbix_config = config['ZABBIX']
    zabbix_config = config['ZABBIX']
    url = zabbix_config['API_URL']
    host_interface_id = zabbix_config['HOST_INTERFACE_ID']
    host_id = zabbix_config['HOST_ID']
    timezone_offset_hours = int(zabbix_config['TIMEZONE_OFFSET_HOURS'])

    item_name = f"{workflow_name} - {field_name.capitalize()}"
    item_key = f"{ZABBIX_ITEM_PREFIX}{workflow_id}.{field_name}"

    # Converte o horário UTC para GMT-3 e ajusta o tipo de informação
    if field_name in ["createdAt", "updatedAt"]:
        try:
            dt_utc = datetime.strptime(field_value.split('.')[0], '%Y-%m-%d %H:%M:%S')
            dt_gmt3 = dt_utc.replace(tzinfo=timezone.utc) + timedelta(hours=timezone_offset_hours)
            formatted_value = dt_gmt3.strftime('%Y-%m-%d %H:%M:%S')
            value_type = 4 # Tipo de dado: Texto
        except (ValueError, TypeError):
            print(f"Aviso: Não foi possível converter a data '{field_value}' para GMT-3. Usando valor original.", file=sys.stderr)
            formatted_value = field_value
            value_type = 4
    elif field_name == "active":
        formatted_value = int(field_value)
        value_type = 3 # Tipo de dado: Numérico (unsigned)
    else:
        formatted_value = field_value
        value_type = 4 # Tipo de dado: Texto

    params = {
        "name": item_name,
        "key": item_key,
        "type": 3, # Zabbix Agent (passive) para que o Zabbix colete o valor
        "value_type": value_type,
        "interfaceid": host_interface_id,
        "hostid": host_id,
        "applications": [get_or_create_application(config, headers, url, host_id, "n8n Workflows")],
        "delay": COLLECTION_INTERVAL_SECONDS,
        "description": f"Status do workflow n8n: {workflow_name} - Campo: {field_name}",
        "enabled": 1,
        "history": 90,
        "trends": 365,
        "status": 0,
        "delta": 0,
        "params": ""
    }

    # Verifica se o item já existe
    existing_items = zabbix_api_request(url, headers, "item.get", {
        "output": ["itemid", "name", "key_"],
        "hostids": host_id,
        "filter": {"key_": item_key}
    })

    if existing_items:
        # Se o item existe, atualiza-o
        item_id = existing_items[0]['itemid']
        params["itemid"] = item_id
        update_response = zabbix_api_request(url, headers, "item.update", params)
        if update_response:
            print(f"Item atualizado: '{item_name}' (Key: {item_key})")
        else:
            print(f"Falha ao atualizar item: '{item_name}' (Key: {item_key})", file=sys.stderr)
    else:
        # Se o item não existe, cria-o
        create_response = zabbix_api_request(url, headers, "item.create", params)
        if create_response:
            print(f"Item criado: '{item_name}' (Key: {item_key})")
        else:
            print(f"Falha ao criar item: '{item_name}' (Key: {item_key})", file=sys.stderr)

def get_or_create_application(config, headers, url, host_id, app_name):
    """Obtém o ID de uma aplicação existente ou a cria."""
    applications = zabbix_api_request(url, headers, "application.get", {
        "output": ["applicationid"],
        "hostids": host_id,
        "filter": {"name": app_name}
    })

    if applications:
        return applications[0]['applicationid']
    else:
        app_params = {
            "name": app_name,
            "hostid": host_id
        }
        created_app = zabbix_api_request(url, headers, "application.create", app_params)
        if created_app:
            return created_app['applicationids'][0]
        else:
            print(f"Erro: Falha ao criar aplicação '{app_name}'", file=sys.stderr)
            return None

# --- Funções de Banco de Dados ---

def get_workflows_from_db(db_path):
    """Busca todos os workflows ativos do banco de dados SQLite."""
    workflows_data = []
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, active, createdAt, updatedAt
            FROM workflow_entity
            WHERE isArchived = 0
        """)
        rows = cursor.fetchall()
        for row in rows:
            workflows_data.append({
                'id': row[0],
                'name': row[1],
                'active': row[2],
                'createdAt': row[3],
                'updatedAt': row[4]
            })
        return workflows_data
    except sqlite3.Error as e:
        print(f"Erro ao acessar o banco de dados SQLite: {e}", file=sys.stderr)
        return []
    finally:
        if conn:
            conn.close()

# --- Lógica Principal ---

def main():
    config = load_config()
    n8n_config = config['N8N']
    zabbix_headers = get_zabbix_headers(config)

    workflows = get_workflows_from_db(n8n_config['DB_PATH'])

    if not workflows:
        print("Nenhum workflow encontrado no banco de dados ou erro ao acessá-lo.", file=sys.stderr)
        return

    for wf in workflows:
        workflow_id = wf['id']
        workflow_name = wf['name'] if wf['name'] else f"Workflow_{workflow_id}"

        # Cria ou atualiza o item 'active'
        create_zabbix_item(config, zabbix_headers, workflow_id, workflow_name, "active", wf['active'])

        # Cria ou atualiza o item 'createdAt'
        create_zabbix_item(config, zabbix_headers, workflow_id, workflow_name, "createdAt", wf['createdAt'])

        # Cria ou atualiza o item 'updatedAt'
        create_zabbix_item(config, zabbix_headers, workflow_id, workflow_name, "updatedAt", wf['updatedAt'])

if __name__ == "__main__":
    main()
































