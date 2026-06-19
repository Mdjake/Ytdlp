from flask import Flask, request, jsonify
import requests
import re
import json
from collections import OrderedDict
import urllib.parse

app = Flask(__name__)

# API Keys and URLs
YOUTUBE_API_KEY = "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
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

def parse_duration(duration):
    """Convert ISO 8601 duration to readable format"""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return "N/A"
    
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    
    out = []
    if h: out.append(f"{h}h")
    if m: out.append(f"{m}m")
    if s: out.append(f"{s}s")
    
    return " ".join(out) if out else "0s"

def get_video_metadata(video_id):
    """Fetch video metadata from YouTube API"""
    url = f"{YOUTUBE_VIDEOS_API_URL}?part=snippet,statistics,contentDetails&id={video_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": "YouTube API failed"}
    
    data = r.json()
    if not data.get("items"):
        return {"error": "Video not found"}
    
    v = data["items"][0]
    snippet = v["snippet"]
    stats = v["statistics"]
    content = v["contentDetails"]
    
    return {
        "title": snippet.get("title", "N/A"),
        "channel": snippet.get("channelTitle", "N/A"),
        "channel_id": snippet.get("channelId", "N/A"),
        "description": snippet.get("description", "N/A"),
        "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url") or 
                    f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "duration_iso": content.get("duration", "N/A"),
        "duration_readable": parse_duration(content.get("duration")),
        "views": stats.get("viewCount", "0"),
        "likes": stats.get("likeCount", "0"),
        "comments": stats.get("commentCount", "0"),
        "tags": snippet.get("tags", []),
        "published_at": snippet.get("publishedAt", "N/A"),
        "category_id": snippet.get("categoryId", "N/A")
    }

def get_stream_links(video_url):
    """Get direct stream links from ytdlp API"""
    try:
        # Encode the URL properly
        encoded_url = urllib.parse.quote(video_url, safe='')
        api_url = YTDLP_API.format(encoded_url)
        
        # Make request with browser headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return {"error": f"Stream API returned {response.status_code}"}
        
        data = response.json()
        
        # Check for errors
        if data.get("download", {}).get("error", False):
            return {"error": "Stream extraction failed"}
        
        return data.get("download", {})
        
    except requests.exceptions.Timeout:
        return {"error": "Stream API timeout"}
    except requests.exceptions.ConnectionError:
        return {"error": "Could not connect to stream API"}
    except json.JSONDecodeError:
        return {"error": "Invalid response from stream API"}
    except Exception as e:
        return {"error": f"Stream extraction error: {str(e)}"}

def filter_audio_streams(medias):
    """Filter and return only audio streams"""
    audio_streams = []
    
    # Common audio-only format IDs
    audio_format_ids = ['139', '140', '141', '256', '257', '258', '251']
    
    for media in medias:
        # Check if it's audio-only
        if media.get('type') == 'audio':
            audio_streams.append(media)
        # Check if format ID matches audio formats
        elif media.get('formatId') in audio_format_ids:
            audio_streams.append(media)
        # Check mime type
        elif 'audio' in media.get('mimeType', '').lower() and 'video' not in media.get('mimeType', '').lower():
            audio_streams.append(media)
    
    return audio_streams

def get_best_stream(medias, quality='best'):
    """Get the best stream based on quality preference"""
    if not medias:
        return None
    
    # Priority: mp4 with highest resolution
    video_streams = [m for m in medias if m.get('type') == 'video']
    
    if not video_streams:
        return medias[0] if medias else None
    
    # Sort by height (resolution) descending
    sorted_streams = sorted(
        video_streams, 
        key=lambda x: x.get('height', 0), 
        reverse=True
    )
    
    # Return highest quality
    return sorted_streams[0]

@app.route("/", methods=["GET"])
def index():
    """API information and usage"""
    return jsonify({
        "name": "YouTube to Direct Stream API",
        "version": "2.0",
        "description": "Convert any YouTube URL to direct stream links with metadata",
        "credit": "Combined YouTube Data API + ytdlp API",
        "endpoints": {
            "/yt": {
                "method": "GET",
                "params": {
                    "dl": "YouTube URL (required)",
                    "format": "Optional: 'all', 'audio', 'video', 'best' (default: 'best')"
                },
                "example": "/yt?dl=https://www.youtube.com/watch?v=WOZwY8iEomg&format=best"
            }
        },
        "features": [
            "Get video metadata (title, channel, views, etc.)",
            "Extract direct stream links",
            "Filter by format (all/audio/video/best)",
            "Get audio-only streams"
        ]
    })

