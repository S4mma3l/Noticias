import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
from datetime import datetime
import newspaper
import logging
import os
import time
import random
import nltk
import json

# Descarga punkt (solo necesita ejecutarse una vez, pero no hace daño tenerlo aquí)
try:
    nltk.data.find('corpora/wordnet')
except LookupError:
    nltk.download('wordnet', download_dir='/home/runner/nltk_data')
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', download_dir='/home/runner/nltk_data')
try:
    nltk.data.find('tokenizers/punkt_tab/english.pickle')
except LookupError:
    nltk.download('punkt_tab', download_dir='/home/runner/nltk_data')

# Configuración del logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_article_data(url):
    """Extrae el título, el resumen y la fecha de publicación."""
    try:
        article = newspaper.Article(url)
        article.download()
        if article.download_state != 2:
            logging.warning(f"No se pudo descargar el artículo de {url}")
            return None, None, None
        article.parse()
        article.nlp()
        return article.title, article.summary, article.publish_date
    except newspaper.article.ArticleException as e:
        logging.error(f"Error al procesar el artículo {url}: {e}")
        return None, None, None
    except Exception as e:
        logging.exception(f"Error inesperado al procesar {url}: {e}")
        return None, None, None
     
def check_if_article_exists(supabase, title):
    """Comprueba si un artículo con el título dado ya existe en la base de datos."""
    normalized_title = title.lower().strip()
    logging.info(f"Verificando existencia en DB por título (normalizado): '{normalized_title}'")
    try:
        query = supabase.table("amenazas").select("*").eq("titulo", normalized_title) # Construye el objeto de consulta
        query_url = query.url  # Intenta obtener la URL de esta manera (cambio aquí)
        logging.info(f"Consulta Supabase generada (URL): {query_url}") # Log de la URL real
        response = query.execute() # Ejecuta la consulta
        logging.info(f"Respuesta de la base de datos para título normalizado '{normalized_title}': {response}")
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error al consultar la base de datos: {e}")
        logging.exception(e)
        return False

def scrape_website(website, num_articles_to_scrape=3, max_articles_per_website=10):
    """Extrae información de un sitio web y devuelve una lista de datos de artículos."""
    # Configuración de Supabase
    logging.info("Comprobando variables de entorno...")
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logging.error("URL o clave de Supabase no encontradas en variables de entorno.")
        return []

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    logging.info("Conexión a Supabase establecida.")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        }
        response = requests.get(website["url"], headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        article_containers = soup.find_all("article")[:max_articles_per_website]
        article_links = []
        articles_data = []
        articles_scraped_count = 0

        for article_container in article_containers: # Renombrar variable para claridad
            if articles_scraped_count >= num_articles_to_scrape:
                logging.info(f"Alcanzado el límite de {num_articles_to_scrape} noticias. Deteniendo extracción para {website['name']}.")
                break

            title_element = article_container.find("h3", class_="SummaryItemHedBase-hiFYpQ") # Selector CSS preciso para el título
            link_element = article_container.find("a", class_="SummaryItemHedLink-civMjp") # Selector CSS preciso para el link

            if title_element and link_element:
                article_title_snippet = title_element.text.strip() # Extraer título del snippet
                article_link = link_element['href']
                if not article_link.startswith("http"):
                    article_link = "https://es.wired.com" + article_link

                logging.info(f"Título encontrado en snippet: '{article_title_snippet}'")

                if check_if_article_exists(supabase, article_title_snippet): # Comprobar duplicado con título del snippet
                    logging.info(f"Artículo con título '{article_title_snippet}' ya existe. Omitiendo.")
                    continue # Saltar al siguiente artículo si ya existe

                logging.info(f"Procesando nuevo artículo con título (snippet): '{article_title_snippet}' y enlace: {article_link}")

                title, summary, publish_date = extract_article_data(article_link) # Extraer datos completos

                if title and summary: # Verificar que newspaper3k extrajo título y resumen
                    logging.info(f"Título del artículo (newspaper3k): '{title}'") # Log del título de newspaper3k
                    if check_if_article_exists(supabase, title): # Doble verificación con título completo por si acaso
                        logging.info(f"Artículo con título (newspaper3k) '{title}' ya existe (segunda verificación). Omitiendo.")
                        continue

                    publish_date_str = publish_date.isoformat() if isinstance(publish_date, datetime) else None
                    data = {
                        "fuente": website["name"],
                        "titulo": title,
                        "enlace": article_link,
                        "resumen": summary,
                        "fecha_publicacion": publish_date_str,
                        "fecha_actualizacion": datetime.utcnow().isoformat()
                    }
                    logging.info(f"Datos a insertar: {data}")
                    try:
                        data_response = supabase.table("amenazas").insert(data, returning="minimal").execute()
                        logging.info(f"Artículo insertado en la base de datos: {title}")
                        articles_scraped_count += 1
                        articles_data.append(data)
                    except Exception as e:
                        logging.error(f"Error al insertar en Supabase: {e}")
                        logging.exception(e)
                else:
                    logging.warning(f"No se pudo extraer título o resumen con newspaper3k del enlace: {article_link}. Omitiendo.")

        return articles_data

    except requests.exceptions.RequestException as e:
        logging.error(f"Error de solicitud web para {website['url']}: {e}")
        return []
    except Exception as e:
        logging.exception(f"Error inesperado al procesar {website['url']}: {e}")
        return []


def main():
    """Función principal."""
    WEBSITES = [
        {"name": "Wired en Español", "url": "https://es.wired.com/tag/ciberseguridad"}
    ]
    all_articles = []
    num_articles_per_run = 3
    for website in WEBSITES:
        logging.info(f"Extrayendo noticias de: {website['name']}")
        articles = scrape_website(website, num_articles_to_scrape=num_articles_per_run)
        all_articles.extend(articles)
        logging.info(f"Extracción de {website['name']} finalizada.")

    logging.info("Extracción completada para todos los sitios.")

    with open("data/articles.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    main()