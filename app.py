from flask import Flask, request, jsonify, redirect, abort
import requests
import re
import json
import urllib.parse
import secrets
import time
import os
from collections import OrderedDict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================
YOUTUBE_API_KEY = "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
YOUTUBE_SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_COMMENTS_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
YOUTUBE_PLAYLISTS_API_URL = "https://www.googleapis.com/youtube/v3/playlists"
YOUTUBE_PLAYLIST_ITEMS_API_URL = "https://www.googleapis.com/youtube/v3/playlistItems"

STREAM_APIS = [
    "https://www.clipto.com/api/youtube",
    "https://api.vevioz.com/api/button/mp3/{}",
    "https://yt-api.com/yt?url={}",
]

# =========================================================
# URL SHORTENER STORAGE
# =========================================================
# Simple in-memory store. In production use Redis / SQLite.
# Format: { code: {"url": str, "expires": float, "hits": int, "created": float} }
SHORT_DB = {}

# How long the short link itself stays alive (independent of googlevideo expire)
SHORT_TTL_SECONDS = 60 * 60 * 6      # 6 hours
SHORT_CODE_LEN = 6                    # e.g. /s/aB3xK9

# Base URL of THIS service — set this to your Vercel/Render domain after deploy.
# In local dev, leave as None and we'll derive it from the request.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", None)  # e.g. "https://ytdlp-ten.vercel.app"


def _cleanup_expired():
    """Drop expired short links to keep memory tidy."""
    now = time.time()
    expired = [c for c, v in SHORT_DB.items() if v["expires"] < now]
    for c in expired:
        SHORT_DB.pop(c, None)


def shorten_url(long_url: str, ttl_seconds: int = None) -> str:
    """
    Save long_url and return a clean short path like '/s/aB3xK9'.
    If the URL is already short or None, returns it untouched.
    """
    if not long_url or not isinstance(long_url, str):
        return long_url

    # Already short? Don't re-shorten
    if len(long_url) < 80:
        return long_url

    _cleanup_expired()

    # Reuse existing code if same URL already stored and still valid
    for code, entry in SHORT_DB.items():
        if entry["url"] == long_url and entry["expires"] > time.time():
            return f"/s/{code}"

    code = secrets.token_urlsafe(SHORT_CODE_LEN).replace("-", "a").replace("_", "b")[:SHORT_CODE_LEN]
    # Ensure uniqueness
    while code in SHORT_DB:
        code = secrets.token_urlsafe(SHORT_CODE_LEN).replace("-", "a").replace("_", "b")[:SHORT_CODE_LEN]

    ttl = ttl_seconds if ttl_seconds is not None else SHORT_TTL_SECONDS
    SHORT_DB[code] = {
        "url": long_url,
        "expires": time.time() + ttl,
        "hits": 0,
        "created": time.time(),
    }
    return f"/s/{code}"


def short_url_absolute(long_url: str) -> str:
    """Return absolute short URL (with base domain) — safest for WhatsApp."""
    path = shorten_url(long_url)
    if path == long_url:            # wasn't shortened
        return long_url
    base = PUBLIC_BASE_URL or request.host_url.rstrip("/")
    return f"{base}{path}"


def shorten_stream_obj(stream: dict) -> dict:
    """Given a direct_stream dict, replace .url with the short version."""
    if not stream or not stream.get("url"):
        return stream
    stream = dict(stream)  # copy
    stream["long_url"] = stream["url"]
    stream["url"] = short_url_absolute(stream["url"])
    stream["shortened"] = True
    return stream


