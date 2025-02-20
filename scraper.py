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

def check_if_article_exists(title):
    """Comprueba si un artículo con el título dado ya existe en la base de datos."""
    # Configuración de Supabase (movida dentro de la función)
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logging.error("La URL o la clave de Supabase no se encontraron en las variables de entorno")
        return False

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    normalized_title = title.lower().strip()
    try:
        response = supabase.table("amenazas").select("*").eq("titulo", normalized_title).execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error al comprobar si existe el artículo en Supabase: {e}")
        return False

def scrape_website(website, num_articles=6):
    """Extrae información de un sitio web y devuelve una lista de datos de artículos."""
    # Configuración de Supabase (movida dentro de la función)
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logging.error("La URL o la clave de Supabase no se encontraron en las variables de entorno")
        return []

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        }
        response = requests.get(website["url"], headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        article_containers = soup.find_all("article")[:num_articles]
        article_links = []

        for article in article_containers:
            a_tag = article.find("a")
            if a_tag and a_tag.has_attr('href'):
                link = a_tag['href']
                if not link.startswith("http"):
                    link = "https://es.wired.com" + link
                article_links.append(link)

        logging.info(f"Se encontraron {len(article_links)} enlaces de artículos en {website['url']}")
        for link in article_links:
            logging.info(f"  {link}")

        articles_data = []
        for link in article_links:
            title, summary, publish_date = extract_article_data(link)
            if title and summary:
                if check_if_article_exists(title):
                    logging.info(f"El artículo ya existe: {title}. Omitiendo.")
                    continue

                publish_date_str = publish_date.isoformat() if isinstance(publish_date, datetime) else None
                data = {
                    "fuente": website["name"],
                    "titulo": title,
                    "enlace": link,
                    "resumen": summary,
                    "fecha_publicacion": publish_date_str,
                    "fecha_actualizacion": datetime.utcnow().isoformat()
                }
                logging.info(f"Datos a insertar: {data}")
                articles_data.append(data)
        return articles_data

    except requests.exceptions.RequestException as e:
        logging.error(f"Fallo en la solicitud para {website['url']}: {e}")
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
    for website in WEBSITES:
        logging.info(f"Extrayendo: {website['name']}")
        articles = scrape_website(website)
        all_articles.extend(articles)
        logging.info(f"Extracción finalizada: {website['name']}")

    logging.info("Extracción completada.")

    with open("data/articles.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    main()