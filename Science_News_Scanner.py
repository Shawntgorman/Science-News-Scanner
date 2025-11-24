import streamlit as st
import feedparser
import requests
import datetime
from datetime import date
import json
from openai import OpenAI
import os
from dotenv import load_dotenv
import urllib.parse

# --- CONFIGURATION & SECURITY ---
load_dotenv()

def get_api_key():
    if "OPENAI_API_KEY" in st.secrets:
        return st.secrets["OPENAI_API_KEY"]
    return os.getenv("OPENAI_API_KEY")

api_key = get_api_key()

if not api_key:
    st.error("API Key not found! Please set OPENAI_API_KEY in Streamlit Secrets.")
    st.stop()

client = OpenAI(api_key=api_key)

# --- USER PREFERENCES ---
# We define the start date and keywords here to use across all APIs
START_DATE = date(2025, 11, 18)
KEYWORDS = [
    "time travel", "consciousness", "holographic universe", 
    "quantum gravity", "bio resurrection", "life extension", 
    "simulation theory", "synthetic biology", "warp drive"
]

# --- FETCHING FUNCTIONS ---

def fetch_openalex():
    """
    Queries OpenAlex for papers published since Nov 18, 2025, 
    matching specific PopMech keywords.
    """
    st.write("...Querying OpenAlex API (Big database, this takes a second)...")
    articles = []
    
    # Construct a search string: (time travel OR consciousness OR ...)
    # OpenAlex uses 'default.search' for keywords
    search_query = " OR ".join([f'"{k}"' for k in KEYWORDS])
    
    # URL Encoding
    params = {
        'filter': f'from_publication_date:{START_DATE},default.search:{search_query}',
        'per-page': 10,
        'sort': 'publication_date:desc'
    }
    
    url = "https://api.openalex.org/works"
    
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        for item in data.get('results', []):
            # Extract relevant data
            title = item.get('title')
            # OpenAlex stores abstracts in an 'inverted index' which is hard to read.
            # We often have to use the title or look for a stored abstract.
            # For simplicity, we use the title + concepts as the summary if abstract is missing.
            summary = f"Topics: {[c['display_name'] for c in item.get('concepts', [])[:5]]}"
            
            articles.append({
                'title': title,
                'link': item.get('doi') or item.get('id'),
                'summary': summary,
                'source': 'OpenAlex (Preprint/Paper)'
            })
    except Exception as e:
        print(f"OpenAlex Error: {e}")
        
    return articles

def fetch_osf():
    """
    Queries OSF Preprints API for recent submissions matching keywords.
    """
    st.write("...Querying OSF Preprints API...")
    articles = []
    
    # OSF search is simpler. We'll search for the general "science" category 
    # and filter by date on our end, or use their query param.
    
    # Note: OSF API v2 filtering is strict. We will fetch recent preprints 
    # and check keywords manually to ensure high relevance.
    url = "https://api.osf.io/v2/preprints/"
    params = {
        'filter[date_published][gte]': f'{START_DATE}',
        'page[size]': 15
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        for item in data.get('data', []):
            attrs = item.get('attributes', {})
            title = attrs.get('title', '')
            desc = attrs.get('description', '')
            
            # Simple keyword check before adding
            full_text = (title + desc).lower()
            if any(k in full_text for k in ["time", "quantum", "mind", "bio", "life", "ai", "simulation"]):
                articles.append({
                    'title': title,
                    'link': item.get('links', {}).get('html'),
                    'summary': desc[:500],
                    'source': 'OSF Preprint'
                })
    except Exception as e:
        print(f"OSF Error: {e}")
        
    return articles

def fetch_rss_feeds():
    """
    Fetches from standard RSS feeds (ArXiv, Nature, etc.)
    """
    st.write("...Scanning standard RSS feeds...")
    
    # REMOVED OpenAlex/OSF from here. Only actual RSS feeds remain.
    feed_urls = [
        "http://www.nature.com/subjects/scientific-reports.rss",
        "http://journals.plos.org/plosone/feed/atom",
        "https://royalsocietypublishing.org/action/showFeed?type=etoc&journalCode=rspa",
        "https://royalsocietypublishing.org/action/showFeed?type=etoc&journalCode=pnas",
        "http://export.arxiv.org/rss/quant-ph",
        "http://export.arxiv.org/rss/q-bio",
        "http://export.arxiv.org/rss/physics.soc-ph",
        "http://export.arxiv.org/rss/cs.AI" # Added AI specific feed
    ]
    
    articles = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PopMech-Scanner/1.0"}
    
    for url in feed_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries[:5]:
                # RSS Date Filter
                # We try to parse the date. If valid and older than start date, skip.
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = date(entry.published_parsed.tm_year, entry.published_parsed.tm_mon, entry.published_parsed.tm_mday)
                    if pub_date < START_DATE:
                        continue
                
                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'summary': getattr(entry, 'summary', '')[:600],
                    'source': feed.feed.get('title', 'RSS Source')
                })
        except:
            continue
            
    return articles