# =========================================================
# YOUTUBE HELPERS (unchanged from your original)
# =========================================================
def extract_video_id(url):
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([^&?\s]+)',
        r'(?:https?://)?youtu\.be/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/([^&?\s]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_playlist_id(url):
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[^&]+&list=([^&?\s]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def parse_duration(duration):
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return {"readable": "N/A", "seconds": 0}
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    out = []
    if h: out.append(f"{h}h")
    if m: out.append(f"{m}m")
    if s: out.append(f"{s}s")
    return {"readable": " ".join(out) if out else "0s", "seconds": h * 3600 + m * 60 + s}


def get_direct_stream_single(video_id):
    # (exactly as your original — unchanged)
    try:
        payload = {"url": f"https://www.youtube.com/watch?v={video_id}"}
        headers = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}
        r = requests.post("https://www.clipto.com/api/youtube", json=payload, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data and data.get("medias"):
                audio_video_formats = ['18', '22', '37', '59', '78']
                best = None
                for fmt_id in audio_video_formats:
                    for media in data.get("medias", []):
                        if media.get('formatId') == fmt_id:
                            best = media
                            break
                    if best:
                        break
                if not best:
                    best = data.get("medias", [])[0] if data.get("medias") else None
                if best and best.get("url"):
                    return {
                        "url": best.get("url"),
                        "quality": best.get("quality") or best.get("label"),
                        "height": best.get("height"),
                        "ext": best.get("ext"),
                        "format_id": best.get("formatId"),
                        "source": "clipto"
                    }
    except:
        pass

    try:
        api_url = STREAM_APIS[1].format(video_id)
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(api_url, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get('url') or data.get('download_url'):
                return {
                    "url": data.get('url') or data.get('download_url'),
                    "quality": "audio",
                    "ext": "mp3",
                    "format_id": "audio",
                    "source": "vevioz"
                }
    except:
        pass

    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        encoded_url = urllib.parse.quote(video_url, safe='')
        api_url = STREAM_APIS[2].format(encoded_url)
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(api_url, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get('formats'):
                formats = data.get('formats', [])
                if formats:
                    return {
                        "url": formats[0].get("url"),
                        "quality": formats[0].get("qualityLabel"),
                        "height": formats[0].get("height"),
                        "ext": formats[0].get("ext"),
                        "format_id": formats[0].get("itag"),
                        "source": "yt-api"
                    }
            elif data.get('url'):
                return {
                    "url": data.get('url'),
                    "quality": data.get('qualityLabel', 'unknown'),
                    "height": data.get('height'),
                    "ext": data.get('ext', 'mp4'),
                    "format_id": data.get('itag', 'unknown'),
                    "source": "yt-api"
                }
    except:
        pass

    return None


def get_streams_batch(video_ids):
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {executor.submit(get_direct_stream_single, vid): vid for vid in video_ids}
        for future in as_completed(future_to_id):
            vid = future_to_id[future]
            try:
                results[vid] = future.result(timeout=10)
            except Exception:
                results[vid] = None
    return results


def fetch_youtube_details(video_id):
    url = f"{YOUTUBE_VIDEOS_API_URL}?part=snippet,statistics,contentDetails&id={video_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    if r.status_code != 200:
        return {"error": f"YouTube API failed: {r.status_code}"}
    data = r.json()
    if not data.get("items"):
        return {"error": "Video not found"}
    v = data["items"][0]
    snippet = v.get("snippet", {})
    stats = v.get("statistics", {})
    content = v.get("contentDetails", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title", "N/A"),
        "description": snippet.get("description", "N/A"),
        "channel_id": snippet.get("channelId", "N/A"),
        "channel_title": snippet.get("channelTitle", "N/A"),
        "published_at": snippet.get("publishedAt", "N/A"),
        "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "N/A"),
        "views": stats.get("viewCount", "0"),
        "likes": stats.get("likeCount", "0"),
        "comments": stats.get("commentCount", "0"),
        "duration": parse_duration(content.get("duration", "PT0S"))
    }


def fetch_channel_details(channel_id):
    url = f"{YOUTUBE_CHANNELS_API_URL}?part=snippet,statistics&id={channel_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    if r.status_code != 200:
        return {"error": f"Channel API failed: {r.status_code}"}
    data = r.json()
    if not data.get("items"):
        return {"error": "Channel not found"}
    c = data["items"][0]
    snippet = c.get("snippet", {})
    stats = c.get("statistics", {})
    return {
        "channel_id": channel_id,
        "title": snippet.get("title", "N/A"),
        "description": snippet.get("description", "N/A"),
        "custom_url": snippet.get("customUrl", "N/A"),
        "published_at": snippet.get("publishedAt", "N/A"),
        "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "N/A"),
        "subscribers": stats.get("subscriberCount", "0"),
        "views": stats.get("viewCount", "0"),
        "videos": stats.get("videoCount", "0")
    }


def fetch_video_comments(video_id, max_results=20):
    url = f"{YOUTUBE_COMMENTS_API_URL}?part=snippet&videoId={video_id}&maxResults={max_results}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    if r.status_code != 200:
        return {"error": f"Comments API failed: {r.status_code}"}
    data = r.json()
    comments = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        comments.append({
            "author": snippet.get("authorDisplayName", "N/A"),
            "text": snippet.get("textDisplay", "N/A"),
            "likes": snippet.get("likeCount", 0),
            "published_at": snippet.get("publishedAt", "N/A")
        })
    return {"total_results": data.get("pageInfo", {}).get("totalResults", 0), "comments": comments}


def search_videos(query, max_results=10, order="relevance"):
    url = f"{YOUTUBE_SEARCH_API_URL}?part=snippet&q={urllib.parse.quote(query)}&maxResults={max_results}&order={order}&type=video&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    if r.status_code != 200:
        return {"error": f"Search API failed: {r.status_code}"}
    data = r.json()
    videos = []
    for item in data.get("items", []):
        vid = item.get("id", {}).get("videoId")
        if vid:
            snippet = item.get("snippet", {})
            videos.append({
                "video_id": vid,
                "title": snippet.get("title", "N/A"),
                "description": snippet.get("description", "N/A"),
                "channel_id": snippet.get("channelId", "N/A"),
                "channel_title": snippet.get("channelTitle", "N/A"),
                "published_at": snippet.get("publishedAt", "N/A"),
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "N/A")
            })
    return {"total_results": data.get("pageInfo", {}).get("totalResults", 0), "videos": videos}


def fetch_playlist_details(playlist_id):
    url = f"{YOUTUBE_PLAYLISTS_API_URL}?part=snippet,contentDetails&id={playlist_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    if r.status_code != 200:
        return {"error": f"Playlist API failed: {r.status_code}"}
    data = r.json()
    if not data.get("items"):
        return {"error": "Playlist not found"}
    p = data["items"][0]
    snippet = p.get("snippet", {})
    content = p.get("contentDetails", {})
    items_url = f"{YOUTUBE_PLAYLIST_ITEMS_API_URL}?part=snippet,contentDetails&playlistId={playlist_id}&maxResults=50&key={YOUTUBE_API_KEY}"
    items_response = requests.get(items_url)
    items_data = items_response.json() if items_response.status_code == 200 else {}
    videos = []
    for item in items_data.get("items", []):
        s = item.get("snippet", {})
        c = item.get("contentDetails", {})
        videos.append({
            "title": s.get("title", "N/A"),
            "video_id": c.get("videoId", "N/A"),
            "position": s.get("position", 0),
            "channel_title": s.get("channelTitle", "N/A"),
            "published_at": s.get("publishedAt", "N/A"),
            "thumbnail": s.get("thumbnails", {}).get("high", {}).get("url", "N/A")
        })
    return {
        "playlist_id": playlist_id,
        "title": snippet.get("title", "N/A"),
        "description": snippet.get("description", "N/A"),
        "channel_id": snippet.get("channelId", "N/A"),
        "channel_title": snippet.get("channelTitle", "N/A"),
        "item_count": content.get("itemCount", 0),
        "videos": videos
    }


def add_streams_to_videos(videos):
    """Add streams in parallel, shortened."""
    if not videos:
        return videos
    video_ids = [v.get("video_id") for v in videos if v.get("video_id")]
    print(f"🔄 Fetching streams for {len(video_ids)} videos...")
    stream_results = get_streams_batch(video_ids)
    for video in videos:
        vid = video.get("video_id")
        stream = stream_results.get(vid)
        if stream:
            video["direct_stream"] = shorten_stream_obj({
                "url": stream.get("url"),
                "quality": stream.get("quality"),
                "height": stream.get("height"),
                "ext": stream.get("ext"),
                "format_id": stream.get("format_id"),
                "source": stream.get("source")
            })
            video["stream_available"] = True
        else:
            video["direct_stream"] = None
            video["stream_available"] = False
    print(f"✅ Streams fetched for {sum(1 for v in videos if v.get('stream_available'))}")
    return videos


# =========================================================
# ENDPOINTS
# =========================================================
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "YouTube Complete API with Streams + Shortener",
        "version": "4.1",
        "credit": "@ab_devs",
        "description": "Complete YouTube Data API + direct stream URLs + built-in shortener",
        "endpoints": {
            "/yt":        {"params": {"dl": "YouTube URL"}},
            "/search":    {"params": {"q": "query", "max": 10, "include_streams": True}},
            "/channel":   {"params": {"id": "Channel ID"}},
            "/comments":  {"params": {"id": "video ID/URL", "max": 20}},
            "/playlist":  {"params": {"id": "playlist ID/URL", "include_streams": True}},
            "/related":   {"params": {"id": "video ID/URL", "max": 10}},
            "/batch":     {"params": {"ids": "comma,separated,ids"}},
            "/shorten":   {"params": {"url": "long URL", "ttl": "optional seconds"}},
            "/s/<code>":  {"desc": "Redirects to the full stream URL"}
        }
    })


