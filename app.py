"""
Higher or Lower: Video Views Edition
A Streamlit game using the official YouTube Data API v3.

Run:
    pip install streamlit requests
    streamlit run app.py

API key: put it in .streamlit/secrets.toml (or Streamlit Cloud → Settings → Secrets) as
    YOUTUBE_API_KEY = "your-key"
The key stays on the server and is never sent to the page.
"""

import json

import requests
import streamlit as st
import streamlit.components.v1 as components

API_BASE = "https://www.googleapis.com/youtube/v3"
VIDEOS_PER_CHANNEL = 100  # max videos pulled from each channel's uploads

st.set_page_config(page_title="Higher or Lower: Views", page_icon="🎬", layout="wide")
st.markdown("<style>.block-container{padding-top:1.5rem;padding-bottom:0}</style>", unsafe_allow_html=True)


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


# Cached for 6 hours: saves quota, and data is refreshed instead of stored forever.
@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def fetch_channel_videos(handle: str, key: str) -> list[dict]:
    handle = handle.strip()
    if not handle.startswith("@"):
        handle = "@" + handle

    ch = api_get("channels", {"part": "contentDetails,snippet", "forHandle": handle}, key)
    if not ch.get("items"):
        raise ValueError(f"Channel {handle} not found")
    channel_title = ch["items"][0]["snippet"]["title"]
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

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

    videos = []
    for i in range(0, len(ids), 50):
        vids = api_get("videos", {"part": "snippet,statistics", "id": ",".join(ids[i:i + 50])}, key)
        for v in vids.get("items", []):
            views = v.get("statistics", {}).get("viewCount")
            thumb = best_thumbnail(v["snippet"].get("thumbnails", {}))
            if views is None or thumb is None:
                continue
            videos.append({
                "id": v["id"],
                "title": v["snippet"]["title"],
                "channel": channel_title,
                "thumbnail": thumb,
                "views": int(views),
            })
    return videos


# ---------------------------------------------------------------- sidebar
def secret_key() -> str:
    try:
        return st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        return ""


with st.sidebar:
    st.header("Setup")
    api_key = secret_key()
    if api_key:
        st.caption("🔑 API key loaded from secrets.")
    else:
        # Empty by default: never pre-fill a key into the page.
        api_key = st.text_input("YouTube API key", type="password",
                                help="Better: add YOUTUBE_API_KEY to your Streamlit secrets.")
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
            if len(pool) < 3:
                st.error("Need at least 3 videos with public view counts.")
            else:
                st.session_state.pool = pool
                st.success(f"Loaded {len(pool)} videos.")

    st.divider()
    st.caption(
        "This game uses YouTube API Services. By playing you agree to the "
        "[YouTube Terms of Service](https://www.youtube.com/t/terms). "
        "See the [Google Privacy Policy](https://policies.google.com/privacy). "
        "Not affiliated with or endorsed by YouTube."
    )

# ---------------------------------------------------------------- game (runs in the browser)
if "pool" not in st.session_state:
    st.title("🎬 Higher or Lower")
    st.info("Add some channel handles in the sidebar, then press **Load channels & start**.")
    st.stop()

