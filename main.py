import os
import tempfile
import streamlit as st
import pandas as pd
import sqlite3
import sqlparse  # Added for SQL formatting
from gemini_sql import (
    create_sqlite_from_file,
    get_db_schema,
    run_sql_query,
    get_gemini_response,
    extract_table_name,
)

st.set_page_config(page_title="Lang2SQL", layout="wide")
st.markdown("""
<h1>🧠 Lang2SQL <span style='font-size: 32px;'> - Prompt in, SQL out with Gemini behind the scenes</span></h1>
""", unsafe_allow_html=True)

# Initialize session state variables
if "db_path" not in st.session_state:
    st.session_state.db_path = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "action_history" not in st.session_state:
    st.session_state.action_history = []
if "schema" not in st.session_state:
    st.session_state.schema = {}

# Cache schema loading so it doesn't reload on every rerun
@st.cache_data
def load_schema(db_path):
    conn = sqlite3.connect(db_path)
    schema = get_db_schema(conn)
    conn.close()
    return schema

# Upload data
st.subheader("📂 Upload your data file (.db, .csv, .xlsx)")
uploaded_file = st.file_uploader(
    "Upload SQLite DB, CSV, or Excel", type=["db", "csv", "xls", "xlsx"]
)

if uploaded_file:
    ext = os.path.splitext(uploaded_file.name)[1].lower()

    if st.session_state.db_path is None:
        # Create a persistent temp DB file
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        st.session_state.db_path = temp_db.name

        if ext == ".db":
            temp_db.write(uploaded_file.read())
        elif ext in [".csv", ".xls", ".xlsx"]:
            # Convert uploaded file to SQLite DB
            conn_temp, _ = create_sqlite_from_file(uploaded_file, uploaded_file.name)
            conn_temp.backup(sqlite3.connect(st.session_state.db_path))
            conn_temp.close()

    # Load schema only once and cache it
    if not st.session_state.schema:
        st.session_state.schema = load_schema(st.session_state.db_path)

    def build_prompt(schema):
        """Build prompt for Gemini based on DB schema"""
        schema_desc = "\n".join(
            [f"Table `{table}` has columns: {', '.join(cols)}." for table, cols in schema.items()]
        )
        return [
            f"""
You are an expert at writing SQL queries.

The SQL database has the following schema:

{schema_desc}

Examples:
- Delete all customers from Germany.
  DELETE FROM Customer WHERE Country = 'Germany';

- Add a new genre called Synthwave.
  INSERT INTO Genre (Name) VALUES ('Synthwave');

Only return the SQL query. Do not include ``` or the word 'sql'.
"""
        ]

    # Chat container to keep UI stable on rerun
    chat_box = st.container()

    # Display previous chat history
    with chat_box:
        for entry in st.session_state.chat_history:
            with st.chat_message("user"):
                st.markdown(entry["user"])
            with st.chat_message("assistant"):
                formatted_sql = sqlparse.format(entry["sql"], reindent=True, keyword_case='upper')
                st.markdown(f"**Generated SQL:**\n```sql\n{formatted_sql}\n```")
                if isinstance(entry["result"], pd.DataFrame):
                    st.dataframe(entry["result"])
                elif isinstance(entry["result"], str):
                    if entry["result"].startswith("✅"):
                        st.success(entry["result"])
                    elif entry["result"].startswith("❌"):
                        st.error(entry["result"])
                    else:
                        st.info(entry["result"])

    # User input for question/query
    user_prompt = st.chat_input("Ask anything about your database...")

    if user_prompt:
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            with st.spinner("Generating SQL..."):
                prompt = build_prompt(st.session_state.schema)
                sql_query = get_gemini_response(user_prompt, prompt)
                formatted_sql = sqlparse.format(sql_query, reindent=True, keyword_case='upper')
                st.markdown(f"**Generated SQL:**\n```sql\n{formatted_sql}\n```")

                with st.spinner("Executing query..."):
                    conn = sqlite3.connect(st.session_state.db_path)
                    result = run_sql_query(sql_query, conn)
                    conn.close()

                    if isinstance(result, pd.DataFrame):
                        if not result.empty:
                            st.dataframe(result)
                        else:
                            st.info("✅ Query ran successfully. No rows returned.")
                    else:
                        if result.startswith("✅"):
                            st.success(result)
                            affected_table = extract_table_name(sql_query)
                            if affected_table:
                                preview_df = run_sql_query(
                                    f"SELECT * FROM {affected_table} LIMIT 100",
                                    sqlite3.connect(st.session_state.db_path),
                                )
                                if isinstance(preview_df, pd.DataFrame) and not preview_df.empty:
                                    result = preview_df
                                    st.dataframe(result)
                                else:
                                    st.info("✅ Operation successful. No rows to preview.")

                            # Log non-SELECT actions
                            if not sql_query.strip().lower().startswith("select"):
                                action_msg = f"✅ Executed `{sql_query.split()[0].upper()}` on `{affected_table or 'unknown'}`."
                                st.session_state.action_history.append(action_msg)
                                # Clear schema cache and reload
                                load_schema.clear()
                                st.session_state.schema = load_schema(st.session_state.db_path)

                        elif result.startswith("❌"):
                            st.error(result)
                        else:
                            st.info(result)

        # Save to chat history
        st.session_state.chat_history.append({
            "user": user_prompt,
            "sql": sql_query,
            "result": result,
        })

    # Sidebar with schema, download button (icon only), and actions
    with st.sidebar:
        with st.spinner("Loading schema..."):
            col1, col2 = st.columns([10, 1])
            with col1:
                st.subheader("🗂️ Database Schema")
                if st.session_state.schema:
                    selected_table = st.selectbox(
                        "View columns in table", list(st.session_state.schema.keys())
                    )
                    st.markdown(f"**Columns in `{selected_table}`**")
                    st.write(st.session_state.schema[selected_table])
                else:
                    st.warning("⚠️ Could not extract schema.")

            with col2:
                if st.session_state.db_path and os.path.exists(st.session_state.db_path):
                    with open(st.session_state.db_path, "rb") as f:
                        db_bytes = f.read()
                    st.download_button(
                        label="💾",
                        data=db_bytes,
                        file_name="updated_database.db",
                        mime="application/x-sqlite3",
                        key="download_button",
                        use_container_width=True,
                        help="Download updated SQLite database",
                    )
                else:
                    st.info("No database loaded yet.")

        if st.session_state.action_history:
            st.markdown("---")
            st.subheader("📝 Recent Actions")
            for action in reversed(st.session_state.action_history[-10:]):
                st.write(action)

else:
    st.info("⬆️ Upload a .db, .csv, or .xlsx file to begin.")
