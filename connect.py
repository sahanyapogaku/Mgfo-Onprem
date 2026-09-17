import os
import sys
import pyodbc

def load_env(path=".env"):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def build_connection_string(env):
    encrypt = "yes" if env.get("DB_ENCRYPT", "yes").lower() == "yes" else "no"
    trust_cert = "yes" if env.get("DB_TRUST_SERVER_CERTIFICATE", "no").lower() == "yes" else "no"
    return (
        f"DRIVER={{{env['DB_DRIVER']}}};"
        f"SERVER={env['DB_SERVER']},{env.get('DB_PORT', '1433')};"
        f"DATABASE={env['DB_NAME']};"
        f"UID={env['DB_USER']};"
        f"PWD={env['DB_PASSWORD']};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_cert};"
        f"Connection Timeout=30;"
    )


def main():
    env = load_env()
    conn_str = build_connection_string(env)
    try:
        conn = pyodbc.connect(conn_str)
    except pyodbc.Error as e:
        print(f"Connection FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    cursor = conn.cursor()
    cursor.execute('SELECT @@VERSION, DB_NAME()')
    row = cursor.fetchone()
    print("Connected successfully.")
    print("SQL Server version:", row[0].split("\n")[0])
    print("Connected to database:", row[1])
    conn.close()


if __name__ == "__main__":
    main()