@app.route("/shorten", methods=["GET"])
def shorten_endpoint():
    """Manually shorten any URL. Returns the short code + absolute short URL."""
    long_url = request.args.get("url", "").strip()
    ttl = request.args.get("ttl", type=int)
    if not long_url:
        return jsonify({"error": "Missing url parameter"}), 400
    if not long_url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"}), 400

    path = shorten_url(long_url, ttl_seconds=ttl)
    base = PUBLIC_BASE_URL or request.host_url.rstrip("/")
    return jsonify({
        "long_url": long_url,
        "short_path": path,
        "short_url": f"{base}{path}",
        "expires_in_seconds": ttl if ttl else SHORT_TTL_SECONDS
    })


@app.route("/s/<code>", methods=["GET"])
def redirect_short(code):
    """Redirect a short code to the full stream URL."""
    _cleanup_expired()
    entry = SHORT_DB.get(code)
    if not entry:
        return jsonify({"error": "Short link not found or expired"}), 404
    if entry["expires"] < time.time():
        SHORT_DB.pop(code, None)
        return jsonify({"error": "Short link expired"}), 410

    entry["hits"] += 1

    # Redirect directly to the googlevideo URL.
    # 302 so we don't cache the redirect (googlevideo links expire).
    return redirect(entry["url"], code=302)


