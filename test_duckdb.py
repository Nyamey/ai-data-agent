# test_duckdb.py — Teste le chargement de données avec DuckDB
from agent.tools.data_loader import load_data, execute_query

# Charger le fichier CSV
result = load_data("C:/Users/nyame/Downloads/data csv/customer_retention_data.csv")

print("=== Inspection des données ===")
print(f"Table : {result['table_name']}")
print(f"Lignes : {result['row_count']}")
print(f"Colonnes : {len(result['schema'])}")
print(f"Doublons : {result['duplicate_count']}")
print(f"Valeurs manquantes : {result['null_counts']}")
print(f"Plage de dates : {result['date_range']}")
print()

# Tester une requête
print("=== Top 5 clients par activité ===")
print(execute_query("""
    SELECT customer_id, COUNT(*) as nb_activites 
    FROM customer_retention_data 
    GROUP BY customer_id 
    ORDER BY nb_activites DESC 
    LIMIT 5
"""))
