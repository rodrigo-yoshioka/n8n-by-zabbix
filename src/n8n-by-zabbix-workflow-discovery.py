#!/opt/n8n-by-zabbix/venv/bin/python3

import sqlite3
import requests
import sys
import configparser

# --- Constantes de Configuração ---
CONFIG_FILE = '/etc/zabbix/n8n_monitor.conf'
ZABBIX_ITEM_PREFIX = "n8n.workflow."
COLLECTION_INTERVAL_SECONDS = 3600  # 1 hora

# --- Funções de Configuração e Zabbix API ---
def load_config():
    """Carrega as configurações do arquivo.conf."""
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
        "id": 1 # ID da requisicao
    }
    url = zabbix_config['API_URL']
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=500.0)
        response.raise_for_status()
        result = response.json()
        if 'error' in result:
            print(f"Erro na API do Zabbix ({method}): {result['error']['data']}", file=sys.stderr)
            return None
        return result.get('result')
    except requests.exceptions.RequestException as e:
        print(f"Erro de rede ao chamar API Zabbix ({method}): {e}", file=sys.stderr)
        return None
    except KeyError:
        print(f"Erro: Resposta inesperada da API do Zabbix para {method}.", file=sys.stderr)
        return None

# Obtem a interfaceid associada ao host
def zabbix_get_interface_id(hostid):
    params = {"hostids": hostid}
    response = zabbix_api_request("hostinterface.get", params)
    if len(response) > 0:
        return response[0]["interfaceid"]
    else:
        raise Exception(f"Interface nao encontrada para o host ID '{hostid}'.")

def zabbix_create_item(workflow_id, workflow_name, item):
    """Cria ou atualiza um item no Zabbix."""
    host_id = zabbix_config['HOST_ID']
    host_interface_id = zabbix_get_interface_id(host_id)

    if item == "Status":
        item_name = f"Workflow - {workflow_name} - {item}"
        item_key = f"n8n.workflow.status[{workflow_id}]"
        value_type = 3 # Tipo de dado: Numérico (unsigned)
        tags = {"tag":"component","value":"Cron"}
    elif item == "Update":
        item_name = f"Workflow - {workflow_name} - {item}"
        item_key = f"n8n.workflow.update[{workflow_id}]"
        value_type = 3  # Tipo de dado: Numérico (unsigned)
        tags = {"tag": "component", "value": "Cron"}

    params = {
        "name": item_name,
        "key_": item_key,
        "type": 0, # Zabbix Agent (passive) para que o Zabbix colete o valor
        "value_type": value_type,
        "interfaceid": host_interface_id,
        "hostid": host_id,
        "delay": "60s",
        "history": "90d",
        "trends": "400d",
        "tags": tags
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
        params.pop("hostid", None)
        params["itemid"] = item_id
        update_response = zabbix_api_request("item.update", params)
        if update_response:
            print(f"Item atualizado: '{item_name}' (Key: {item_key})")
        else:
            print(f"Falha ao atualizar item: '{item_name}' (Key: {item_key})", file=sys.stderr)
    else:
        # Se o item não existe, cria-o
        create_response = zabbix_api_request("item.create", params)
        if create_response:
            print(f"Item criado: '{item_name}' (Key: {item_key})")
        else:
            print(f"Falha ao criar item: '{item_name}' (Key: {item_key})", file=sys.stderr)

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
        workflow_id = wf['id']
        workflow_name = wf['name'] if wf['name'] else f"Workflow_{workflow_id}"

        # Cria ou atualiza o item 'Status'
        if wf['active'] == 1:
            """Cria ou atualiza o item com o status do job"""
            zabbix_create_item(workflow_id, workflow_name, "Status")

            """Cria ou atualiza o item 'updatedAt'"""
            zabbix_create_item(workflow_id, workflow_name, "Update")

if __name__ == "__main__":
    main()
