@app.route("/stats/<code>", methods=["GET"])
def short_stats(code):
    """Optional: check hit count / expiry of a short code."""
    entry = SHORT_DB.get(code)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    remaining = max(0, int(entry["expires"] - time.time()))
    return jsonify({
        "code": code,
        "hits": entry["hits"],
        "expires_in_seconds": remaining,
        "long_url_preview": entry["url"][:80] + ("..." if len(entry["url"]) > 80 else "")
    })


@app.route("/yt", methods=["GET"])
def yt_api():
    url = request.args.get("dl", "").strip()
    if not url:
        return jsonify({"error": "Missing dl parameter"}), 400
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    details = fetch_youtube_details(video_id)
    if "error" in details:
        return jsonify(details), 404

    stream = get_direct_stream_single(video_id)

    response = OrderedDict()
    response["video_id"] = video_id
    response["title"] = details.get("title")
    response["channel"] = details.get("channel_title")
    response["channel_id"] = details.get("channel_id")
    response["description"] = details.get("description")
    response["thumbnail"] = details.get("thumbnail")
    response["duration"] = details.get("duration", {}).get("readable")
    response["duration_seconds"] = details.get("duration", {}).get("seconds")
    response["published_at"] = details.get("published_at")
    response["views"] = details.get("views")
    response["likes"] = details.get("likes")
    response["comments"] = details.get("comments")

    if stream:
        response["direct_stream"] = shorten_stream_obj(stream)
        response["stream_available"] = True
    else:
        response["direct_stream"] = None
        response["stream_available"] = False

    return jsonify(response)


@app.route("/search", methods=["GET"])
def search():
    query = request.args.get("q", "").strip()
    max_results = int(request.args.get("max", 10))
    order = request.args.get("order", "relevance")
    include_streams = request.args.get("include_streams", "true").lower() == "true"
    if not query:
        return jsonify({"error": "Missing q parameter"}), 400
    results = search_videos(query, max_results, order)
    if "error" in results:
        return jsonify(results), 400
    videos = results.get("videos", [])
    if include_streams and videos:
        videos = add_streams_to_videos(videos)
    return jsonify({
        "query": query,
        "total_results": results.get("total_results", 0),
        "returned_count": len(videos),
        "videos": videos
    })


