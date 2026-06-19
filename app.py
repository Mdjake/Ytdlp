from flask import Flask, request, jsonify
import requests
import re
import json
import urllib.parse
from collections import OrderedDict
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

YOUTUBE_API_KEY = "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
YOUTUBE_SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_COMMENTS_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
YOUTUBE_PLAYLISTS_API_URL = "https://www.googleapis.com/youtube/v3/playlists"
YOUTUBE_PLAYLIST_ITEMS_API_URL = "https://www.googleapis.com/youtube/v3/playlistItems"

# Multiple stream APIs for fallback
STREAM_APIS = [
    "https://www.clipto.com/api/youtube",
    "https://api.vevioz.com/api/button/mp3/{}",
    "https://yt-api.com/yt?url={}",
]

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
    """Get direct stream for a single video with fallbacks"""
    try:
        # Try clipto.com
        payload = {"url": f"https://www.youtube.com/watch?v={video_id}"}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json'
        }
        r = requests.post("https://www.clipto.com/api/youtube", json=payload, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data and data.get("medias"):
                # Find best quality with audio
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
    
    # Try vevioz (audio)
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
    
    # Try yt-api.com
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
    
    # Fallback: return None
    return None

def get_streams_batch(video_ids):
    """Get direct streams for multiple videos in parallel"""
    results = {}
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {
            executor.submit(get_direct_stream_single, video_id): video_id 
            for video_id in video_ids
        }
        
        for future in as_completed(future_to_id):
            video_id = future_to_id[future]
            try:
                stream = future.result(timeout=10)
                results[video_id] = stream
            except Exception as e:
                results[video_id] = None
    
    return results

def fetch_youtube_details(video_id):
    """Fetch video metadata"""
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
    """Fetch channel details"""
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
    """Fetch comments for a video"""
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
    """Search for videos"""
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
    """Fetch playlist details and items"""
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
    
    # Get playlist items
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
    """Add direct streams to a list of videos"""
    if not videos:
        return videos
    
    # Get all video IDs
    video_ids = [v.get("video_id") for v in videos if v.get("video_id")]
    
    # Get streams in parallel
    print(f"🔄 Fetching streams for {len(video_ids)} videos...")
    stream_results = get_streams_batch(video_ids)
    
    # Add streams to videos
    for video in videos:
        video_id = video.get("video_id")
        stream = stream_results.get(video_id)
        
        if stream:
            video["direct_stream"] = {
                "url": stream.get("url"),
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

# ====================== API ENDPOINTS ======================

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "YouTube Complete API with Streams",
        "version": "4.0",
        "credit": "@ab_devs",
        "description": "Complete YouTube Data API + Direct Stream URLs for ALL endpoints",
        "features": [
            "Direct streams in EVERY response",
            "Parallel stream fetching",
            "Multiple fallback APIs",
            "Full YouTube Data API features"
        ],
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
            }
        }
    })

@app.route("/yt", methods=["GET"])
def yt_api():
    """Get video details + direct stream"""
    url = request.args.get("dl", "").strip()
    
    if not url:
        return jsonify({"error": "Missing dl parameter"}), 400
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch video details
    details = fetch_youtube_details(video_id)
    if "error" in details:
        return jsonify(details), 404
    
    # Get direct stream
    stream = get_direct_stream_single(video_id)
    
    # Build response
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
            "url": stream.get("url"),
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
    """Search videos with direct streams"""
    query = request.args.get("q", "").strip()
    max_results = int(request.args.get("max", 10))
    order = request.args.get("order", "relevance")
    include_streams = request.args.get("include_streams", "true").lower() == "true"
    
    if not query:
        return jsonify({"error": "Missing q parameter"}), 400
    
    # Search for videos
    results = search_videos(query, max_results, order)
    if "error" in results:
        return jsonify(results), 400
    
    videos = results.get("videos", [])
    
    # Add streams if requested
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
    """Get channel details"""
    channel_id = request.args.get("id", "").strip()
    
    if not channel_id:
        return jsonify({"error": "Missing id parameter"}), 400
    
    channel_data = fetch_channel_details(channel_id)
    if "error" in channel_data:
        return jsonify(channel_data), 404
    
    return jsonify(channel_data)

@app.route("/comments", methods=["GET"])
def comments():
    """Get video comments"""
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
    """Get playlist details with direct streams for each video"""
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
    
    # Add streams to playlist videos
    if include_streams and playlist_data.get("videos"):
        playlist_data["videos"] = add_streams_to_videos(playlist_data["videos"])
    
    return jsonify(playlist_data)

@app.route("/related", methods=["GET"])
def related():
    """Get related videos with direct streams"""
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
    
    # Use search to find related videos
    results = search_videos(f"related:{video_id}", max_results)
    if "error" in results:
        return jsonify(results), 400
    
    videos = results.get("videos", [])
    
    # Add streams
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
    """Get direct streams for multiple videos"""
    ids_input = request.args.get("ids", "").strip()
    
    if not ids_input:
        return jsonify({"error": "Missing ids parameter"}), 400
    
    video_ids = [id.strip() for id in ids_input.split(",") if id.strip()]
    
    if not video_ids:
        return jsonify({"error": "No valid video IDs"}), 400
    
    # Get streams in parallel
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
                "url": stream.get("url"),
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
        "version": "4.0",
        "features": [
            "Direct streams in ALL responses",
            "Parallel processing",
            "Multiple fallback APIs",
            "All YouTube Data API endpoints"
        ]
    })

if __name__ == "__main__":
    print("\n" + "="*80)
    print("🎯 YouTube Complete API v4.0 - STREAMS IN ALL RESPONSES")
    print("="*80)
    print("✨ Features:")
    print("   • Direct streams in EVERY endpoint")
    print("   • Parallel stream fetching for speed")
    print("   • Multiple fallback APIs")
    print("   • All YouTube Data API features")
    print("\n📌 Endpoints (ALL return direct streams):")
    print("   /yt        - Single video + stream")
    print("   /search    - Search + streams for ALL videos")
    print("   /playlist  - Playlist + streams for ALL videos")
    print("   /related   - Related videos + streams")
    print("   /batch     - Multiple videos + streams")
    print("   /channel   - Channel details")
    print("   /comments  - Video comments")
    print("\n📖 Examples:")
    print("   /search?q=Electrostatics+JEE&max=5")
    print("   /playlist?id=PLWwAq55NJFmDdY7XHbDYHq1Bp4bL1K3p")
    print("   /related?id=WOZwY8iEomg&max=5")
    print("   /batch?ids=WOZwY8iEomg,dQw4w9WgXcQ")
    print("\n" + "="*80 + "\n")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
