import os
import sqlite3
import pandas as pd
import re
import google.generativeai as genai
from dotenv import load_dotenv
import tempfile

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


def create_sqlite_from_file(file, filename):
    ext = os.path.splitext(filename)[1].lower()

    # Save to real temp DB file (not in-memory)
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    conn = sqlite3.connect(temp_db.name)

    if ext == ".csv":
        df = pd.read_csv(file)
    elif ext in [".xls", ".xlsx"]:
        df = pd.read_excel(file)
    else:
        raise ValueError("Unsupported file type")

    table_name = os.path.splitext(os.path.basename(filename))[0]
    df.to_sql(table_name, conn, index=False, if_exists="replace")
    return conn, table_name


def get_db_schema(conn):
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cur.fetchall()
        schema = {}
        for table_tuple in tables:
            table = table_tuple[0]
            cur.execute(f"PRAGMA table_info({table});")
            columns_info = cur.fetchall()
            columns = [col[1] for col in columns_info]
            schema[table] = columns
        return schema
    except Exception:
        return {}


def run_sql_query(sql, conn):
    try:
        cur = conn.cursor()
        statements = [s.strip() for s in sql.strip().split(";") if s.strip()]
        result = None
        for stmt in statements:
            cur.execute(stmt)
            if cur.description:
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                result = pd.DataFrame(rows, columns=columns)
            else:
                result = f"✅ Statement executed. Rows affected: {cur.rowcount}"
        conn.commit()
        return result
    except Exception as e:
        return f"❌ SQL Error: {e}"


def get_gemini_response(question, prompt):
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content([prompt[0], question])
    return response.text.strip()


def extract_table_name(sql_query):
    sql = sql_query.strip().lower()
    match = re.search(r"(?:from|into|update|table)\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql)
    return match.group(1) if match else None