@app.route("/channel", methods=["GET"])
def channel():
    cid = request.args.get("id", "").strip()
    if not cid:
        return jsonify({"error": "Missing id parameter"}), 400
    data = fetch_channel_details(cid)
    if "error" in data:
        return jsonify(data), 404
    return jsonify(data)


@app.route("/comments", methods=["GET"])
def comments():
    vid_input = request.args.get("id", "").strip()
    max_results = int(request.args.get("max", 20))
    if not vid_input:
        return jsonify({"error": "Missing id parameter"}), 400
    vid = extract_video_id(vid_input)
    if not vid:
        if re.match(r'^[a-zA-Z0-9_-]{11}$', vid_input):
            vid = vid_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    data = fetch_video_comments(vid, max_results)
    if "error" in data:
        return jsonify(data), 400
    return jsonify(data)


@app.route("/playlist", methods=["GET"])
def playlist():
    pl_input = request.args.get("id", "").strip()
    include_streams = request.args.get("include_streams", "true").lower() == "true"
    if not pl_input:
        return jsonify({"error": "Missing id parameter"}), 400
    pl = extract_playlist_id(pl_input)
    if not pl:
        if re.match(r'^[a-zA-Z0-9_-]+$', pl_input):
            pl = pl_input
        else:
            return jsonify({"error": "Invalid playlist ID or URL"}), 400
    data = fetch_playlist_details(pl)
    if "error" in data:
        return jsonify(data), 404
    if include_streams and data.get("videos"):
        data["videos"] = add_streams_to_videos(data["videos"])
    return jsonify(data)


@app.route("/related", methods=["GET"])
def related():
    vid_input = request.args.get("id", "").strip()
    max_results = int(request.args.get("max", 10))
    if not vid_input:
        return jsonify({"error": "Missing id parameter"}), 400
    vid = extract_video_id(vid_input)
    if not vid:
        if re.match(r'^[a-zA-Z0-9_-]{11}$', vid_input):
            vid = vid_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    results = search_videos(f"related:{vid}", max_results)
    if "error" in results:
        return jsonify(results), 400
    videos = results.get("videos", [])
    if videos:
        videos = add_streams_to_videos(videos)
    return jsonify({
        "video_id": vid,
        "total_results": results.get("total_results", 0),
        "returned_count": len(videos),
        "videos": videos
    })


@app.route("/batch", methods=["GET"])
def batch():
    ids_input = request.args.get("ids", "").strip()
    if not ids_input:
        return jsonify({"error": "Missing ids parameter"}), 400
    ids = [i.strip() for i in ids_input.split(",") if i.strip()]
    if not ids:
        return jsonify({"error": "No valid video IDs"}), 400
    stream_results = get_streams_batch(ids)
    out = []
    for vid in ids:
        s = stream_results.get(vid)
        entry = {"video_id": vid, "stream_available": s is not None}
        if s:
            entry["direct_stream"] = shorten_stream_obj(s)
        else:
            entry["direct_stream"] = None
        out.append(entry)
    return jsonify({"total": len(out), "videos": out})


@app.route("/health", methods=["GET"])
def health():
    _cleanup_expired()
    return jsonify({
        "status": "healthy",
        "version": "4.1",
        "active_short_links": len(SHORT_DB),
        "features": [
            "Direct streams in all responses",
            "Auto-shortening of stream URLs",
            "Self-hosted shortener (/s/<code>)",
            "Parallel processing",
            "Multiple fallback APIs"
        ]
    })


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🎯 YouTube Complete API v4.1 — STREAMS + SHORTENER")
    print("=" * 80)
    print("✨ New in 4.1:")
    print("   • /shorten?url=...  →  returns short URL")
    print("   • /s/<code>         →  302 redirect to full stream")
    print("   • /stats/<code>     →  hit count + expiry")
    print("   • All direct_stream.url fields auto-shortened")
    print("\n⚙️  Env var PUBLIC_BASE_URL=... controls short link domain")
    print("=" * 80 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
