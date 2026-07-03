import streamlit as st
from neo4j import GraphDatabase
import os

st.title("🔬 NikelPower")
st.write("Тест подключения к Neo4j")

# Получаем URI из переменной окружения или используем localhost по умолчанию
neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD", "nikelpower2026")

st.info(f"🔗 Подключение к: `{neo4j_uri}`")

# Подключение к Neo4j
try:
    driver = GraphDatabase.driver(
        neo4j_uri,
        auth=(neo4j_user, neo4j_password)
    )
    
    with driver.session() as session:
        result = session.run("RETURN 'Neo4j работает!' AS message")
        message = result.single()["message"]
        
    st.success(f"✅ {message}")
    st.info("Подключение к Neo4j успешно!")
    
    driver.close()
    
except Exception as e:
    st.error(f"❌ Ошибка подключения: {e}")
    st.warning("Убедитесь, что Neo4j запущен: `docker compose up -d`")