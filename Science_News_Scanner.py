import streamlit as st
import feedparser
import requests
import datetime
from openai import OpenAI
import os
from dotenv import load_dotenv

# --- CONFIGURATION & SECURITY ---
# This loads API key from .env (local) or Streamlit Secrets (cloud)
load_dotenv()

def get_api_key():
    # Check Streamlit secrets first (for cloud deployment)
    if "OPENAI_API_KEY" in st.secrets:
        return st.secrets["OPENAI_API_KEY"]
    # Fallback to environment variable (for local run)
    return os.getenv("OPENAI_API_KEY")

api_key = get_api_key()

if not api_key:
    st.error("API Key not found! Please set OPENAI_API_KEY in .env or Streamlit Secrets.")
    st.stop()

client = OpenAI(api_key=api_key)

# --- FUNCTIONS ---
def fetch_doaj_articles():
    """Fetches recent science articles from Directory of Open Access Journals"""
    url = "https://doaj.org/api/v1/search/articles/bibjson.subject.term:science?sort=created_date&pageSize=5"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        articles = []
        for result in data.get('results', []):
            bibjson = result.get('bibjson', {})
            articles.append({
                'title': bibjson.get('title', 'No Title'),
                'link': bibjson.get('link', [{}])[0].get('url', '#'),
                'summary': bibjson.get('abstract', 'No Abstract'),
                'source': 'DOAJ'
            })
        return articles
    except Exception as e:
        return []

def parse_rss_feeds():
    feed_urls = [
        "http://www.nature.com/subjects/scientific-reports.rss",
        "http://journals.plos.org/plosone/feed/atom",
        "https://royalsocietypublishing.org/action/showFeed?type=etoc&journalCode=rspa",
        "https://royalsocietypublishing.org/action/showFeed?type=etoc&journalCode=pnas",
        "http://export.arxiv.org/rss/quant-ph",
        "http://connect.biorxiv.org/biorxiv_xml.php?subject=all"
    ]
    
    articles = []
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    for i, url in enumerate(feed_urls):
        status_text.text(f"Scanning source {i+1}/{len(feed_urls)}: {url}...")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]: # Limit to top 3 per feed for speed
                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'summary': getattr(entry, 'summary', '')[:500], # Truncate long summaries
                    'source': feed.feed.get('title', 'RSS Source')
                })
        except:
            continue
        progress_bar.progress((i + 1) / len(feed_urls))
            
    status_text.text("Fetching DOAJ API data...")
    articles.extend(fetch_doaj_articles())
    status_text.empty()
    progress_bar.empty()
    
    return articles

def analyze_with_ai(articles):
    results = []
    status_text = st.empty()
    
    # Create a container for the results
    for i, article in enumerate(articles):
        status_text.text(f"AI analyzing article {i+1}/{len(articles)}...")
        
        prompt = f"""
        Role: Senior Science Editor.
        Task: Rate this story for Popular Mechanics (0-10).
        Criteria: "Small but Astounding," Visual, Niche.
        
        Title: {article['title']}
        Summary: {article['summary']}
        
        Output format: strictly JSON.
        {{
            "score": number,
            "headline": "catchy headline",
            "reason": "1 sentence why"
        }}
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100
            )
            content = response.choices[0].message.content
            
            # Simple parsing to check if score is high enough (e.g. > 7)
            # In a real app, you'd use json.loads() for robustness
            if '"score": 7' in content or '"score": 8' in content or '"score": 9' in content:
                results.append({
                    "data": article,
                    "analysis": content
                })
        except:
            continue
            
    status_text.empty()
    return results

# --- MAIN APP UI ---
st.set_page_config(page_title="PopMech Signal Dashboard", layout="wide")

st.title("📡 Signal-to-Noise Dashboard")
st.markdown("_Automated discovery pipeline for Popular Mechanics deputy editor test_")

if st.button("Run Daily Scan"):
    with st.spinner("Trawling the deep web..."):
        raw_articles = parse_rss_feeds()
        st.success(f"Found {len(raw_articles)} raw papers. Filtering with AI...")
        
        winners = analyze_with_ai(raw_articles)
        
    st.header(f"Today's Top Picks ({len(winners)})")
    
    for item in winners:
        with st.expander(f"⭐ {item['data']['title']}", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Source:** [{item['data']['source']}]({item['data']['link']})")
                st.caption(item['data']['summary'][:300] + "...")
            with col2:
                st.info(item['analysis'])