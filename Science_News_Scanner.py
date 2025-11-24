import streamlit as st
import feedparser
import requests
import datetime
from datetime import date, timedelta
import json
from openai import OpenAI
import os
from dotenv import load_dotenv
import random
import time

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

# --- TARGETING PARAMETERS ---
# We look back 5 days to ensure we catch the Nov 18 window
START_DATE = datetime.date.today() - timedelta(days=5)

# BANNED TERMS (Stops the "Flipped Classroom" / Policy papers)
EXCLUDE_TERMS = [
    "classroom", "education", "pedagogy", "curriculum", "funding", 
    "policy", "obituary", "correction", "erratum", "diversity", 
    "student", "campus", "undergraduate", "flipped"
]

# --- HELPER FUNCTIONS ---

def is_junk(title, summary):
    """
    Returns True if the paper is likely administrative/educational junk.
    """
    text = (title + " " + summary).lower()
    for term in EXCLUDE_TERMS:
        if term in text:
            return True
    return False

# --- FETCHING FUNCTIONS ---

def fetch_openalex_targeted():
    """
    Fires specific, separate queries for each PopMech category to guarantee variety.
    """
    st.write(f"...Targeting OpenAlex (Papers since {START_DATE})...")
    articles = []
    
    # We run separate queries for distinct topics to ensure one doesn't drown out the others
    queries = [
        "time travel OR closed timelike curve OR wormhole OR time",
        "quantum OR higher dimension OR dimensional OR dimensionality"
        "artificial intelligence OR large language model OR agi",
        "quantum entanglement OR holographic OR many worlds OR physics",
        "synthetic biology OR crispr OR resurrection OR longevity",
        "consciousness OR cognitive OR neural OR mind",
        "biology OR evolution",
        "Earth OR environment OR environmental",
        "futurism OR simulation"
    ]
    
    base_url = "https://api.openalex.org/works"
    
    for q in queries:
        # Construct filter: Published recently AND matches query in Title/Abstract
        filter_param = f"from_publication_date:{START_DATE},title_and_abstract.search:{q}"
        params = {
            'filter': filter_param,
            'per-page': 5, # Get top 5 for EACH category
            'sort': 'relevance_score:desc' # Get the best matches, not just newest
        }
        
        try:
            r = requests.get(base_url, params=params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                for item in data.get('results', []):
                    title = item.get('title')
                    if not title: continue
                    
                    # OpenAlex abstract handling
                    abstract = "No abstract available."
                    # (OpenAlex uses an inverted index for abstracts, often too complex to reconstruct quickly.
                    # We rely on the Title + Concepts list for the AI judgment).
                    concepts = [c['display_name'] for c in item.get('concepts', [])[:5]]
                    summary = f"Key Concepts: {', '.join(concepts)}"
                    
                    if not is_junk(title, summary):
                        articles.append({
                            'title': title,
                            'link': item.get('doi') or item.get('id'),
                            'summary': summary,
                            'source': f"OpenAlex ({q.split(' OR ')[0]}...)"
                        })
            time.sleep(0.2) # Be nice to the API
        except Exception as e:
            print(f"OpenAlex Error on {q}: {e}")
            continue

    return articles

def fetch_osf_preprints():
    """
    Fetches raw recent preprints from OSF and filters locally.
    """
    st.write("...Scanning OSF Preprints...")
    articles = []
    url = "https://api.osf.io/v2/preprints/"
    
    # OSF doesn't support complex search well via API, so we fetch the firehose
    # of recent papers and filter them ourselves.
    params = {
        'filter[date_published][gte]': f'{START_DATE}',
        'page[size]': 20 # Grab a larger chunk
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        relevant_keywords = ["quantum", "ai", "intelligence", "neural", "physics", "bio", "genome", "space", "time", "simulation"]
        
        for item in data.get('data', []):
            attrs = item.get('attributes', {})
            title = attrs.get('title', '')
            desc = attrs.get('description', '') or ""
            
            full_text = (title + desc).lower()
            
            # 1. Check for Junk
            if is_junk(title, desc):
                continue
                
            # 2. Check for Relevance
            if any(k in full_text for k in relevant_keywords):
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
    Fetches from standard RSS feeds but goes deeper (Top 10).
    """
    st.write("...Scanning ArXiv & Journals...")
    
    feed_urls = [
        "http://export.arxiv.org/rss/quant-ph",
        "http://export.arxiv.org/rss/cs.AI",
        "http://export.arxiv.org/rss/q-bio",
        "http://export.arxiv.org/rss/gr-qc", # General Relativity / Quantum Cosmology
        "http://www.nature.com/subjects/scientific-reports.rss",
        "https://www.pnas.org/action/showFeed?type=etoc&journalCode=pnas"
    ]
    
    articles = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PopMech-Scanner/1.0"}
    
    for url in feed_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            feed = feedparser.parse(response.content)
            
            # Go deeper! Top 10 instead of Top 3
            for entry in feed.entries[:10]:
                title = entry.title
                summary = getattr(entry, 'summary', '')[:600]
                
                # IMMEDIATE TRASH FILTER
                if is_junk(title, summary):
                    continue

                articles.append({
                    'title': title,
                    'link': entry.link,
                    'summary': summary,
                    'source': feed.feed.get('title', 'RSS Source')
                })
        except:
            continue
            
    return articles

def analyze_with_ai(articles):
    results = []
    
    # SHUFFLE the articles so PNAS isn't always first
    random.shuffle(articles)
    
    # Cap the analysis at 25 articles to save tokens/time, but since we shuffled,
    # it's a random sample of the best candidates.
    selection = articles[:25]
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total = len(selection)
    
    if total == 0:
        return []

    for i, article in enumerate(selection):
        status_text.text(f"AI analyzing {i+1}/{total}: {article['title'][:40]}...")
        progress_bar.progress((i + 1) / total)
        
        prompt = f"""
        Role: Deputy Short-Form Science Editor at Popular Mechanics.
        
        Paper: "{article['title']}"
        Summary: "{article['summary']}"
        Source: "{article['source']}"
        
        Does this paper meet these CRITERIA?
        1. TOPIC: Evolution, Biology, Earth Sciences, Environmental Sciences, AI, Futurism, Time, Time Travel, Consciousness, the Mind, Simulation, Holographic, Quantum, Resurrection, 
        Higher Dimensional Physics, Life Extension
        2. CONTENT: "Meaningful advance in biology, physics, cognitive psychology, artificial intelligence, Earth sciences, and environmental sciences" and "Contains cause-effect explanations" and "Content can be used to ask and answer meaningful questions"
        3. EXCLUDE: Education, Policy, Incremental tweaks, boring math proofs.
        
        If NO, return JSON: {{"score": 0, "headline": "", "reason": ""}}
        If YES, return JSON: {{"score": 8, "headline": "PopMech Style Headline", "reason": "Why it explains something new and answers interesting questions about important science topics"}}
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You output only valid JSON."},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.7
            )
            
            data = json.loads(response.choices[0].message.content)
            
            if data.get("score", 0) >= 6:
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

st.title("📡 Deep-Dive Signal Dashboard")
st.markdown(f"**Scanning Window:** {START_DATE} to Present")
st.markdown("**Filters:** _Education/Policy content auto-removed._")

if st.button("Run Deep Scan"):
    with st.spinner("Executing targeted search patterns..."):
        
        # 1. Fetch from all sources
        list_1 = fetch_openalex_targeted()
        list_2 = fetch_osf_preprints()
        list_3 = fetch_rss_feeds()
        
        all_articles = list_1 + list_2 + list_3
        unique_articles = {v['title']:v for v in all_articles}.values() # Remove duplicates
        final_list = list(unique_articles)
        
        st.success(f"Found {len(final_list)} candidates after filtering junk. Sending to AI...")
        
        # 2. Analyze
        winners = analyze_with_ai(final_list)
        
        # Sort by score
        winners.sort(key=lambda x: x['ai_data']['score'], reverse=True)
        
    st.header(f"Today's Top Picks ({len(winners)})")
    
    if len(winners) == 0:
        st.warning("No hits found. (If you still see nothing, the date window might be too tight for these specific topics).")
    
    for item in winners:
        score = item['ai_data']['score']
        with st.expander(f"[{score}/10] {item['ai_data']['headline']}", expanded=True):
            st.markdown(f"**Pitch:** {item['ai_data']['reason']}")
            st.markdown(f"**Source:** [{item['original']['source']}]({item['original']['link']})")
            st.caption(f"**Original Title:** {item['original']['title']}")

