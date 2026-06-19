from flask import Flask, request, jsonify
import requests
import re
import json
from collections import OrderedDict
import urllib.parse
from datetime import datetime

app = Flask(__name__)

# API Keys and URLs
YOUTUBE_API_KEY = "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
YOUTUBE_SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_COMMENTS_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
YOUTUBE_PLAYLISTS_API_URL = "https://www.googleapis.com/youtube/v3/playlists"
YOUTUBE_PLAYLIST_ITEMS_API_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
YTDLP_API = "https://ytdlp-ten.vercel.app/yt?dl={}"

def extract_video_id(url):
    """Extract YouTube video ID from various URL formats"""
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
    """Extract YouTube playlist ID from URL"""
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
    """Convert ISO 8601 duration to readable format and seconds"""
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

def get_video_details(video_id, parts=None):
    """Fetch comprehensive video details from YouTube API"""
    if parts is None:
        parts = "snippet,contentDetails,statistics,topicDetails,status,recordingDetails,player,fileDetails,processingDetails"
    
    url = f"{YOUTUBE_VIDEOS_API_URL}?part={parts}&id={video_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"YouTube API failed: {r.status_code}"}
    
    data = r.json()
    if not data.get("items"):
        return {"error": "Video not found"}
    
    v = data["items"][0]
    
    # Comprehensive video data extraction
    video_data = {
        # Basic Info
        "id": video_id,
        "title": v.get("snippet", {}).get("title", "N/A"),
        "description": v.get("snippet", {}).get("description", "N/A"),
        "channel_id": v.get("snippet", {}).get("channelId", "N/A"),
        "channel_title": v.get("snippet", {}).get("channelTitle", "N/A"),
        
        # Thumbnails (all sizes)
        "thumbnails": v.get("snippet", {}).get("thumbnails", {}),
        
        # Timing
        "published_at": v.get("snippet", {}).get("publishedAt", "N/A"),
        "duration": parse_duration(v.get("contentDetails", {}).get("duration", "PT0S")),
        
        # Statistics
        "statistics": {
            "views": int(v.get("statistics", {}).get("viewCount", 0)),
            "likes": int(v.get("statistics", {}).get("likeCount", 0)),
            "dislikes": int(v.get("statistics", {}).get("dislikeCount", 0)),
            "favorites": int(v.get("statistics", {}).get("favoriteCount", 0)),
            "comments": int(v.get("statistics", {}).get("commentCount", 0))
        },
        
        # Content Details
        "content_details": {
            "duration_iso": v.get("contentDetails", {}).get("duration", "N/A"),
            "dimension": v.get("contentDetails", {}).get("dimension", "N/A"),
            "definition": v.get("contentDetails", {}).get("definition", "N/A"),
            "caption": v.get("contentDetails", {}).get("caption", "N/A"),
            "licensed_content": v.get("contentDetails", {}).get("licensedContent", False),
            "projection": v.get("contentDetails", {}).get("projection", "N/A")
        },
        
        # Status
        "status": {
            "upload_status": v.get("status", {}).get("uploadStatus", "N/A"),
            "privacy_status": v.get("status", {}).get("privacyStatus", "N/A"),
            "license": v.get("status", {}).get("license", "N/A"),
            "embeddable": v.get("status", {}).get("embeddable", False),
            "public_stats_viewable": v.get("status", {}).get("publicStatsViewable", False)
        },
        
        # Categories & Tags
        "category_id": v.get("snippet", {}).get("categoryId", "N/A"),
        "tags": v.get("snippet", {}).get("tags", []),
        
        # Topic Details (if available)
        "topic_details": {
            "topic_categories": v.get("topicDetails", {}).get("topicCategories", []),
            "relevant_topic_ids": v.get("topicDetails", {}).get("relevantTopicIds", [])
        },
        
        # Recording Details (if available)
        "recording_details": {
            "location": v.get("recordingDetails", {}).get("location", {}),
            "location_description": v.get("recordingDetails", {}).get("locationDescription", "N/A"),
            "recording_date": v.get("recordingDetails", {}).get("recordingDate", "N/A")
        },
        
        # Live Streaming Info
        "live_streaming": {
            "actual_start_time": v.get("liveStreamingDetails", {}).get("actualStartTime", "N/A"),
            "actual_end_time": v.get("liveStreamingDetails", {}).get("actualEndTime", "N/A"),
            "scheduled_start_time": v.get("liveStreamingDetails", {}).get("scheduledStartTime", "N/A"),
            "scheduled_end_time": v.get("liveStreamingDetails", {}).get("scheduledEndTime", "N/A"),
            "concurrent_viewers": v.get("liveStreamingDetails", {}).get("concurrentViewers", 0)
        }
    }
    
    return video_data