@app.route("/yt", methods=["GET"])
def convert_to_direct_stream():
    """Main endpoint: Convert YouTube URL to direct stream link"""
    
    # Get parameters
    url = request.args.get("dl", "").strip()
    format_type = request.args.get("format", "best").lower()
    
    # Validate input
    if not url:
        return jsonify({"error": "Missing 'dl' parameter", "usage": "/yt?dl=YOUTUBE_URL"}), 400
    
    # Extract video ID
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL", "provided": url}), 400
    
    # Build proper YouTube URL
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Get metadata
    metadata = get_video_metadata(video_id)
    if "error" in metadata:
        return jsonify({"error": metadata["error"]}), 404
    
    # Get stream links
    stream_data = get_stream_links(video_url)
    if "error" in stream_data:
        return jsonify({
            "video_id": video_id,
            "metadata": metadata,
            "error": stream_data["error"],
            "note": "Metadata retrieved but stream links unavailable"
        }), 207  # Multi-Status
    
    # Process medias based on format preference
    medias = stream_data.get("medias", [])
    filtered_medias = []
    best_stream = None
    
    if format_type == "audio":
        # Get only audio streams
        filtered_medias = filter_audio_streams(medias)
        best_stream = filtered_medias[0] if filtered_medias else None
    
    elif format_type == "video":
        # Get only video streams (filter out audio-only)
        filtered_medias = [m for m in medias if m.get('type') == 'video']
        best_stream = get_best_stream(filtered_medias)
    
    elif format_type == "best":
        # Get the best quality video with audio
        best_stream = get_best_stream(medias)
    
    else:  # format_type == "all" or anything else
        filtered_medias = medias
        best_stream = get_best_stream(medias)
    
    # Build response
    response = OrderedDict()
    response["video_id"] = video_id
    response["url"] = video_url
    response["format_preference"] = format_type
    response["metadata"] = metadata
    response["streams"] = {
        "all": medias,
        "filtered": filtered_medias if filtered_medias else None,
        "count": len(filtered_medias) if filtered_medias else len(medias)
    }
    
    if best_stream:
        response["direct_stream"] = {
            "url": best_stream.get("url"),
            "format_id": best_stream.get("formatId"),
            "quality": best_stream.get("quality") or best_stream.get("label"),
            "height": best_stream.get("height"),
            "width": best_stream.get("width"),
            "ext": best_stream.get("ext"),
            "fps": best_stream.get("fps"),
            "bitrate": best_stream.get("bitrate"),
            "mime_type": best_stream.get("mimeType"),
            "has_audio": "audio" in best_stream.get("mimeType", "").lower() 
                         or best_stream.get('type') != 'video' 
                         or best_stream.get('type') == 'audio'
        }
        response["stream_ready"] = True
    else:
        response["direct_stream"] = None
        response["stream_ready"] = False
        response["message"] = "No suitable stream found for the requested format"
    
    return jsonify(response)

# Additional endpoint for direct extraction
@app.route("/extract", methods=["GET"])
def extract_direct_only():
    """Simpler endpoint - returns only the direct stream URL"""
    url = request.args.get("dl", "").strip()
    quality = request.args.get("quality", "best")  # best, 720, 480, 360
    
    if not url:
        return jsonify({"error": "Missing 'dl' parameter"}), 400
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    stream_data = get_stream_links(video_url)
    
    if "error" in stream_data:
        return jsonify({"error": stream_data["error"]}), 500
    
    medias = stream_data.get("medias", [])
    
    # Filter by quality if specified
    if quality != "best":
        target_height = int(re.search(r'\d+', quality).group()) if re.search(r'\d+', quality) else None
        if target_height:
            # Find closest quality
            filtered = [m for m in medias if m.get('type') == 'video']
            closest = min(filtered, key=lambda x: abs(x.get('height', 0) - target_height))
            stream_url = closest.get('url')
        else:
            stream_url = get_best_stream(medias).get('url')
    else:
        best = get_best_stream(medias)
        stream_url = best.get('url') if best else None
    
    if stream_url:
        return jsonify({
            "video_id": video_id,
            "direct_stream_url": stream_url,
            "quality": quality
        })
    else:
        return jsonify({"error": "No stream found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
