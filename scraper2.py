import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
from datetime import datetime
import newspaper
import logging
from dotenv import load_dotenv
import os
import time
import random
import nltk

# Descarga punkt (solo necesita ejecutarse una vez, pero no hace daño tenerlo aquí)
nltk.download('punkt', quiet=True)

# Load environment variables
load_dotenv()

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("Supabase URL or Key not found in .env file")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# List of websites
WEBSITES = [
    {"name": "Wired en Español", "url": "https://es.wired.com/tag/ciberseguridad"}
]

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def extract_article_data(url):
    """Extracts title, summary, and publish date."""
    try:
        article = newspaper.Article(url)
        article.download()
        if article.download_state != 2:
            logging.warning(f"Failed to download article from {url}")
            return None, None, None
        article.parse()
        article.nlp()
        return article.title, article.summary, article.publish_date
    except newspaper.article.ArticleException as e:
        logging.error(f"Error processing article {url}: {e}")
        return None, None, None
    except Exception as e:
        logging.exception(f"Unexpected error processing {url}: {e}")
        return None, None, None

def scrape_website(website, max_retries=3):
    """Scrapes a website."""
    for attempt in range(max_retries):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            }
            response = requests.get(website["url"], headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            # --- Website-Specific Extraction ---
            article_containers = soup.find_all("article")[:4]
            article_links = []

            for article in article_containers:
                a_tag = article.find("a")
                if a_tag and a_tag.has_attr('href'):
                    link = a_tag['href']
                    if not link.startswith("http"):
                        link = "https://es.wired.com" + link
                    article_links.append(link)
            # --- End Website-Specific Extraction ---

            logging.info(f"Found {len(article_links)} article links on {website['url']}")
            for link in article_links:
                logging.info(f"  {link}")

            for link in article_links:
                title, summary, publish_date = extract_article_data(link)
                if title and summary:
                    publish_date_str = publish_date.isoformat() if isinstance(publish_date, datetime) else None
                    data = {
                        "fuente": website["name"],
                        "titulo": title,
                        "enlace": link,
                        "resumen": summary,
                        "fecha_publicacion": publish_date_str,
                        "fecha_actualizacion": datetime.utcnow().isoformat()
                    }
                    logging.info(f"Data to be inserted: {data}")

                    # Insert directly (handle duplicates with Supabase unique constraint)
                    try:
                        data_response = supabase.table("amenazas").insert(data, returning="minimal").execute()  # Usa solo el nombre de la tabla.
                        logging.info(f"Inserted article: {title}")
                    except Exception as e:
                        logging.error(f"Error inserting into Supabase: {e}")

            return

        except requests.exceptions.RequestException as e:
            logging.error(f"Attempt {attempt+1} failed for {website['url']}: {e}")
            if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 403:
                break
        except Exception as e:
            logging.exception(f"Attempt {attempt+1} failed for {website['url']}: {e}")
            break
        finally:
            delay = (2 ** attempt) + random.random()
            logging.info(f"Waiting {delay:.2f} seconds...")
            time.sleep(delay)

    logging.error(f"Failed to scrape {website['url']} after {max_retries} attempts")

def main():
    """Main function."""
    for website in WEBSITES:
        logging.info(f"Scraping: {website['name']}")
        scrape_website(website)
        logging.info(f"Finished scraping: {website['name']}")

if __name__ == "__main__":
    main()
    logging.info("Scraping completed.")