def get_channel_details(channel_id):
    """Fetch channel details from YouTube API"""
    url = f"{YOUTUBE_CHANNELS_API_URL}?part=snippet,statistics,brandingSettings,contentDetails,topicDetails,status&id={channel_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"YouTube API failed: {r.status_code}"}
    
    data = r.json()
    if not data.get("items"):
        return {"error": "Channel not found"}
    
    c = data["items"][0]
    
    return {
        "id": channel_id,
        "title": c.get("snippet", {}).get("title", "N/A"),
        "description": c.get("snippet", {}).get("description", "N/A"),
        "custom_url": c.get("snippet", {}).get("customUrl", "N/A"),
        "published_at": c.get("snippet", {}).get("publishedAt", "N/A"),
        "thumbnails": c.get("snippet", {}).get("thumbnails", {}),
        "country": c.get("snippet", {}).get("country", "N/A"),
        "statistics": {
            "subscribers": int(c.get("statistics", {}).get("subscriberCount", 0)),
            "views": int(c.get("statistics", {}).get("viewCount", 0)),
            "videos": int(c.get("statistics", {}).get("videoCount", 0))
        },
        "branding": {
            "keywords": c.get("brandingSettings", {}).get("channel", {}).get("keywords", ""),
            "unsubscribed_trailer": c.get("brandingSettings", {}).get("channel", {}).get("unsubscribedTrailer", "N/A"),
            "profile_color": c.get("brandingSettings", {}).get("channel", {}).get("profileColor", "N/A"),
            "image_banner": c.get("brandingSettings", {}).get("image", {}).get("bannerExternalUrl", "N/A")
        },
        "topic_details": {
            "topic_categories": c.get("topicDetails", {}).get("topicCategories", []),
        },
        "status": {
            "is_linked": c.get("status", {}).get("isLinked", False),
            "long_uploads_status": c.get("status", {}).get("longUploadsStatus", "N/A"),
            "made_for_kids": c.get("status", {}).get("madeForKids", False),
            "self_declared_made_for_kids": c.get("status", {}).get("selfDeclaredMadeForKids", False)
        }
    }

def get_comments(video_id, max_results=20):
    """Fetch comments for a video"""
    url = f"{YOUTUBE_COMMENTS_API_URL}?part=snippet&videoId={video_id}&maxResults={max_results}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"Failed to fetch comments: {r.status_code}"}
    
    data = r.json()
    comments = []
    
    for item in data.get("items", []):
        snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        comments.append({
            "author": snippet.get("authorDisplayName", "N/A"),
            "author_channel_id": snippet.get("authorChannelId", {}).get("value", "N/A"),
            "text": snippet.get("textDisplay", "N/A"),
            "likes": snippet.get("likeCount", 0),
            "published_at": snippet.get("publishedAt", "N/A"),
            "updated_at": snippet.get("updatedAt", "N/A")
        })
    
    return {
        "total_results": data.get("pageInfo", {}).get("totalResults", 0),
        "comments": comments
    }

