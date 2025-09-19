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

config = load_config()
n8n_config = config['N8N']
zabbix_config = config['ZABBIX']

def zabbix_api_request(method, params):
    headers = {
        'Authorization': f'Bearer {zabbix_config['AUTH_TOKEN']}',
        'Content-Type': 'application/json'
    }
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1 # ID da requisição
    }
    url = zabbix_config['API_URL']
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

def zabbix_create_item(workflow_id, workflow_name, item, valor):
    """Cria ou atualiza um item no Zabbix."""
    url = zabbix_config['API_URL']
    host_interface_id = zabbix_config['HOST_INTERFACE_ID']
    host_id = zabbix_config['HOST_ID']
    timezone_offset_hours = int(zabbix_config['TIMEZONE_OFFSET_HOURS'])

    item_name = f"{workflow_name} - {item}"
    item_key = f"{workflow_id}.{item}"

    # Converte o horário UTC para GMT-3 e ajusta o tipo de informação
    if item in ["createdAt", "Update"]:
        try:
            dt_utc = datetime.strptime(valor.split('.')[0], '%Y-%m-%d %H:%M:%S')
            dt_gmt3 = dt_utc.replace(tzinfo=timezone.utc) + timedelta(hours=timezone_offset_hours)
            formatted_value = dt_gmt3.strftime('%Y-%m-%d %H:%M:%S')
            value_type = 4 # Tipo de dado: Texto
        except (ValueError, TypeError):
            print(f"Aviso: Não foi possível converter a data '{valor}' para GMT-3. Usando valor original.", file=sys.stderr)
            formatted_value = valor
            value_type = 4
    elif item == "Status":
        formatted_value = int(valor)
        value_type = 3 # Tipo de dado: Numérico (unsigned)
    else:
        formatted_value = valor
        value_type = 4 # Tipo de dado: Texto

    params = {
        "name": item_name,
        "key": item_key,
        "type": 3, # Zabbix Agent (passive) para que o Zabbix colete o valor
        "value_type": value_type,
        "interfaceid": host_interface_id,
        "hostid": host_id,
        "delay": COLLECTION_INTERVAL_SECONDS,
        "enabled": 1,
        "history": 90,
        "trends": 400,
        "status": 0,
        "delta": 0,
        "params": ""
    }

    # Verifica se o item já existe
    existing_items = zabbix_api_request("item.get", {
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
def get_workflows_from_db():
    """Busca todos os workflows ativos do banco de dados SQLite."""
    workflows_data = []
    db_path = n8n_config['DB_PATH']
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, active, updatedAt
            FROM workflow_entity
            WHERE active = 1
        """)
        rows = cursor.fetchall()
        for row in rows:
            workflows_data.append({
                'id': row[0],
                'name': row[1],
                'active': row[2],
                'updatedAt': row[3]
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
    workflows = get_workflows_from_db()

    if not workflows:
        print("Nenhum workflow encontrado no banco de dados ou erro ao acessá-lo.", file=sys.stderr)
        return

    for wf in workflows:
        print(wf)
        workflow_id = wf['id']
        workflow_name = wf['name'] if wf['name'] else f"Workflow_{workflow_id}"

        # Cria ou atualiza o item 'Status'
        if wf['active'] == 1:
            create_zabbix_item(workflow_id, workflow_name, "Status", wf['active'])

        #
        # # Cria ou atualiza o item 'createdAt'
        # create_zabbix_item(config, zabbix_headers, workflow_id, workflow_name, "createdAt", wf['createdAt'])
        #
        # # Cria ou atualiza o item 'updatedAt'
        # create_zabbix_item(config, zabbix_headers, workflow_id, workflow_name, "updatedAt", wf['updatedAt'])

if __name__ == "__main__":
    main()
