GAME_HTML = r"""
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root{
    --bg:#0e1117; --panel:#161b26; --text:#f2f4f8; --muted:#9aa3b2;
    --good:#22c55e; --bad:#ef4444; --accent:#ff4b4b;
    --ease:cubic-bezier(.22,1,.36,1);
  }
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--text);
    font-family:"Source Sans Pro",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
  .wrap{max-width:1400px;margin:0 auto;padding:4px 8px}

  /* HUD */
  .hud{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:4px 12px 14px}
  .brand{font-size:28px;font-weight:800;letter-spacing:-.5px}
  .brand small{display:block;font-size:14px;font-weight:400;color:var(--muted);letter-spacing:0;margin-top:2px}
  .stats{display:flex;gap:28px}
  .stat{text-align:right}
  .stat .lbl{font-size:12px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted)}
  .stat .val{font-size:34px;font-weight:800;line-height:1;display:inline-block}
  .bump{animation:bump .45s var(--ease)}
  @keyframes bump{0%{transform:scale(1)}40%{transform:scale(1.45);color:var(--good)}100%{transform:scale(1)}}

  /* Stage + sliding cards */
  .stage{position:relative;overflow:hidden}
  .card{position:absolute;top:0;left:0;width:50%;padding:0 12px;border:0;background:none;color:inherit;
    text-align:left;font:inherit;cursor:pointer;
    transition:transform .65s var(--ease),opacity .65s var(--ease)}
  .card.left{transform:translateX(0)}
  .card.right{transform:translateX(100%)}
  .card.enter{transform:translateX(200%);opacity:0;transition:none}
  .card.exit{transform:translateX(-100%);opacity:0}
  .card:focus-visible{outline:none}
  .card:focus-visible .thumb{box-shadow:0 0 0 3px var(--accent)}

  .thumb{position:relative;aspect-ratio:16/9;border-radius:18px;overflow:hidden;background:#222;
    box-shadow:0 10px 30px rgba(0,0,0,.45);
    transition:transform .35s var(--ease),box-shadow .35s var(--ease)}
  .thumb img{width:100%;height:100%;object-fit:cover;display:block}
  .thumb::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;
    box-shadow:inset 0 0 0 0 transparent;transition:box-shadow .3s var(--ease)}
  .stage:not(.busy) .card:hover .thumb{transform:translateY(-8px) scale(1.02);
    box-shadow:0 22px 50px rgba(0,0,0,.6),0 0 0 3px rgba(255,255,255,.85)}
  .stage.busy .card{cursor:default}
  .card.picked .thumb{transform:scale(.985)}
  .card.good .thumb::after{box-shadow:inset 0 0 0 5px var(--good)}
  .card.bad  .thumb::after{box-shadow:inset 0 0 0 5px var(--bad)}
  .card.shake .thumb{animation:shake .5s}
  @keyframes shake{20%,60%{transform:translateX(-10px)}40%,80%{transform:translateX(10px)}}

  .meta{padding:14px 4px 0}
  .title{font-size:20px;font-weight:700;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;
    -webkit-box-orient:vertical;overflow:hidden;min-height:50px}
  .sub{display:flex;align-items:center;justify-content:space-between;margin-top:6px;color:var(--muted);font-size:15px}
  .sub a{color:var(--muted);text-decoration:none;font-size:13px}
  .sub a:hover{color:var(--text);text-decoration:underline}
  .views{margin-top:8px;font-size:38px;font-weight:800;letter-spacing:-.5px;font-variant-numeric:tabular-nums}
  .views .unit{font-size:18px;font-weight:600;color:var(--muted);letter-spacing:0}
  .views .q{color:var(--muted)}

  /* VS badge */
  .vs{position:absolute;left:50%;width:76px;height:76px;margin-left:-38px;border-radius:50%;z-index:5;
    display:grid;place-items:center;font-weight:900;font-size:24px;background:#fff;color:#111;
    box-shadow:0 8px 24px rgba(0,0,0,.5);pointer-events:none;
    transition:background .3s,color .3s,transform .4s var(--ease)}
  .vs.good{background:var(--good);color:#fff;transform:scale(1.15)}
  .vs.bad{background:var(--bad);color:#fff;transform:scale(1.15)}

  .hint{text-align:center;color:var(--muted);font-size:14px;margin-top:14px;transition:opacity .3s}
  .stage.busy ~ .hint{opacity:.3}

  /* Game over */
  .over{position:fixed;inset:0;display:grid;place-items:center;z-index:10;
    background:rgba(8,10,15,.6);backdrop-filter:blur(6px);
    opacity:0;pointer-events:none;transition:opacity .4s}
  .over.show{opacity:1;pointer-events:auto}
  .box{background:var(--panel);border-radius:22px;padding:32px 44px;text-align:center;min-width:300px;
    box-shadow:0 30px 80px rgba(0,0,0,.6);transform:translateY(20px) scale(.96);transition:transform .45s var(--ease)}
  .over.show .box{transform:none}
  .box .lbl{color:var(--muted);text-transform:uppercase;letter-spacing:2px;font-size:13px}
  .box .big{font-size:72px;font-weight:900;line-height:1.1;margin:6px 0}
  .box .nb{color:var(--good);font-weight:700;height:22px}
  .box button{margin-top:16px;border:0;border-radius:12px;padding:12px 28px;font:inherit;font-weight:700;
    font-size:17px;background:var(--accent);color:#fff;cursor:pointer;transition:transform .2s}
  .box button:hover{transform:scale(1.05)}

  @media (max-width:760px){
    .brand{font-size:20px}.brand small{display:none}
    .stat .val{font-size:26px}
    .card{padding:0 5px}
    .title{font-size:14px;min-height:36px}
    .views{font-size:20px}.views .unit{font-size:12px}
    .sub a{display:none}
    .vs{width:46px;height:46px;margin-left:-23px;font-size:15px}
  }
</style></head>
<body>
<div class="wrap">
  <div class="hud">
    <div class="brand">🎬 Higher or Lower<small>Click the video you think has more views</small></div>
    <div class="stats">
      <div class="stat"><div class="lbl">Score</div><div class="val" id="score">0</div></div>
      <div class="stat"><div class="lbl">Best</div><div class="val" id="best">0</div></div>
    </div>
  </div>
  <div class="stage" id="stage"><div class="vs" id="vs">VS</div></div>
  <div class="hint">Tip: use ← and → on your keyboard</div>
</div>
<div class="over" id="over"><div class="box">
  <div class="lbl">Final score</div>
  <div class="big" id="final">0</div>
  <div class="nb" id="newbest"></div>
  <button id="again">Play again</button>
</div></div>

<script>
const POOL = __DATA__;
const META_H = window.innerWidth <= 760 ? 110 : 165;
const stage = document.getElementById('stage');
const vs = document.getElementById('vs');
const scoreEl = document.getElementById('score');
const bestEl = document.getElementById('best');
let left, right, cardL, cardR, score = 0, busy = false, recent = [];
let best = 0;
try { best = parseInt(localStorage.getItem('hl_best') || '0', 10) || 0; } catch (e) {}
bestEl.textContent = best;

const fmt = n => n.toLocaleString('it-IT');

function pick() {
  // avoid repeating any of the last few videos
  const avoid = new Set(recent);
  let v, tries = 0;
  do { v = POOL[Math.floor(Math.random() * POOL.length)]; tries++; }
  while (avoid.has(v.id) && tries < 50);
  recent.push(v.id); if (recent.length > Math.min(20, POOL.length - 2)) recent.shift();
  new Image().src = v.thumbnail; // preload
  return v;
}

function makeCard(v, pos, reveal) {
  const c = document.createElement('div');
  c.className = 'card ' + pos;
  c.tabIndex = 0;
  c.setAttribute('role', 'button');
  c.innerHTML =
    '<div class="thumb"><img alt="" draggable="false"></div>' +
    '<div class="meta"><div class="title"></div>' +
    '<div class="sub"><span class="channel"></span><a target="_blank" rel="noopener">Watch on YouTube ↗</a></div>' +
    '<div class="views"><span class="num"></span> <span class="unit">views</span></div></div>';
  c.querySelector('img').src = v.thumbnail;
  c.querySelector('.title').textContent = v.title;      // textContent = safe from HTML in titles
  c.querySelector('.channel').textContent = v.channel;
  const a = c.querySelector('a');
  a.href = 'https://www.youtube.com/watch?v=' + encodeURIComponent(v.id);
  a.addEventListener('click', e => e.stopPropagation());
  const num = c.querySelector('.num');
  if (reveal) num.textContent = fmt(v.views);
  else { num.textContent = '???'; num.classList.add('q'); }
  c.addEventListener('click', () => choose(c === cardR ? 'right' : 'left'));
  stage.appendChild(c);
  return c;
}

function layout() {
  const cardW = stage.clientWidth / 2 - (window.innerWidth <= 760 ? 10 : 24);
  const imgH = cardW * 9 / 16;
  stage.style.height = (imgH + META_H + 12) + 'px';
  vs.style.top = (imgH / 2 - vs.offsetHeight / 2) + 'px';
}

function countUp(el, target, ms) {
  el.classList.remove('q');
  return new Promise(res => {
    const t0 = performance.now();
    const step = t => {
      const p = Math.min(1, (t - t0) / ms);
      const e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(Math.round(target * e));
      if (p < 1) requestAnimationFrame(step); else res();
    };
    requestAnimationFrame(step);
  });
}

function choose(side) {
  if (busy) return;
  busy = true;
  stage.classList.add('busy');
  const chosen = side === 'right' ? cardR : cardL;
  chosen.classList.add('picked');
  const correct = side === 'right' ? right.views >= left.views : left.views >= right.views;

  countUp(cardR.querySelector('.num'), right.views, 1100).then(() => {
    if (correct) {
      chosen.classList.add('good');
      vs.className = 'vs good'; vs.textContent = '✓';
      score++;
      scoreEl.textContent = score;
      scoreEl.classList.remove('bump'); void scoreEl.offsetWidth; scoreEl.classList.add('bump');
      if (score > best) {
        best = score; bestEl.textContent = best;
        try { localStorage.setItem('hl_best', String(best)); } catch (e) {}
      }
      setTimeout(advance, 850);
    } else {
      chosen.classList.add('bad', 'shake');
      vs.className = 'vs bad'; vs.textContent = '✗';
      setTimeout(gameOver, 1100);
    }
  });
}

function advance() {
  const old = cardL;
  old.className = 'card exit';
  cardR.className = 'card left';
  left = right;
  cardL = cardR;
  right = pick();
  cardR = makeCard(right, 'enter', false);
  void cardR.offsetWidth;                // force layout so the transition runs
  cardR.className = 'card right';
  vs.className = 'vs'; vs.textContent = 'VS';
  setTimeout(() => { old.remove(); busy = false; stage.classList.remove('busy'); }, 650);
}

function gameOver() {
  document.getElementById('final').textContent = score;
  document.getElementById('newbest').textContent = (score > 0 && score === best) ? '🏆 New best!' : '';
  document.getElementById('over').classList.add('show');
}

function start() {
  stage.querySelectorAll('.card').forEach(c => c.remove());
  document.getElementById('over').classList.remove('show');
  score = 0; scoreEl.textContent = 0; recent = [];
  vs.className = 'vs'; vs.textContent = 'VS';
  left = pick(); right = pick();
  cardL = makeCard(left, 'left', true);
  cardR = makeCard(right, 'right', false);
  busy = false; stage.classList.remove('busy');
  layout();
}

document.getElementById('again').addEventListener('click', start);
document.addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft') choose('left');
  if (e.key === 'ArrowRight') choose('right');
  if (e.key === 'Enter' && document.getElementById('over').classList.contains('show')) start();
});
window.addEventListener('resize', layout);
start();
</script>
</body></html>
"""

data = json.dumps(st.session_state.pool).replace("</", "<\\/")  # safe inside <script>
components.html(GAME_HTML.replace("__DATA__", data), height=720, scrolling=False)