def search_videos(query, max_results=10, order="relevance"):
    """Search for videos using YouTube API"""
    url = f"{YOUTUBE_SEARCH_API_URL}?part=snippet&q={urllib.parse.quote(query)}&maxResults={max_results}&order={order}&type=video&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"Search failed: {r.status_code}"}
    
    data = r.json()
    videos = []
    
    for item in data.get("items", []):
        videos.append({
            "id": item.get("id", {}).get("videoId", "N/A"),
            "title": item.get("snippet", {}).get("title", "N/A"),
            "description": item.get("snippet", {}).get("description", "N/A"),
            "channel_id": item.get("snippet", {}).get("channelId", "N/A"),
            "channel_title": item.get("snippet", {}).get("channelTitle", "N/A"),
            "published_at": item.get("snippet", {}).get("publishedAt", "N/A"),
            "thumbnail": item.get("snippet", {}).get("thumbnails", {}).get("high", {}).get("url", "N/A")
        })
    
    return {
        "total_results": data.get("pageInfo", {}).get("totalResults", 0),
        "videos": videos
    }

def get_playlist_details(playlist_id):
    """Fetch playlist details from YouTube API"""
    url = f"{YOUTUBE_PLAYLISTS_API_URL}?part=snippet,contentDetails,status&id={playlist_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"Failed to fetch playlist: {r.status_code}"}
    
    data = r.json()
    if not data.get("items"):
        return {"error": "Playlist not found"}
    
    p = data["items"][0]
    
    # Get playlist items
    items_url = f"{YOUTUBE_PLAYLIST_ITEMS_API_URL}?part=snippet,contentDetails,status&playlistId={playlist_id}&maxResults=50&key={YOUTUBE_API_KEY}"
    items_response = requests.get(items_url)
    items_data = items_response.json() if items_response.status_code == 200 else {}
    
    videos = []
    for item in items_data.get("items", []):
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        videos.append({
            "title": snippet.get("title", "N/A"),
            "video_id": content_details.get("videoId", "N/A"),
            "position": snippet.get("position", 0),
            "channel_title": snippet.get("channelTitle", "N/A"),
            "published_at": snippet.get("publishedAt", "N/A"),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "N/A")
        })
    
    return {
        "id": playlist_id,
        "title": p.get("snippet", {}).get("title", "N/A"),
        "description": p.get("snippet", {}).get("description", "N/A"),
        "channel_id": p.get("snippet", {}).get("channelId", "N/A"),
        "channel_title": p.get("snippet", {}).get("channelTitle", "N/A"),
        "published_at": p.get("snippet", {}).get("publishedAt", "N/A"),
        "thumbnails": p.get("snippet", {}).get("thumbnails", {}),
        "item_count": p.get("contentDetails", {}).get("itemCount", 0),
        "privacy_status": p.get("status", {}).get("privacyStatus", "N/A"),
        "videos": videos
    }

def get_stream_links(video_url):
    """Get direct stream links from ytdlp API"""
    try:
        encoded_url = urllib.parse.quote(video_url, safe='')
        api_url = YTDLP_API.format(encoded_url)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return {"error": f"Stream API returned {response.status_code}"}
        
        data = response.json()
        
        if data.get("download", {}).get("error", False):
            return {"error": "Stream extraction failed"}
        
        return data.get("download", {})
        
    except Exception as e:
        return {"error": f"Stream extraction error: {str(e)}"}

@app.route("/", methods=["GET"])
def index():
    """API information and all available endpoints"""
    return jsonify({
        "name": "YouTube Complete API",
        "version": "3.0",
        "description": "Full YouTube Data API + Direct Stream Links",
        "credit": "YouTube Data API v3 + ytdlp",
        "endpoints": {
            "/video": {
                "method": "GET",
                "params": {
                    "id": "Video ID or URL",
                    "include_stream": "true/false (default: false)",
                    "include_comments": "true/false (default: false)",
                    "include_channel": "true/false (default: false)"
                },
                "example": "/video?id=https://www.youtube.com/watch?v=WOZwY8iEomg&include_stream=true"
            },
            "/channel": {
                "method": "GET",
                "params": {"id": "Channel ID"},
                "example": "/channel?id=UC_x5XG1OV2P6uZZ5FSM9Ttw"
            },
            "/search": {
                "method": "GET",
                "params": {
                    "q": "Search query",
                    "max": "Max results (default: 10)",
                    "order": "relevance/date/rating/viewCount"
                },
                "example": "/search?q=Electrostatics JEE&max=5"
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
                "params": {"id": "Playlist ID or URL"},
                "example": "/playlist?id=PLWwAq55NJFmDdY7XHbDYHq1Bp4bL1K3p"
            },
            "/stream": {
                "method": "GET",
                "params": {
                    "id": "Video ID or URL",
                    "format": "best/audio/video (default: best)"
                },
                "example": "/stream?id=https://www.youtube.com/watch?v=WOZwY8iEomg"
            },
            "/full": {
                "method": "GET",
                "params": {
                    "id": "Video ID or URL",
                    "include_comments": "true/false"
                },
                "example": "/full?id=WOZwY8iEomg&include_comments=true"
            }
        }
    })

