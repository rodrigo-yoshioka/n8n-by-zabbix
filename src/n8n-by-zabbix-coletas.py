#!/opt/n8n-by-zabbix/venv/bin/python3

import sqlite3
import sys
import configparser
from datetime import datetime, timezone, timedelta

def load_config():
    """Carrega as configurações do arquivo.conf."""
    config = configparser.ConfigParser()
    if not config.read(CONFIG_FILE):
        print(f"Erro: Arquivo de configuração não encontrado em {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    return config

def coleta_status(workflow_id, db_path):
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
                SELECT count(*) 
                FROM execution_entity 
                WHERE startedAT > DATETIME('now', '-24 hour')
                    AND workflowId = ? 
                    AND status = 'error'
                ORDER BY startedAt DESC
            """, (workflow_id,))
        total = cursor.fetchone()
        return total[0]
    except sqlite3.Error as e:
        print(f"Erro ao acessar o banco de dados SQLite: {e}", file=sys.stderr)
        return []
    finally:
        if conn:
            conn.close()

def coleta_update(workflow_id, db_path):
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
                SELECT id, name, updatedAt 
                FROM workflow_entity 
                WHERE id=? 
                LIMIT 1
            """,(workflow_id,))
        dados = cursor.fetchone()
        data = dados[2]
        dt_utc = datetime.strptime(data.split('.')[0], '%Y-%m-%d %H:%M:%S')
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        fuso_horario_gmt3 = timezone(timedelta(hours=-3))
        dt_gmt3 = dt_utc.astimezone(fuso_horario_gmt3)
        unix_time = int(dt_gmt3.timestamp())
        return unix_time
    except sqlite3.Error as e:
        print(f"Erro ao acessar o banco de dados SQLite: {e}", file=sys.stderr)
        return []
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # --- Constantes de Configuração ---
    CONFIG_FILE = '/etc/zabbix/n8n_monitor.conf'
    configs = load_config()
    n8n_config = configs['N8N']

    if len(sys.argv) > 1:
        action = sys.argv[1]
        workflow = sys.argv[2]

        if action == "status":
            print(coleta_status(workflow, n8n_config['DB_PATH']))
        elif action == "update":
            print(coleta_update(workflow, n8n_config['DB_PATH']))

