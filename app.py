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
    except Exception as e:
        print(f"Clipto error for {video_id}: {str(e)}")
    
    # Try vevioz (audio)
    try:
        api_url = f"https://api.vevioz.com/api/button/mp3/{video_id}"
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
    except Exception as e:
        print(f"Vevioz error for {video_id}: {str(e)}")
    
    # Try yt-api.com
    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        encoded_url = urllib.parse.quote(video_url, safe='')
        api_url = f"https://yt-api.com/yt?url={encoded_url}"
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
    except Exception as e:
        print(f"YT-API error for {video_id}: {str(e)}")
    
    return None

def get_streams_batch(video_ids):
    """Get direct streams for multiple videos in parallel"""
    results = {}
    
    if not video_ids:
        return results
    
    print(f"🔄 Fetching streams for {len(video_ids)} videos...")
    
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
                print(f"Error fetching stream for {video_id}: {str(e)}")
                results[video_id] = None
    
    stream_count = sum(1 for s in results.values() if s is not None)
    print(f"✅ Got streams for {stream_count}/{len(video_ids)} videos")
    
    return results

def search_videos(query, max_results=10, order="relevance", duration="any"):
    """Search for videos"""
    params = {
        "part": "snippet",
        "q": query,
        "maxResults": max_results,
        "order": order,
        "type": "video",
        "key": "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
    }
    
    # Add duration filter if specified
    if duration and duration != "any":
        duration_map = {
            "short": "short",
            "medium": "medium", 
            "long": "long"
        }
        if duration in duration_map:
            params["videoDuration"] = duration_map[duration]
    
    url = f"{YOUTUBE_SEARCH_API_URL}?{urllib.parse.urlencode(params)}"
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
        "videos": videos,
        "next_page_token": data.get("nextPageToken"),
        "prev_page_token": data.get("prevPageToken")
    }

# ====================== API ENDPOINTS ======================

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "YouTube Complete API with Streams",
        "version": "4.0",
        "credit": "@ab_devs",
        "description": "Complete YouTube Data API + Direct Stream URLs for ALL endpoints",
        "endpoints": {
            "/search": {
                "method": "GET",
                "params": {
                    "q": "Search query (required)",
                    "max": "Max results (default: 10)",
                    "order": "relevance/date/rating/viewCount",
                    "duration": "any/short/medium/long"
                },
                "example": "/search?q=Electrostatics+JEE&max=5&duration=medium"
            },
            "/yt": {
                "method": "GET",
                "params": {"dl": "YouTube URL"},
                "example": "/yt?dl=https://www.youtube.com/watch?v=WOZwY8iEomg"
            },
            "/batch": {
                "method": "GET",
                "params": {"ids": "comma-separated video IDs"},
                "example": "/batch?ids=WOZwY8iEomg,dQw4w9WgXcQ"
            }
        }
    })

@app.route("/search", methods=["GET"])
def search():
    """Search videos with direct streams for ALL videos"""
    query = request.args.get("q", "").strip()
    max_results = int(request.args.get("max", 10))
    order = request.args.get("order", "relevance")
    duration = request.args.get("duration", "any")
    
    if not query:
        return jsonify({"error": "Missing q parameter"}), 400
    
    print(f"\n🔍 Searching for: {query}")
    print(f"📊 Max results: {max_results}, Order: {order}, Duration: {duration}")
    
    # Search for videos
    results = search_videos(query, max_results, order, duration)
    if "error" in results:
        return jsonify(results), 400
    
    videos = results.get("videos", [])
    print(f"📹 Found {len(videos)} videos")
    
    # Get streams for ALL videos
    if videos:
        video_ids = [v["video_id"] for v in videos]
        stream_results = get_streams_batch(video_ids)
        
        # Add streams to each video
        for video in videos:
            video_id = video["video_id"]
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
    
    # Build response
    response = {
        "query": query,
        "total_results": results.get("total_results", 0),
        "returned_count": len(videos),
        "next_page_token": results.get("next_page_token"),
        "prev_page_token": results.get("prev_page_token"),
        "videos": videos
    }
    
    # Add summary
    stream_count = sum(1 for v in videos if v.get("stream_available", False))
    response["streams_found"] = stream_count
    response["streams_total"] = len(videos)
    
    print(f"✅ Returning {len(videos)} videos with {stream_count} streams\n")
    
    return jsonify(response)

@app.route("/yt", methods=["GET"])
def yt_api():
    """Get single video with direct stream"""
    url = request.args.get("dl", "").strip()
    
    if not url:
        return jsonify({"error": "Missing dl parameter"}), 400
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    print(f"\n🎯 Fetching video: {video_id}")
    
    # Get stream
    stream = get_direct_stream_single(video_id)
    
    # Get video details from search
    results = search_videos(video_id, 1)
    if "error" in results:
        return jsonify(results), 404
    
    videos = results.get("videos", [])
    if not videos:
        return jsonify({"error": "Video not found"}), 404
    
    video_data = videos[0]
    
    if stream:
        video_data["direct_stream"] = {
            "url": stream.get("url"),
            "quality": stream.get("quality"),
            "height": stream.get("height"),
            "ext": stream.get("ext"),
            "format_id": stream.get("format_id"),
            "source": stream.get("source")
        }
        video_data["stream_available"] = True
    else:
        video_data["direct_stream"] = None
        video_data["stream_available"] = False
    
    print(f"✅ Stream available: {video_data['stream_available']}\n")
    
    return jsonify(video_data)

@app.route("/batch", methods=["GET"])
def batch():
    """Get direct streams for multiple videos"""
    ids_input = request.args.get("ids", "").strip()
    
    if not ids_input:
        return jsonify({"error": "Missing ids parameter"}), 400
    
    video_ids = [id.strip() for id in ids_input.split(",") if id.strip()]
    
    if not video_ids:
        return jsonify({"error": "No valid video IDs"}), 400
    
    print(f"\n📦 Batch processing {len(video_ids)} videos...")
    
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
    
    stream_count = sum(1 for v in results if v.get("stream_available", False))
    print(f"✅ Got streams for {stream_count}/{len(results)} videos\n")
    
    return jsonify({
        "total": len(results),
        "streams_found": stream_count,
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
            "Multiple fallback APIs"
        ]
    })

if __name__ == "__main__":
    print("\n" + "="*80)
    print("🎯 YouTube Complete API v4.0 - STREAMS IN ALL RESPONSES")
    print("="*80)
    print("✨ Features:")
    print("   • Direct streams in EVERY response")
    print("   • Parallel stream fetching for speed")
    print("   • Multiple fallback APIs")
    print("   • Full YouTube Data API features")
    print("\n📌 Endpoints (ALL return direct streams):")
    print("   /search  - Search + streams for ALL videos")
    print("   /yt      - Single video + stream")
    print("   /batch   - Multiple videos + streams")
    print("\n📖 Examples:")
    print("   /search?q=Electrostatics+JEE&max=5&duration=medium")
    print("   /yt?dl=https://www.youtube.com/watch?v=WOZwY8iEomg")
    print("   /batch?ids=WOZwY8iEomg,dQw4w9WgXcQ")
    print("\n" + "="*80 + "\n")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