@app.route("/video", methods=["GET"])
def get_video():
    """Get comprehensive video details"""
    video_id_input = request.args.get("id", "").strip()
    include_stream = request.args.get("include_stream", "false").lower() == "true"
    include_comments = request.args.get("include_comments", "false").lower() == "true"
    include_channel = request.args.get("include_channel", "false").lower() == "true"
    
    if not video_id_input:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    
    # Extract video ID if URL provided
    video_id = extract_video_id(video_id_input)
    if not video_id:
        # Try using as-is if it looks like an ID
        if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id_input):
            video_id = video_id_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    
    # Get video details
    video_data = get_video_details(video_id)
    if "error" in video_data:
        return jsonify(video_data), 404
    
    response = OrderedDict()
    response["video"] = video_data
    
    # Include stream if requested
    if include_stream:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        stream_data = get_stream_links(video_url)
        response["stream"] = stream_data if "error" not in stream_data else {"error": stream_data.get("error")}
    
    # Include comments if requested
    if include_comments:
        comments_data = get_comments(video_id)
        response["comments"] = comments_data if "error" not in comments_data else {"error": comments_data.get("error")}
    
    # Include channel if requested
    if include_channel and video_data.get("channel_id"):
        channel_data = get_channel_details(video_data["channel_id"])
        response["channel"] = channel_data if "error" not in channel_data else {"error": channel_data.get("error")}
    
    return jsonify(response)

@app.route("/channel", methods=["GET"])
def get_channel():
    """Get channel details"""
    channel_id = request.args.get("id", "").strip()
    
    if not channel_id:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    
    channel_data = get_channel_details(channel_id)
    if "error" in channel_data:
        return jsonify(channel_data), 404
    
    return jsonify(channel_data)

@app.route("/search", methods=["GET"])
def search():
    """Search for videos"""
    query = request.args.get("q", "").strip()
    max_results = int(request.args.get("max", 10))
    order = request.args.get("order", "relevance")
    
    if not query:
        return jsonify({"error": "Missing 'q' parameter"}), 400
    
    results = search_videos(query, max_results, order)
    if "error" in results:
        return jsonify(results), 400
    
    return jsonify(results)

@app.route("/comments", methods=["GET"])
def get_video_comments():
    """Get video comments"""
    video_id_input = request.args.get("id", "").strip()
    max_results = int(request.args.get("max", 20))
    
    if not video_id_input:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    
    video_id = extract_video_id(video_id_input)
    if not video_id:
        if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id_input):
            video_id = video_id_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    
    comments = get_comments(video_id, max_results)
    if "error" in comments:
        return jsonify(comments), 400
    
    return jsonify(comments)

@app.route("/playlist", methods=["GET"])
def get_playlist():
    """Get playlist details"""
    playlist_input = request.args.get("id", "").strip()
    
    if not playlist_input:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    
    playlist_id = extract_playlist_id(playlist_input)
    if not playlist_id:
        # Try using as-is if it looks like a playlist ID
        if re.match(r'^[a-zA-Z0-9_-]+$', playlist_input):
            playlist_id = playlist_input
        else:
            return jsonify({"error": "Invalid playlist ID or URL"}), 400
    
    playlist_data = get_playlist_details(playlist_id)
    if "error" in playlist_data:
        return jsonify(playlist_data), 404
    
    return jsonify(playlist_data)

