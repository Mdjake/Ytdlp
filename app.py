from flask import Flask, request, jsonify, redirect
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
# URL SHORTENER (minimal — no extra response fields)
# =========================================================
SHORT_DB = {}
SHORT_TTL = 60 * 60 * 6  # 6 hours
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

def _cleanup():
    now = time.time()
    for c in [k for k, v in SHORT_DB.items() if v["expires"] < now]:
        SHORT_DB.pop(c, None)

def _shorten(long_url):
    """Return short URL or original if too short / empty."""
    if not long_url or not isinstance(long_url, str) or len(long_url) < 80:
        return long_url
    _cleanup()
    # reuse existing
    for c, v in SHORT_DB.items():
        if v["url"] == long_url and v["expires"] > time.time():
            return f"{PUBLIC_BASE_URL}/s/{c}" if PUBLIC_BASE_URL else f"/s/{c}"
    code = secrets.token_urlsafe(6)[:6].replace("-", "a").replace("_", "b")
    while code in SHORT_DB:
        code = secrets.token_urlsafe(6)[:6].replace("-", "a").replace("_", "b")
    SHORT_DB[code] = {"url": long_url, "expires": time.time() + SHORT_TTL}
    return f"{PUBLIC_BASE_URL}/s/{code}" if PUBLIC_BASE_URL else f"/s/{code}"

@app.route("/s/<code>", methods=["GET"])
def _short_redirect(code):
    _cleanup()
    entry = SHORT_DB.get(code)
    if not entry or entry["expires"] < time.time():
        return jsonify({"error": "Short link not found or expired"}), 404
    return redirect(entry["url"], code=302)

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
# YOUTUBE HELPERS
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
    return {
        "readable": " ".join(out) if out else "0s",
        "seconds": h * 3600 + m * 60 + s
    }

def get_direct_stream_single(video_id):
    try:
        payload = {"url": f"https://www.youtube.com/watch?v={video_id}"}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json'
        }
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
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
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
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
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
        future_to_id = {
            executor.submit(get_direct_stream_single, video_id): video_id
            for video_id in video_ids
        }
        for future in as_completed(future_to_id):
            video_id = future_to_id[future]
            try:
                results[video_id] = future.result(timeout=10)
            except Exception:
                results[video_id] = None
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
    return {
        "total_results": data.get("pageInfo", {}).get("totalResults", 0),
        "comments": comments
    }

