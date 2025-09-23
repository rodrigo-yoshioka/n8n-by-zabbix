#!/opt/n8n-by-zabbix/venv/bin/python3

import psycopg2
import sys
import configparser
from datetime import timezone, timedelta

# --- Constantes de Configuração ---
CONFIG_FILE = '/etc/zabbix/n8n_monitor.conf'
TIMEZONE_OFFSET_HOURS = -3

def load_config():
    """Carrega as configurações do arquivo.conf."""
    config = configparser.ConfigParser()
    if not config.read(CONFIG_FILE):
        print(f"Erro: Arquivo de configuração não encontrado em {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    return config

def get_db_connection(n8n_config):
    """ Cria e retorna uma conexão com o banco de dados PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=n8n_config['DB_POSTGRESDB_HOST'],
            port=n8n_config['DB_POSTGRESDB_PORT'],
            database=n8n_config['DB_POSTGRESDB_DATABASE'],
            user=n8n_config['DB_POSTGRESDB_USER'],
            password=n8n_config['DB_POSTGRESDB_PASSWORD']
        )
        return conn
    except psycopg2.Error as e:
        print(f"Erro de conexão com o banco de dados PostgreSQL: {e}", file=sys.stderr)
        return None

def coleta_status(workflow_id, n8n_config):
    conn = get_db_connection(n8n_config)
    if conn is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute("""
                SELECT count(*) 
                FROM n8n."execution_entity" 
                WHERE "workflowId" = %s
                    AND "startedAt" > NOW() - INTERVAL '24 hours' 
                    AND status = 'error'
            """, (workflow_id,))
        total = cursor.fetchone()
        return total[0]
    except psycopg2.Error as e:
        print(f"Erro ao acessar o banco de dados PostgreSQL: {e}", file=sys.stderr)
        return 0
    finally:
        if conn:
            conn.close()

def coleta_update(workflow_id, n8n_config):
    """ Coleta o unixtime da última atualização do workflow."""
    conn = get_db_connection(n8n_config)
    if conn is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute("""
                SELECT "updatedAt" 
                FROM n8n.workflow_entity 
                WHERE id= %s 
                LIMIT 1
            """,(workflow_id,))
        dados = cursor.fetchone()

        if dados is None or dados[0] is None:
            return 0

        data_utc = dados[0]
        # Converte o objeto datetime (já com fuso horário) para GMT-3 e depois para unixtime
        fuso_horario_gmt3 = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))
        data_gmt3 = data_utc.astimezone(fuso_horario_gmt3)
        unix_time = int(data_gmt3.timestamp())

        return unix_time
    except psycopg2.Error as e:
        print(f"Erro ao acessar o banco de dados PostgreSQL: {e}", file=sys.stderr)
        return 0
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":

    configs = load_config()
    n8n_config = configs['N8N']

    if len(sys.argv) > 1:
        action = sys.argv[1]
        workflow = sys.argv[2]

        if action == "status":
            print(coleta_status(workflow, n8n_config))
        elif action == "update":
            print(coleta_update(workflow, n8n_config))