def analyze_with_ai(articles):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    total = len(articles)
    
    if total == 0:
        return []

    for i, article in enumerate(articles):
        status_text.text(f"AI analyzing {i+1}/{total}: {article['title'][:40]}...")
        progress_bar.progress((i + 1) / total)
        
        prompt = f"""
        Role: Deputy Short-Form Science Editor at Popular Mechanics.
        Task: Evaluate this story.
        
        Title: {article['title']}
        Summary: {article['summary']}
        Source: {article['source']}
        
        STRICT Criteria:
        - Published/Posted after Nov 18, 2025.
        - MUST fall into: AI & Futurism; Time & Time Travel; Consciousness; Simulation; Quantum; Biology & Evolution; Life Extension.
        - MUST be a "Wow" story, not incremental research.
        
        Return JSON with these exact keys:
        - "score" (number 0-10)
        - "headline" (string, PopMech style)
        - "reason" (string, why it fits the criteria)
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You output only valid JSON."},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.8
            )
            
            data = json.loads(response.choices[0].message.content)
            
            if data.get("score", 0) >= 6: # Filter for quality
                results.append({
                    "original": article,
                    "ai_data": data
                })
                
        except Exception as e:
            continue
            
    status_text.text("Analysis Complete!")
    progress_bar.empty()
    return results

# --- MAIN APP UI ---
st.set_page_config(page_title="PopMech Signal Dashboard", layout="wide")

st.title("📡 Signal-to-Noise Dashboard")
st.markdown(f"**Target Date:** Nov 18, 2025 - Present")
st.markdown("**Target Topics:** _Time Travel, Consciousness, Bio-Resurrection, AI, Quantum_")

if st.button("Run Targeted Scan"):
    with st.spinner(" querying OpenAlex, OSF, and ArXiv..."):
        
        # Gather data from all 3 methods
        list_1 = fetch_openalex()
        list_2 = fetch_osf()
        list_3 = fetch_rss_feeds()
        
        all_articles = list_1 + list_2 + list_3
        
        st.success(f"Found {len(all_articles)} papers matching criteria. Filtering with AI...")
        
        # Run AI Analysis
        winners = analyze_with_ai(all_articles)
        
    st.header(f"Today's Top Picks ({len(winners)})")
    
    if len(winners) == 0:
        st.warning("No hits found. (OpenAlex/OSF might be quiet today, or keywords are too specific).")
    
    for item in winners:
        score = item['ai_data']['score']
        with st.expander(f"[{score}/10] {item['ai_data']['headline']}", expanded=True):
            st.markdown(f"**Pitch:** {item['ai_data']['reason']}")
            st.markdown(f"**Source:** [{item['original']['source']}]({item['original']['link']})")
            st.caption(f"**Original Title:** {item['original']['title']}")
