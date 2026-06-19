from flask import Flask, request, jsonify
import requests
import re
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# API Keys and URLs
YOUTUBE_API_KEY = "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
YOUTUBE_SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YTDLP_API = "https://ytdlp-ten.vercel.app/yt?dl={}"

def extract_video_id(url):
    """Extract YouTube video ID from various URL formats"""
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([^&?\s]+)',
        r'(?:https?://)?youtu\.be/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/([^&?\s]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_direct_stream_single(video_id):
    """Get direct stream URL for a single video"""
    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        encoded_url = urllib.parse.quote(video_url, safe='')
        api_url = YTDLP_API.format(encoded_url)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        medias = data.get("download", {}).get("medias", [])
        
        if not medias:
            return None
        
        # Find best quality with audio (format 18 = 360p with audio)
        audio_video_formats = ['18', '22', '37', '59', '78']
        best = None
        
        for fmt_id in audio_video_formats:
            for media in medias:
                if media.get('formatId') == fmt_id:
                    best = media
                    break
            if best:
                break
        
        if not best:
            best = medias[0]
        
        return {
            "url": best.get("url"),
            "quality": best.get("quality") or best.get("label"),
            "height": best.get("height"),
            "ext": best.get("ext"),
            "format_id": best.get("formatId"),
            "has_audio": "audio" in best.get("mimeType", "").lower() or best.get('type') == 'audio'
        }
        
    except Exception as e:
        return None

def get_video_details(video_id):
    """Get video metadata from YouTube API"""
    url = f"{YOUTUBE_VIDEOS_API_URL}?part=snippet,statistics,contentDetails&id={video_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return None
    
    data = r.json()
    if not data.get("items"):
        return None
    
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
        "duration": content.get("duration", "N/A")
    }

def search_videos(query, max_results=10):
    """Search for videos using YouTube API"""
    url = f"{YOUTUBE_SEARCH_API_URL}?part=snippet&q={urllib.parse.quote(query)}&maxResults={max_results}&type=video&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return None
    
    data = r.json()
    videos = []
    
    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        if video_id:
            videos.append({
                "video_id": video_id,
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

@app.route("/", methods=["GET"])
def index():
    """API information"""
    return jsonify({
        "name": "YouTube Direct Stream API with Search",
        "version": "4.0",
        "description": "Get direct stream URLs for any YouTube video",
        "endpoints": {
            "/search": {
                "method": "GET",
                "params": {
                    "q": "Search query",
                    "max": "Max results (default: 10)",
                    "include_streams": "true/false (default: true)"
                },
                "example": "/search?q=Electrostatics+JEE&max=5&include_streams=true"
            },
            "/direct": {
                "method": "GET",
                "params": {"url": "YouTube URL or video ID"},
                "example": "/direct?url=https://www.youtube.com/watch?v=WOZwY8iEomg"
            },
            "/batch": {
                "method": "GET",
                "params": {"ids": "comma-separated video IDs"},
                "example": "/batch?ids=WOZwY8iEomg,dQw4w9WgXcQ"
            }
        }
    })

@app.route("/direct", methods=["GET"])
def get_direct():
    """Get direct stream URL for a single video"""
    url_or_id = request.args.get("url", "").strip()
    
    if not url_or_id:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    
    # Check if it's a URL or direct ID
    video_id = extract_video_id(url_or_id)
    if not video_id:
        # Check if it's already a video ID
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
            video_id = url_or_id
        else:
            return jsonify({"error": "Invalid YouTube URL or video ID"}), 400
    
    # Get metadata
    metadata = get_video_details(video_id)
    if not metadata:
        return jsonify({"error": "Video not found"}), 404
    
    # Get direct stream
    stream = get_direct_stream_single(video_id)
    
    return jsonify({
        "video_id": video_id,
        "title": metadata["title"],
        "channel": metadata["channel_title"],
        "views": metadata["views"],
        "likes": metadata["likes"],
        "duration": metadata["duration"],
        "thumbnail": metadata["thumbnail"],
        "direct_stream": stream,  # ← This contains the direct stream URL
        "stream_available": stream is not None
    })

@app.route("/search", methods=["GET"])
def search_with_streams():
    """Search videos and get direct streams for each"""
    query = request.args.get("q", "").strip()
    max_results = int(request.args.get("max", 10))
    include_streams = request.args.get("include_streams", "true").lower() == "true"
    
    if not query:
        return jsonify({"error": "Missing 'q' parameter"}), 400
    
    # Search for videos
    search_results = search_videos(query, max_results)
    if not search_results:
        return jsonify({"error": "Search failed"}), 500
    
    videos = search_results.get("videos", [])
    
    # If streams requested, fetch them in parallel
    if include_streams and videos:
        print(f"🔍 Found {len(videos)} videos, fetching direct streams...")
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Submit all stream fetching tasks
            future_to_video = {}
            for video in videos:
                video_id = video["video_id"]
                future = executor.submit(get_direct_stream_single, video_id)
                future_to_video[future] = video
            
            # Collect results as they complete
            for future in as_completed(future_to_video):
                video = future_to_video[future]
                try:
                    stream = future.result()
                    video["direct_stream"] = stream
                    video["stream_available"] = stream is not None
                except Exception as e:
                    video["direct_stream"] = None
                    video["stream_available"] = False
                    video["stream_error"] = str(e)
    
    return jsonify({
        "query": query,
        "total_results": search_results.get("total_results", 0),
        "returned_count": len(videos),
        "videos": videos
    })

@app.route("/batch", methods=["GET"])
def batch_streams():
    """Get direct streams for multiple video IDs"""
    ids_input = request.args.get("ids", "").strip()
    
    if not ids_input:
        return jsonify({"error": "Missing 'ids' parameter"}), 400
    
    video_ids = [id.strip() for id in ids_input.split(",") if id.strip()]
    
    if not video_ids:
        return jsonify({"error": "No valid video IDs"}), 400
    
    results = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {
            executor.submit(get_direct_stream_single, video_id): video_id 
            for video_id in video_ids
        }
        
        for future in as_completed(future_to_id):
            video_id = future_to_id[future]
            try:
                stream = future.result()
                metadata = get_video_details(video_id)
                
                results.append({
                    "video_id": video_id,
                    "title": metadata.get("title") if metadata else "N/A",
                    "channel": metadata.get("channel_title") if metadata else "N/A",
                    "direct_stream": stream,
                    "stream_available": stream is not None
                })
            except Exception as e:
                results.append({
                    "video_id": video_id,
                    "error": str(e),
                    "stream_available": False
                })
    
    return jsonify({
        "total": len(results),
        "videos": results
    })

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🎯 YouTube Direct Stream API with Search")
    print("="*70)
    print("✨ Features:")
    print("   • Search YouTube videos")
    print("   • Get direct stream URLs for ALL videos")
    print("   • Parallel processing for speed")
    print("   • Always returns direct streams, never YouTube links")
    print("\n📌 Endpoints:")
    print("   /search  - Search videos with direct streams")
    print("   /direct  - Get direct stream for single video")
    print("   /batch   - Get direct streams for multiple videos")
    print("\n📖 Examples:")
    print("   /search?q=Electrostatics+JEE&max=5")
    print("   /direct?url=https://www.youtube.com/watch?v=WOZwY8iEomg")
    print("   /batch?ids=WOZwY8iEomg,dQw4w9WgXcQ")
    print("\n" + "="*70 + "\n")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
