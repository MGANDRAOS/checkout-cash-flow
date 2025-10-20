import pyodbc
import pandas as pd

conn = pyodbc.connect(
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=localhost,1433;"
    "Database=SBCDB;"
    "Trusted_Connection=yes;"
)

tables = pd.read_sql("""
SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE='BASE TABLE'
ORDER BY TABLE_NAME
""", conn)

print(tables)