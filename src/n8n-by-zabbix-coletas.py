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

def coleta_execucao_status(workflow_id, n8n_config):
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

def coleta_workflow_status(workflow_id, n8n_config):
    conn = get_db_connection(n8n_config)
    if conn is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute("""
                SELECT "active" 
                FROM n8n."workflow_entity" 
                WHERE "id" = %s
            """, (workflow_id,))
        active = cursor.fetchone()
        if active[0] == True:
            ativo = 1
        else:
            ativo = 0

        return ativo
    except psycopg2.Error as e:
        print(f"Erro ao acessar o banco de dados PostgreSQL: {e}", file=sys.stderr)
        return 0
    finally:
        if conn:
            conn.close()

def coleta_is_archived(workflow_id, n8n_config):
    conn = get_db_connection(n8n_config)
    if conn is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute("""
                SELECT "isArchived" 
                FROM n8n."workflow_entity" 
                WHERE "id" = %s
            """, (workflow_id,))
        archived = cursor.fetchone()
        if archived[0] == True:
            arquivado = 1
        else:
            arquivado = 0
        return arquivado
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

def coleta_average_time(workflow_id, n8n_config):
    conn = get_db_connection(n8n_config)
    if conn is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute("""
                SELECT AVG(EXTRACT(EPOCH FROM ("stoppedAt" - "startedAt"))) AS media_tempo_execucao_segundos 
                FROM n8n."execution_entity" 
                WHERE "workflowId" = %s AND status IN ('success','error') AND "startedAt" > NOW() - interval '10 MINUTES'
            """, (workflow_id,))
        tempo_medio = cursor.fetchone()
        return tempo_medio[0]
    except psycopg2.Error as e:
        print(f"Erro ao acessar o banco de dados PostgreSQL: {e}", file=sys.stderr)
        return 0
    finally:
        if conn:
            conn.close()

def coleta_max_time(workflow_id, n8n_config):
    conn = get_db_connection(n8n_config)
    if conn is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute("""
                SELECT MAX(EXTRACT(EPOCH FROM ("stoppedAt" - "startedAt"))) AS max_tempo_execucao_segundos 
                FROM n8n."execution_entity" 
                WHERE "workflowId" = %s AND status IN ('success','error') AND "startedAt" > NOW() - interval '10 MINUTES' 
            """, (workflow_id,))
        tempo_maximo = cursor.fetchone()
        return tempo_maximo[0]
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

        if action == "execucao_status":
            print(coleta_execucao_status(workflow, n8n_config))
        elif action == "workflow_status":
            print(coleta_workflow_status(workflow, n8n_config))
        elif action == "is_archived":
            print(coleta_is_archived(workflow, n8n_config))
        elif action == "update":
            print(coleta_update(workflow, n8n_config))
        elif action == "average_time":
            print(coleta_average_time(workflow, n8n_config))
        elif action == "max_time":
            print(coleta_max_time(workflow, n8n_config))

