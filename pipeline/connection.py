"""Azure Synapse access, reused from DataHubDevelopment rather than
reimplemented — see team_custom_modules.remote_connections.RemoteDataConn.

Locally: run `az login` first (select the production subscription).
In CI: set AZURE_CLIENT_ID / AZURE_CLIENT_SECRET / AZURE_TENANT_ID as repo
secrets; DefaultAzureCredential picks up a service-principal login from
those env vars automatically, no interactive login needed.
"""
from team_custom_modules.remote_connections import RemoteDataConn


def get_connection() -> RemoteDataConn:
    return RemoteDataConn()


def query(conn: RemoteDataConn, sql: str):
    """Thin wrapper so pipeline scripts import from here, not the vendored
    module directly, if this ever needs to change (e.g. adding retries)."""
    return conn.get_azure_sql_data(sql)
