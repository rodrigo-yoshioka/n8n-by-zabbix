#!/opt/n8n-by-zabbix/venv/bin/python3

import psycopg2
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

# Obtem o hostname
def zabbix_get_hostname(hostid):
    params = {
        "output": ["name"],
        "filter": {
            "hostid": [hostid]
        }
    }
    resultado = zabbix_api_request("host.get", params)
    return resultado[0]['name']

# Cria ou atualiza um item no zabbix
def zabbix_create_item(params):
    """Cria ou atualiza um item no Zabbix."""

    # Verifica se o item já existe
    existing_items = zabbix_api_request("item.get", {
        "output": ["itemid", "name", "key_"],
        "hostids": params['hostid'],
        "filter": {"key_": params['key_']}
    })

    if existing_items:
        # Se o item existe, atualiza-o
        item_id = existing_items[0]['itemid']
        params.pop("hostid", None)
        params["itemid"] = item_id
        update_response = zabbix_api_request("item.update", params)
        if update_response:
            print(f"Item atualizado: {update_response['itemids'][0]} - {params['name']} (Key: {params['key_']})")
            return update_response['itemids'][0]
        else:
            print(f"Falha ao atualizar item: {update_response['itemids'][0]} - {params['name']} (Key: {params['key_']})", file=sys.stderr)
            return None
    else:
        # Se o item não existe, cria-o
        print("Cria")
        create_response = zabbix_api_request("item.create", params)
        if create_response:
            print(f"Item criado: {params['name']} (Key: {params['key_']})")
            return create_response['itemids'][0]
        else:
            print(f"Falha ao criar item: {params['name']} (Key: {params['key']})", file=sys.stderr)
            return None

# Cria ou atualiza as triggers
def zabbix_create_trigger(trigger_params):
    """Cria ou atualiza uma trigger no Zabbix."""
    # Verifica se a trigger já existe
    existing_triggers = zabbix_api_request("trigger.get", {
        "output": ["triggerid", "description"],
        "filter": {"description": trigger_params['description']}
    })
    if existing_triggers:
        trigger_id = existing_triggers[0]['triggerid']
        trigger_params['triggerid'] = trigger_id
        update_response = zabbix_api_request("trigger.update", trigger_params)
        # if update_response:
        #     print(f"Trigger atualizada: '{trigger_name}'")
        return update_response
    else:
        create_response = zabbix_api_request("trigger.create", trigger_params)
        return create_response

