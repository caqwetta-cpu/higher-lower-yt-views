"""
Higher or Lower: Video Views Edition
A Streamlit game using the official YouTube Data API v3.

Run:
    pip install streamlit requests
    streamlit run app.py

API key: put it in .streamlit/secrets.toml as
    YOUTUBE_API_KEY = "your-key"
or paste it into the sidebar while testing.
"""

import random

import requests
import streamlit as st

API_BASE = "https://www.googleapis.com/youtube/v3"
VIDEOS_PER_CHANNEL = 100  # max videos pulled from each channel's uploads

st.set_page_config(page_title="Higher or Lower: Views", page_icon="🎬", layout="centered")


# ---------------------------------------------------------------- API helpers
def api_get(path: str, params: dict, key: str) -> dict:
    r = requests.get(f"{API_BASE}/{path}", params={**params, "key": key}, timeout=15)
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "YouTube API error"))
    return data


def best_thumbnail(thumbs: dict) -> str | None:
    for size in ("maxres", "standard", "high", "medium", "default"):
        if size in thumbs:
            return thumbs[size]["url"]
    return None


# Cached for 6 hours so you don't burn quota on every rerun,
# and data is refreshed regularly instead of stored forever.
@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def fetch_channel_videos(handle: str, key: str) -> list[dict]:
    handle = handle.strip()
    if not handle.startswith("@"):
        handle = "@" + handle

    # 1) handle -> uploads playlist (1 quota unit)
    ch = api_get("channels", {"part": "contentDetails,snippet", "forHandle": handle}, key)
    if not ch.get("items"):
        raise ValueError(f"Channel {handle} not found")
    channel_title = ch["items"][0]["snippet"]["title"]
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # 2) uploads playlist -> video IDs (1 unit per 50 videos)
    ids, page_token = [], None
    while len(ids) < VIDEOS_PER_CHANNEL:
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        pl = api_get("playlistItems", params, key)
        ids += [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        page_token = pl.get("nextPageToken")
        if not page_token:
            break
    ids = ids[:VIDEOS_PER_CHANNEL]

    # 3) video IDs -> title, thumbnail, views (1 unit per 50 videos)
    videos = []
    for i in range(0, len(ids), 50):
        vids = api_get("videos", {"part": "snippet,statistics", "id": ",".join(ids[i:i + 50])}, key)
        for v in vids.get("items", []):
            views = v.get("statistics", {}).get("viewCount")
            thumb = best_thumbnail(v["snippet"].get("thumbnails", {}))
            if views is None or thumb is None:  # hidden view counts or no thumbnail
                continue
            videos.append({
                "id": v["id"],
                "title": v["snippet"]["title"],
                "channel": channel_title,
                "thumbnail": thumb,
                "views": int(views),
            })
    return videos


# ---------------------------------------------------------------- game logic
def pick_next(exclude_id: str | None) -> dict:
    pool = [v for v in st.session_state.pool if v["id"] != exclude_id]
    return random.choice(pool)


def start_game(pool: list[dict]):
    st.session_state.pool = pool
    st.session_state.left = random.choice(pool)
    st.session_state.right = pick_next(st.session_state.left["id"])
    st.session_state.score = 0
    st.session_state.game_over = False
    st.session_state.last_result = None


def guess(higher: bool):
    left, right = st.session_state.left, st.session_state.right
    correct = right["views"] >= left["views"] if higher else right["views"] <= left["views"]
    st.session_state.last_result = (correct, right)
    if correct:
        st.session_state.score += 1
        st.session_state.best = max(st.session_state.get("best", 0), st.session_state.score)
        st.session_state.left = right
        st.session_state.right = pick_next(right["id"])
    else:
        st.session_state.game_over = True


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")  # 1.234.567 (Italian style)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Setup")
    try:
        default_key = st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        default_key = ""
    api_key = st.text_input("YouTube API key", value=default_key, type="password")
    handles_raw = st.text_area(
        "Channel handles (one per line)",
        value="@veritasium\n@MrBeast\n@kurzgesagt",
        height=120,
    )
    if st.button("Load channels & start", type="primary", use_container_width=True):
        if not api_key:
            st.error("Add your API key first.")
        else:
            handles = [h for h in handles_raw.splitlines() if h.strip()]
            pool, errors = [], []
            with st.spinner("Fetching videos…"):
                for h in handles:
                    try:
                        pool += fetch_channel_videos(h, api_key)
                    except Exception as e:
                        errors.append(f"{h.strip()}: {e}")
            for e in errors:
                st.warning(e)
            if len(pool) < 2:
                st.error("Need at least 2 videos with public view counts.")
            else:
                start_game(pool)
                st.success(f"Loaded {len(pool)} videos.")

    st.divider()
    st.caption(
        "This game uses YouTube API Services. By playing you agree to the "
        "[YouTube Terms of Service](https://www.youtube.com/t/terms). "
        "See the [Google Privacy Policy](https://policies.google.com/privacy). "
        "Not affiliated with or endorsed by YouTube."
    )

# ---------------------------------------------------------------- main
st.title("🎬 Higher or Lower")
st.caption("Does the second video have more or fewer views than the first?")

if "pool" not in st.session_state:
    st.info("Enter your API key and some channel handles in the sidebar, then press **Load channels & start**.")
    st.stop()

c1, c2 = st.columns(2)
c1.metric("Score", st.session_state.score)
c2.metric("Best", st.session_state.get("best", 0))

result = st.session_state.last_result
if result and result[0] and not st.session_state.game_over:
    st.success(f"Correct! It had {fmt(result[1]['views'])} views.")

left, right = st.session_state.left, st.session_state.right
col_l, col_r = st.columns(2, gap="large")


def video_card(col, v, show_views: bool):
    with col:
        st.image(v["thumbnail"])
        st.markdown(f"**[{v['title']}](https://www.youtube.com/watch?v={v['id']})**")
        st.caption(v["channel"])
        if show_views:
            st.markdown(f"### {fmt(v['views'])} views")


video_card(col_l, left, show_views=True)
video_card(col_r, right, show_views=st.session_state.game_over)

if st.session_state.game_over:
    st.error(
        f"Wrong! **{right['title']}** has {fmt(right['views'])} views. "
        f"Final score: **{st.session_state.score}**"
    )
    if st.button("Play again", type="primary", use_container_width=True):
        start_game(st.session_state.pool)
        st.rerun()
else:
    with col_r:
        b1, b2 = st.columns(2)
        if b1.button("⬆ Higher", use_container_width=True):
            guess(True)
            st.rerun()
        if b2.button("⬇ Lower", use_container_width=True):
            guess(False)
            st.rerun()