def search_videos(query, max_results=10, order="relevance"):
    url = f"{YOUTUBE_SEARCH_API_URL}?part=snippet&q={urllib.parse.quote(query)}&maxResults={max_results}&order={order}&type=video&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    if r.status_code != 200:
        return {"error": f"Search API failed: {r.status_code}"}
    data = r.json()
    videos = []
    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        if video_id:
            snippet = item.get("snippet", {})
            videos.append({
                "video_id": video_id,
                "title": snippet.get("title", "N/A"),
                "description": snippet.get("description", "N/A"),
                "channel_id": snippet.get("channelId", "N/A"),
                "channel_title": snippet.get("channelTitle", "N/A"),
                "published_at": snippet.get("publishedAt", "N/A"),
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "N/A")
            })
    return {
        "total_results": data.get("pageInfo", {}).get("totalResults", 0),
        "videos": videos
    }

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
        item_snippet = item.get("snippet", {})
        item_content = item.get("contentDetails", {})
        videos.append({
            "title": item_snippet.get("title", "N/A"),
            "video_id": item_content.get("videoId", "N/A"),
            "position": item_snippet.get("position", 0),
            "channel_title": item_snippet.get("channelTitle", "N/A"),
            "published_at": item_snippet.get("publishedAt", "N/A"),
            "thumbnail": item_snippet.get("thumbnails", {}).get("high", {}).get("url", "N/A")
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
    if not videos:
        return videos
    video_ids = [v.get("video_id") for v in videos if v.get("video_id")]
    print(f"🔄 Fetching streams for {len(video_ids)} videos...")
    stream_results = get_streams_batch(video_ids)
    for video in videos:
        video_id = video.get("video_id")
        stream = stream_results.get(video_id)
        if stream:
            video["direct_stream"] = {
                "url": _shorten(stream.get("url")),
                "quality": stream.get("quality"),
                "height": stream.get("height"),
                "ext": stream.get("ext"),
                "format_id": stream.get("format_id"),
                "source": stream.get("source")
            }
            video["stream_available"] = True
        else:
            video["direct_stream"] = None
            video["stream_available"] = False
    print(f"✅ Streams fetched for {sum(1 for v in videos if v.get('stream_available'))} videos")
    return videos

# =========================================================
# API ENDPOINTS
# =========================================================
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "YouTube Complete API with Streams",
        "version": "4.1",
        "credit": "@ab_devs",
        "description": "Complete YouTube Data API + Direct Stream URLs (shortened)",
        "endpoints": {
            "/yt": {
                "method": "GET",
                "params": {"dl": "YouTube URL"},
                "example": "/yt?dl=https://www.youtube.com/watch?v=WOZwY8iEomg"
            },
            "/search": {
                "method": "GET",
                "params": {
                    "q": "Search query",
                    "max": "Max results (default: 10)",
                    "include_streams": "true/false (default: true)"
                },
                "example": "/search?q=Electrostatics+JEE&max=5"
            },
            "/channel": {
                "method": "GET",
                "params": {"id": "Channel ID"},
                "example": "/channel?id=UC_x5XG1OV2P6uZZ5FSM9Ttw"
            },
            "/comments": {
                "method": "GET",
                "params": {
                    "id": "Video ID or URL",
                    "max": "Max comments (default: 20)"
                },
                "example": "/comments?id=WOZwY8iEomg&max=10"
            },
            "/playlist": {
                "method": "GET",
                "params": {
                    "id": "Playlist ID or URL",
                    "include_streams": "true/false (default: true)"
                },
                "example": "/playlist?id=PLWwAq55NJFmDdY7XHbDYHq1Bp4bL1K3p"
            },
            "/related": {
                "method": "GET",
                "params": {
                    "id": "Video ID or URL",
                    "max": "Max results (default: 10)"
                },
                "example": "/related?id=WOZwY8iEomg&max=5"
            },
            "/batch": {
                "method": "GET",
                "params": {"ids": "comma-separated video IDs"},
                "example": "/batch?ids=WOZwY8iEomg,dQw4w9WgXcQ"
            },
            "/s/<code>": {
                "method": "GET",
                "desc": "Redirects to the full stream URL"
            }
        }
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
        response["direct_stream"] = {
            "url": _shorten(stream.get("url")),
            "quality": stream.get("quality"),
            "height": stream.get("height"),
            "ext": stream.get("ext"),
            "format_id": stream.get("format_id"),
            "source": stream.get("source")
        }
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
    channel_id = request.args.get("id", "").strip()
    if not channel_id:
        return jsonify({"error": "Missing id parameter"}), 400
    channel_data = fetch_channel_details(channel_id)
    if "error" in channel_data:
        return jsonify(channel_data), 404
    return jsonify(channel_data)

@app.route("/comments", methods=["GET"])
def comments():
    video_id_input = request.args.get("id", "").strip()
    max_results = int(request.args.get("max", 20))
    if not video_id_input:
        return jsonify({"error": "Missing id parameter"}), 400
    video_id = extract_video_id(video_id_input)
    if not video_id:
        if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id_input):
            video_id = video_id_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    comments_data = fetch_video_comments(video_id, max_results)
    if "error" in comments_data:
        return jsonify(comments_data), 400
    return jsonify(comments_data)

@app.route("/playlist", methods=["GET"])
def playlist():
    playlist_input = request.args.get("id", "").strip()
    include_streams = request.args.get("include_streams", "true").lower() == "true"
    if not playlist_input:
        return jsonify({"error": "Missing id parameter"}), 400
    playlist_id = extract_playlist_id(playlist_input)
    if not playlist_id:
        if re.match(r'^[a-zA-Z0-9_-]+$', playlist_input):
            playlist_id = playlist_input
        else:
            return jsonify({"error": "Invalid playlist ID or URL"}), 400
    playlist_data = fetch_playlist_details(playlist_id)
    if "error" in playlist_data:
        return jsonify(playlist_data), 404
    if include_streams and playlist_data.get("videos"):
        playlist_data["videos"] = add_streams_to_videos(playlist_data["videos"])
    return jsonify(playlist_data)

@app.route("/related", methods=["GET"])
def related():
    video_id_input = request.args.get("id", "").strip()
    max_results = int(request.args.get("max", 10))
    if not video_id_input:
        return jsonify({"error": "Missing id parameter"}), 400
    video_id = extract_video_id(video_id_input)
    if not video_id:
        if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id_input):
            video_id = video_id_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    results = search_videos(f"related:{video_id}", max_results)
    if "error" in results:
        return jsonify(results), 400
    videos = results.get("videos", [])
    if videos:
        videos = add_streams_to_videos(videos)
    return jsonify({
        "video_id": video_id,
        "total_results": results.get("total_results", 0),
        "returned_count": len(videos),
        "videos": videos
    })

@app.route("/batch", methods=["GET"])
def batch():
    ids_input = request.args.get("ids", "").strip()
    if not ids_input:
        return jsonify({"error": "Missing ids parameter"}), 400
    video_ids = [vid.strip() for vid in ids_input.split(",") if vid.strip()]
    if not video_ids:
        return jsonify({"error": "No valid video IDs"}), 400
    stream_results = get_streams_batch(video_ids)
    results = []
    for video_id in video_ids:
        stream = stream_results.get(video_id)
        video_data = {
            "video_id": video_id,
            "stream_available": stream is not None
        }
        if stream:
            video_data["direct_stream"] = {
                "url": _shorten(stream.get("url")),
                "quality": stream.get("quality"),
                "height": stream.get("height"),
                "ext": stream.get("ext"),
                "format_id": stream.get("format_id"),
                "source": stream.get("source")
            }
        else:
            video_data["direct_stream"] = None
        results.append(video_data)
    return jsonify({
        "total": len(results),
        "videos": results
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "version": "4.1",
        "features": [
            "Direct streams in ALL responses",
            "Shortened stream URLs",
            "Parallel processing",
            "Multiple fallback APIs",
            "All YouTube Data API endpoints"
        ]
    })

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🎯 YouTube Complete API v4.1 — SHORTENED STREAMS")
    print("=" * 80)
    print("   • direct_stream.url is auto-shortened to /s/<code>")
    print("   • No extra fields added to responses")
    print("   • Set PUBLIC_BASE_URL env var for absolute short links")
    print("\n" + "=" * 80 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
