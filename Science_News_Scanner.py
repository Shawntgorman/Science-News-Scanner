import streamlit as st
import feedparser
import requests
import datetime
import json
from openai import OpenAI
import os
from dotenv import load_dotenv

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

# --- FUNCTIONS ---

def fetch_rss_data():
    # The complete list of 10 sources
    feed_urls = [
        "http://www.nature.com/subjects/scientific-reports.rss",
        "http://journals.plos.org/plosone/feed/atom",
        "https://royalsocietypublishing.org/action/showFeed?type=etoc&journalCode=rspa", # Proc A
        "https://royalsocietypublishing.org/action/showFeed?type=etoc&journalCode=rspb", # Proc B
        "https://www.pnas.org/action/showFeed?type=etoc&journalCode=pnas",
        "http://export.arxiv.org/rss/quant-ph",
        "http://connect.biorxiv.org/biorxiv_xml.php?subject=all",
        "https://news.ycombinator.com/rss",
        "http://feeds.aps.org/rss/recent/prl.xml",
        "https://www.reddit.com/r/LabRats/new/.rss"
    ]
    
    articles = []
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    # We use a custom User-Agent to prevent Reddit/Journals from blocking the script
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PopMech-Scanner/1.0"
    }
    
    for i, url in enumerate(feed_urls):
        status_text.text(f"Scanning source {i+1}/{len(feed_urls)}: {url}...")
        try:
            # Fetch raw content first to handle permission headers
            response = requests.get(url, headers=headers, timeout=10)
            feed = feedparser.parse(response.content)
            
            # Grab top 3 entries per feed
            for entry in feed.entries[:3]: 
                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'summary': getattr(entry, 'summary', '')[:600], # increased limit
                    'source': feed.feed.get('title', 'RSS Source')
                })
        except Exception as e:
            print(f"Failed to parse {url}: {e}")
            continue
            
        progress_bar.progress((i + 1) / len(feed_urls))
    
    status_text.empty()
    progress_bar.empty()
    return articles

def analyze_with_ai(articles):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(articles)
    
    for i, article in enumerate(articles):
        status_text.text(f"AI analyzing {i+1}/{total}: {article['title'][:40]}...")
        progress_bar.progress((i + 1) / total)
        
        # We force the AI to return valid JSON using response_format
        prompt = f"""
        Role: Senior Science Editor at Popular Mechanics.
        Task: Evaluate this story.
        
        Title: {article['title']}
        Summary: {article['summary']}
        
        Criteria:
        - "Small but Astounding" (Niche, weird, mind-blowing)
        - visually promising
        - NOT generic incremental science
        
        Return JSON with these exact keys:
        - "score" (number 0-10)
        - "headline" (string)
        - "reason" (string)
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You output only valid JSON."},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"}, # This guarantees JSON output
                temperature=0.7
            )
            
            # Parse the JSON properly
            data = json.loads(response.choices[0].message.content)
            
            # Lowered threshold to 6 to ensure you see results for the test
            if data.get("score", 0) >= 6:
                results.append({
                    "original": article,
                    "ai_data": data
                })
                
        except Exception as e:
            print(f"AI Error on {i}: {e}")
            continue
            
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
        raw_articles = fetch_rss_data()
        st.success(f"Found {len(raw_articles)} raw papers. Filtering with AI...")
        
        # 2. Filter Data
        winners = analyze_with_ai(raw_articles)
        
    # 3. Display Results
    st.header(f"Today's Top Picks ({len(winners)})")
    
    if len(winners) == 0:
        st.warning("No high-scoring stories found today. (Try checking the logs or lowering the score threshold in the code)")
    
    for item in winners:
        # Color-coded score badge
        score = item['ai_data']['score']
        score_color = "green" if score >= 8 else "orange"
        
        with st.expander(f"[{score}/10] {item['ai_data']['headline']}", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Pitch:** {item['ai_data']['reason']}")
                st.markdown(f"**Original Source:** [{item['original']['source']}]({item['original']['link']})")
                st.caption(f"**Original Title:** {item['original']['title']}")
            with col2:
                st.metric(label="PopMech Score", value=f"{score}/10")