# --- Funções de Banco de Dados ---
def get_workflows_from_db():
    """Busca todos os workflows ativos do banco de dados SQLite."""
    workflows_data = []
    conn = None
    try:
        # Extrai os dados de conexão do arquivo de configuração
        db_host = n8n_config['DB_POSTGRESDB_HOST']
        db_port = n8n_config['DB_POSTGRESDB_PORT']
        db_database = n8n_config['DB_POSTGRESDB_DATABASE']
        db_user = n8n_config['DB_POSTGRESDB_USER']
        db_password = n8n_config['DB_POSTGRESDB_PASSWORD']

        # Conecta ao banco de dados PostgreSQL
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            database=db_database,
            user=db_user,
            password=db_password
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, active, "updatedAt", "isArchived"
            FROM n8n.workflow_entity
            WHERE "isArchived" = false
        """)
        rows = cursor.fetchall()

        for row in rows:
            workflows_data.append({
                'id': row[0],
                'name': row[1],
                'active': row[2],
                'updatedAt': row[3],
                'isArchived': row[4]
            })
        return workflows_data
    except psycopg2.Error as e:
        print(f"Erro ao acessar o banco de dados PostgreSQL: {e}", file=sys.stderr)
        return []
    finally:
        if conn:
            conn.close()

# --- Lógica Principal ---
def main():
    workflows = get_workflows_from_db()
    host_id = zabbix_config['HOST_ID']
    host_interface_id = zabbix_get_interface_id(host_id)
    hostname = zabbix_get_hostname(host_id)

    if not workflows:
        print("Nenhum workflow encontrado no banco de dados ou erro ao acessá-lo.", file=sys.stderr)
        return

    for wf in workflows:
        workflow_id = wf['id']
        workflow_name = wf['name'] if wf['name'] else f"Workflow_{workflow_id}"

        # Cria ou atualiza o item 'Status'
        if wf['isArchived'] == 0:
            """Cria ou atualiza o item com o status de execucao do workflow."""
            params = {
                "name": f"Workflow - {workflow_name} - Status Execução",
                "key_": f"n8n.workflow.execution.status[{workflow_id}]",
                "type": 0,  # Zabbix Agent (passive) para que o Zabbix colete o valor
                "value_type": 3,
                "interfaceid": host_interface_id,
                "hostid": host_id,
                "delay": "60s",
                "history": "90d",
                "trends": "400d",
                "preprocessing": {"type": 5, "params": "(\\d+)\n\\1", "error_handler": 0},
                "description": "Coleta qual o status das execuções do workflow.",
                "tags": {"tag": "component", "value": "Cron"}
            }
            zabbix_create_item(params)

            trigger_params = {
                "description": f"Workflow {workflow_name} falhou",
                "expression": f"last(/{hostname}/n8n.workflow.execution.status[{workflow_id}])>0",
                "priority": 4,
                "status": 0,
                "recovery_mode": 0,
                "manual_close": 1,
                "comments": "A trigger irá ficar ativa caso haja pelo menos 1 erro de execução dentro das últimas 24h "
                            "e irá desativar automaticamente após 24h do último erro."
            }
            print(zabbix_create_trigger(trigger_params))
            ###########################################################################################################
            """Cria ou atualiza o item de status do workflow"""
            params = {
                "name": f"Workflow - {workflow_name} - Status",
                "key_": f"n8n.workflow.status[{workflow_id}]",
                "type": 0,  # Zabbix Agent (passive) para que o Zabbix colete o valor
                "value_type": 3,
                "interfaceid": host_interface_id,
                "hostid": host_id,
                "delay": "60s",
                "history": "90d",
                "trends": "400d",
                "preprocessing": {"type": 5, "params": "(\\d+)\n\\1", "error_handler": 0},
                "description": "Coleta se o workflow está ativo ou não.",
                "tags": {"tag": "component", "value": "Cron"}
            }
            zabbix_create_item(params)
            ###########################################################################################################
            """Cria ou atualiza o item de isArchived"""
            params = {
                "name": f"Workflow - {workflow_name} - Arquivado",
                "key_": f"n8n.workflow.is.archived[{workflow_id}]",
                "type": 0,  # Zabbix Agent (passive) para que o Zabbix colete o valor
                "value_type": 3,
                "interfaceid": host_interface_id,
                "hostid": host_id,
                "delay": "60s",
                "history": "90d",
                "trends": "400d",
                "preprocessing": {"type": 5, "params": "(\\d+)\n\\1", "error_handler": 0},
                "description": "Coleta se o workflow foi arquivado. Workflows arquivados significam que não devem ser mais "
                               "monitorados, desative ou exclua todos os itens deste workflow para que não haja alarmes.",
                "tags": {"tag": "component", "value": "Cron"}
            }
            zabbix_create_item(params)

            trigger_params = {
                "description": f"Workflow {workflow_name} foi Arquivado",
                "expression": f"change(/{hostname}/n8n.workflow.is.archived[{workflow_id}])<>0",
                "priority": 1,
                "status": 0,
                "recovery_mode": 2,
                "manual_close": 1,
                "comments": "Se esta trigger estiver ligada significa que o workflow foi arquivado no n8n, caso seja porque "
                            "o workflow não será mais utilizado, desative ou exclua todos os itens deste workflow. "
                            "Esta trigger não desativa sozinha, deve ser feita pelo reconhecimento do alarme."
            }
            print(zabbix_create_trigger(trigger_params))
            ###########################################################################################################
            """Cria ou atualiza o item 'updatedAt'"""
            params = {
                "name": f"Workflow - {workflow_name} - Update",
                "key_": f"n8n.workflow.update[{workflow_id}]",
                "type": 0,  # Zabbix Agent (passive) para que o Zabbix colete o valor
                "value_type": 3,
                "interfaceid": host_interface_id,
                "hostid": host_id,
                "units": "unixtime",
                "delay": "60s",
                "history": "90d",
                "trends": "400d",
                "description": "Coleta a data da última alteração do workflow.",
                "tags": {"tag": "component", "value": "Cron"}
            }
            zabbix_create_item(params)

            trigger_params = {
                "description": f"Workflow {workflow_name} foi alterado",
                "expression": f"change(/{hostname}/n8n.workflow.update[{workflow_id}])<>0",
                "priority": 1,
                "status": 0,
                "recovery_mode": 2,
                "manual_close": 1,
                "comments": "Esta trigger ativa se a data da última alteração do workflow foi alterado. É mais um aviso "
                            "para ciência de que houve alterações. Ela não desativa sozinha, sendo necessário ação manual. "
                            "Recomenda-se descrever as alterações para referência futura."
            }
            print(zabbix_create_trigger(trigger_params))

if __name__ == "__main__":
    main()
































