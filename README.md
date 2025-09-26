# n8n-by-zabbix


CREATE DATABASE n8n-db;
CREATE USER n8n-user WITH PASSWORD 'random-password';
GRANT ALL PRIVILEGES ON DATABASE n8n-db TO n8n-user;

Criar diretório /opt/n8n-by-zabbix/

Criar o ambiente virtual do python na subpasta venv.