@app.route("/stream", methods=["GET"])
def get_stream():
    """Get direct stream links only"""
    video_id_input = request.args.get("id", "").strip()
    format_type = request.args.get("format", "best").lower()
    
    if not video_id_input:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    
    video_id = extract_video_id(video_id_input)
    if not video_id:
        if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id_input):
            video_id = video_id_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    stream_data = get_stream_links(video_url)
    
    if "error" in stream_data:
        return jsonify({"error": stream_data["error"]}), 500
    
    medias = stream_data.get("medias", [])
    
    # Filter based on format preference
    if format_type == "audio":
        audio_streams = [m for m in medias if m.get('type') == 'audio' or m.get('formatId') in ['139', '140', '141', '251']]
        best = audio_streams[0] if audio_streams else None
    elif format_type == "video":
        video_streams = [m for m in medias if m.get('type') == 'video']
        best = video_streams[0] if video_streams else None
    else:  # best
        # Prioritize formats with audio
        audio_video_formats = ['18', '22', '37', '59', '78']
        for fmt_id in audio_video_formats:
            for media in medias:
                if media.get('formatId') == fmt_id:
                    best = media
                    break
            else:
                continue
            break
        else:
            best = medias[0] if medias else None
    
    if best:
        return jsonify({
            "video_id": video_id,
            "format_type": format_type,
            "stream_url": best.get("url"),
            "quality": best.get("quality") or best.get("label"),
            "height": best.get("height"),
            "ext": best.get("ext"),
            "format_id": best.get("formatId"),
            "has_audio": "audio" in best.get("mimeType", "").lower() or best.get('type') == 'audio'
        })
    else:
        return jsonify({"error": "No stream found"}), 404

@app.route("/full", methods=["GET"])
def get_full_video_info():
    """Get everything: video details + stream + comments + channel"""
    video_id_input = request.args.get("id", "").strip()
    include_comments = request.args.get("include_comments", "true").lower() == "true"
    
    if not video_id_input:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    
    video_id = extract_video_id(video_id_input)
    if not video_id:
        if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id_input):
            video_id = video_id_input
        else:
            return jsonify({"error": "Invalid video ID or URL"}), 400
    
    response = OrderedDict()
    response["video_id"] = video_id
    response["url"] = f"https://www.youtube.com/watch?v={video_id}"
    
    # Get video details
    video_data = get_video_details(video_id)
    if "error" in video_data:
        return jsonify(video_data), 404
    response["details"] = video_data
    
    # Get stream links
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    stream_data = get_stream_links(video_url)
    if "error" not in stream_data:
        medias = stream_data.get("medias", [])
        # Get best stream with audio
        audio_video_formats = ['18', '22', '37', '59', '78']
        best = None
        for fmt_id in audio_video_formats:
            for media in medias:
                if media.get('formatId') == fmt_id:
                    best = media
                    break
            else:
                continue
            break
        
        if best:
            response["direct_stream"] = {
                "url": best.get("url"),
                "quality": best.get("quality") or best.get("label"),
                "height": best.get("height"),
                "ext": best.get("ext"),
                "format_id": best.get("formatId")
            }
        else:
            response["direct_stream"] = {"error": "No suitable stream found"}
    else:
        response["direct_stream"] = {"error": stream_data.get("error")}
    
    # Get channel details
    if video_data.get("channel_id"):
        channel_data = get_channel_details(video_data["channel_id"])
        if "error" not in channel_data:
            response["channel"] = channel_data
    
    # Get comments
    if include_comments:
        comments_data = get_comments(video_id, 10)
        if "error" not in comments_data:
            response["comments"] = comments_data
    
    return jsonify(response)

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 YouTube Complete API Server")
    print("="*60)
    print("📌 Available Endpoints:")
    print("  /video     - Get video details")
    print("  /channel   - Get channel details")
    print("  /search    - Search videos")
    print("  /comments  - Get video comments")
    print("  /playlist  - Get playlist details")
    print("  /stream    - Get direct stream link")
    print("  /full      - Get everything")
    print("\n📖 Examples:")
    print("  /video?id=WOZwY8iEomg&include_stream=true")
    print("  /search?q=Electrostatics JEE&max=5")
    print("  /full?id=WOZwY8iEomg")
    print("\n" + "="*60)
    print("✨ Server running on http://localhost:5000")
    print("="*60 + "\n")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
