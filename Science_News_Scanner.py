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
    # We fetch slightly fewer articles here to keep the total count manageable
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
    # The list of sources to scan
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
    
    # Loop through RSS feeds
    for i, url in enumerate(feed_urls):
        status_text.text(f"Scanning source {i+1}/{len(feed_urls)}: {url}...")
        try:
            feed = feedparser.parse(url)
            # Limit to top 3 entries per feed to save time/cost
            for entry in feed.entries[:3]: 
                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'summary': getattr(entry, 'summary', '')[:500], # Truncate long summaries
                    'source': feed.feed.get('title', 'RSS Source')
                })
        except:
            continue
        # Update progress bar
        progress_bar.progress((i + 1) / len(feed_urls))
            
    # Fetch API data
    status_text.text("Fetching DOAJ API data...")
    articles.extend(fetch_doaj_articles())
    
    # Clean up UI elements
    status_text.empty()
    progress_bar.empty()
    
    return articles

def analyze_with_ai(articles):
    results = []
    # Create a progress bar and a status text area
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(articles)
    
    for i, article in enumerate(articles):
        # Update status and progress bar
        status_text.text(f"AI analyzing article {i+1}/{total}: {article['title'][:40]}...")
        progress_bar.progress((i + 1) / total)
        
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
                model="gpt-4o-mini",  # FIXED: Correct model name
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.7
            )
            content = response.choices[0].message.content
            
            # Check for high scores (7, 8, 9, or 10) in the response text
            if any(x in content for x in ['"score": 7', '"score": 8', '"score": 9', '"score": 10']):
                results.append({
                    "data": article,
                    "analysis": content
                })
                
        except Exception as e:
            # Print error to UI for debugging
            st.error(f"Error on article {i+1}: {e}")
            continue
            
    # Clear the progress UI when done
    status_text.text("Analysis Complete!")
    progress_bar.empty()
    return results

# --- MAIN APP UI ---
st.set_page_config(page_title="PopMech Signal Dashboard", layout="wide")

st.title("📡 Signal-to-Noise Dashboard")
st.markdown("_Automated discovery pipeline for Popular Mechanics deputy editor test_")

if st.button("Run Daily Scan"):
    with st.spinner("Trawling the deep web..."):
        # 1. Gather Data
        raw_articles = parse_rss_feeds()
        st.success(f"Found {len(raw_articles)} raw papers. Filtering with AI...")
        
        # 2. Filter Data
        winners = analyze_with_ai(raw_articles)
        
    # 3. Display Results
    st.header(f"Today's Top Picks ({len(winners)})")
    
    if len(winners) == 0:
        st.warning("No high-scoring stories found today. Try again later!")
    
    for item in winners:
        with st.expander(f"⭐ {item['data']['title']}", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Source:** [{item['data']['source']}]({item['data']['link']})")
                st.caption(item['data']['summary'][:300] + "...")
            with col2:
                # Simple formatting to clean up the JSON string for display
                st.info(item['analysis'])
