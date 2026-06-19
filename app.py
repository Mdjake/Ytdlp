from flask import Flask, request, jsonify
import requests
import re
import json
import urllib.parse
from collections import OrderedDict
import time
from datetime import datetime

app = Flask(__name__)

YOUTUBE_API_KEY = "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
YOUTUBE_SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_COMMENTS_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
YOUTUBE_PLAYLISTS_API_URL = "https://www.googleapis.com/youtube/v3/playlists"
YOUTUBE_PLAYLIST_ITEMS_API_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
YOUTUBE_SUBSCRIPTIONS_API_URL = "https://www.googleapis.com/youtube/v3/subscriptions"
YOUTUBE_ACTIVITIES_API_URL = "https://www.googleapis.com/youtube/v3/activities"
YOUTUBE_CAPTIONS_API_URL = "https://www.googleapis.com/youtube/v3/captions"
YOUTUBE_THUMBNAILS_API_URL = "https://www.googleapis.com/youtube/v3/thumbnails"
YOUTUBE_WATERMARKS_API_URL = "https://www.googleapis.com/youtube/v3/watermarks"
YOUTUBE_VIDEO_CATEGORIES_API_URL = "https://www.googleapis.com/youtube/v3/videoCategories"
YOUTUBE_LIVE_BROADCASTS_API_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
YOUTUBE_LIVE_STREAMS_API_URL = "https://www.googleapis.com/youtube/v3/liveStreams"
YOUTUBE_MEMBERSHIPS_API_URL = "https://www.googleapis.com/youtube/v3/memberships"

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

def fetch_youtube_details(video_id, parts=None):
    """Fetch comprehensive video details"""
    if parts is None:
        parts = "snippet,contentDetails,statistics,topicDetails,status,recordingDetails,player,liveStreamingDetails"
    
    url = f"{YOUTUBE_VIDEOS_API_URL}?part={parts}&id={video_id}&key={YOUTUBE_API_KEY}"
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
    status = v.get("status", {})
    topic = v.get("topicDetails", {})
    recording = v.get("recordingDetails", {})
    live = v.get("liveStreamingDetails", {})
    
    return {
        # Basic Info
        "video_id": video_id,
        "title": snippet.get("title", "N/A"),
        "description": snippet.get("description", "N/A"),
        "channel_id": snippet.get("channelId", "N/A"),
        "channel_title": snippet.get("channelTitle", "N/A"),
        
        # Thumbnails (all sizes)
        "thumbnails": {
            "default": snippet.get("thumbnails", {}).get("default", {}).get("url"),
            "medium": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "high": snippet.get("thumbnails", {}).get("high", {}).get("url"),
            "standard": snippet.get("thumbnails", {}).get("standard", {}).get("url"),
            "maxres": snippet.get("thumbnails", {}).get("maxres", {}).get("url")
        },
        
        # Timing
        "published_at": snippet.get("publishedAt", "N/A"),
        "duration": parse_duration(content.get("duration", "PT0S")),
        
        # Statistics
        "statistics": {
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "dislikes": int(stats.get("dislikeCount", 0)),
            "favorites": int(stats.get("favoriteCount", 0)),
            "comments": int(stats.get("commentCount", 0))
        },
        
        # Content Details
        "content_details": {
            "duration_iso": content.get("duration", "N/A"),
            "dimension": content.get("dimension", "N/A"),
            "definition": content.get("definition", "N/A"),
            "caption": content.get("caption", "N/A"),
            "licensed_content": content.get("licensedContent", False),
            "projection": content.get("projection", "N/A"),
            "has_audio": content.get("hasAudio", False),
            "has_3d": content.get("has3d", False)
        },
        
        # Status
        "status": {
            "upload_status": status.get("uploadStatus", "N/A"),
            "privacy_status": status.get("privacyStatus", "N/A"),
            "license": status.get("license", "N/A"),
            "embeddable": status.get("embeddable", False),
            "public_stats_viewable": status.get("publicStatsViewable", False),
            "made_for_kids": status.get("madeForKids", False),
            "self_declared_made_for_kids": status.get("selfDeclaredMadeForKids", False)
        },
        
        # Categories & Tags
        "category_id": snippet.get("categoryId", "N/A"),
        "category_name": None,  # Will be filled if requested
        "tags": snippet.get("tags", []),
        
        # Topic Details
        "topic_details": {
            "topic_categories": topic.get("topicCategories", []),
            "relevant_topic_ids": topic.get("relevantTopicIds", [])
        },
        
        # Recording Details
        "recording_details": {
            "location": recording.get("location", {}),
            "location_description": recording.get("locationDescription", "N/A"),
            "recording_date": recording.get("recordingDate", "N/A")
        },
        
        # Live Streaming Details
        "live_streaming": {
            "actual_start_time": live.get("actualStartTime", "N/A"),
            "actual_end_time": live.get("actualEndTime", "N/A"),
            "scheduled_start_time": live.get("scheduledStartTime", "N/A"),
            "scheduled_end_time": live.get("scheduledEndTime", "N/A"),
            "concurrent_viewers": int(live.get("concurrentViewers", 0))
        }
    }

def fetch_channel_details(channel_id):
    """Fetch comprehensive channel details"""
    url = f"{YOUTUBE_CHANNELS_API_URL}?part=snippet,statistics,brandingSettings,contentDetails,topicDetails,status&id={channel_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"Channel API failed: {r.status_code}"}
    
    data = r.json()
    if not data.get("items"):
        return {"error": "Channel not found"}
    
    c = data["items"][0]
    snippet = c.get("snippet", {})
    stats = c.get("statistics", {})
    branding = c.get("brandingSettings", {})
    content = c.get("contentDetails", {})
    topic = c.get("topicDetails", {})
    status = c.get("status", {})
    
    return {
        "channel_id": channel_id,
        "title": snippet.get("title", "N/A"),
        "description": snippet.get("description", "N/A"),
        "custom_url": snippet.get("customUrl", "N/A"),
        "published_at": snippet.get("publishedAt", "N/A"),
        "thumbnails": {
            "default": snippet.get("thumbnails", {}).get("default", {}).get("url"),
            "medium": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "high": snippet.get("thumbnails", {}).get("high", {}).get("url")
        },
        "country": snippet.get("country", "N/A"),
        
        # Statistics
        "statistics": {
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videos": int(stats.get("videoCount", 0)),
            "hidden_subscriber_count": stats.get("hiddenSubscriberCount", False)
        },
        
        # Branding
        "branding": {
            "keywords": branding.get("channel", {}).get("keywords", ""),
            "unsubscribed_trailer": branding.get("channel", {}).get("unsubscribedTrailer", "N/A"),
            "profile_color": branding.get("channel", {}).get("profileColor", "N/A"),
            "banner": {
                "banner_image_url": branding.get("image", {}).get("bannerExternalUrl", "N/A"),
                "banner_mobile": branding.get("image", {}).get("bannerMobileExtraHdUrl", "N/A"),
                "banner_tablet": branding.get("image", {}).get("bannerTabletExtraHdUrl", "N/A")
            }
        },
        
        # Content Details
        "content_details": {
            "uploads": content.get("relatedPlaylists", {}).get("uploads", "N/A"),
            "likes": content.get("relatedPlaylists", {}).get("likes", "N/A"),
            "watch_history": content.get("relatedPlaylists", {}).get("watchHistory", "N/A")
        },
        
        # Topic Details
        "topic_details": {
            "topic_categories": topic.get("topicCategories", [])
        },
        
        # Status
        "status": {
            "is_linked": status.get("isLinked", False),
            "long_uploads_status": status.get("longUploadsStatus", "N/A"),
            "made_for_kids": status.get("madeForKids", False),
            "self_declared_made_for_kids": status.get("selfDeclaredMadeForKids", False)
        }
    }

def fetch_video_comments(video_id, max_results=20):
    """Fetch comments for a video"""
    url = f"{YOUTUBE_COMMENTS_API_URL}?part=snippet,replies&videoId={video_id}&maxResults={max_results}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"Comments API failed: {r.status_code}"}
    
    data = r.json()
    comments = []
    
    for item in data.get("items", []):
        snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        replies = item.get("replies", {}).get("comments", [])
        
        comment_data = {
            "comment_id": item.get("id"),
            "author": snippet.get("authorDisplayName", "N/A"),
            "author_channel_id": snippet.get("authorChannelId", {}).get("value", "N/A"),
            "text": snippet.get("textDisplay", "N/A"),
            "text_original": snippet.get("textOriginal", "N/A"),
            "likes": snippet.get("likeCount", 0),
            "published_at": snippet.get("publishedAt", "N/A"),
            "updated_at": snippet.get("updatedAt", "N/A"),
            "replies": []
        }
        
        # Add replies if any
        for reply in replies:
            reply_snippet = reply.get("snippet", {})
            comment_data["replies"].append({
                "author": reply_snippet.get("authorDisplayName", "N/A"),
                "text": reply_snippet.get("textDisplay", "N/A"),
                "likes": reply_snippet.get("likeCount", 0),
                "published_at": reply_snippet.get("publishedAt", "N/A")
            })
        
        comments.append(comment_data)
    
    return {
        "total_results": data.get("pageInfo", {}).get("totalResults", 0),
        "comments": comments
    }

def fetch_playlist_details(playlist_id):
    """Fetch playlist details and items"""
    # Get playlist info
    url = f"{YOUTUBE_PLAYLISTS_API_URL}?part=snippet,contentDetails,status&id={playlist_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"Playlist API failed: {r.status_code}"}
    
    data = r.json()
    if not data.get("items"):
        return {"error": "Playlist not found"}
    
    p = data["items"][0]
    snippet = p.get("snippet", {})
    content = p.get("contentDetails", {})
    status = p.get("status", {})
    
    # Get playlist items
    items_url = f"{YOUTUBE_PLAYLIST_ITEMS_API_URL}?part=snippet,contentDetails,status&playlistId={playlist_id}&maxResults=50&key={YOUTUBE_API_KEY}"
    items_response = requests.get(items_url)
    items_data = items_response.json() if items_response.status_code == 200 else {}
    
    videos = []
    for item in items_data.get("items", []):
        item_snippet = item.get("snippet", {})
        item_content = item.get("contentDetails", {})
        item_status = item.get("status", {})
        videos.append({
            "title": item_snippet.get("title", "N/A"),
            "video_id": item_content.get("videoId", "N/A"),
            "position": item_snippet.get("position", 0),
            "channel_title": item_snippet.get("channelTitle", "N/A"),
            "published_at": item_snippet.get("publishedAt", "N/A"),
            "thumbnail": item_snippet.get("thumbnails", {}).get("high", {}).get("url", "N/A"),
            "privacy_status": item_status.get("privacyStatus", "N/A")
        })
    
    return {
        "playlist_id": playlist_id,
        "title": snippet.get("title", "N/A"),
        "description": snippet.get("description", "N/A"),
        "channel_id": snippet.get("channelId", "N/A"),
        "channel_title": snippet.get("channelTitle", "N/A"),
        "published_at": snippet.get("publishedAt", "N/A"),
        "thumbnails": {
            "default": snippet.get("thumbnails", {}).get("default", {}).get("url"),
            "medium": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "high": snippet.get("thumbnails", {}).get("high", {}).get("url")
        },
        "item_count": content.get("itemCount", 0),
        "privacy_status": status.get("privacyStatus", "N/A"),
        "videos": videos
    }

def fetch_video_categories(region_code="US"):
    """Fetch video categories"""
    url = f"{YOUTUBE_VIDEO_CATEGORIES_API_URL}?part=snippet&regionCode={region_code}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)
    
    if r.status_code != 200:
        return {"error": f"Categories API failed: {r.status_code}"}
    
    data = r.json()
    categories = {}
    for item in data.get("items", []):
        categories[item.get("id")] = item.get("snippet", {}).get("title", "N/A")
    
    return categories

def search_videos(query, max_results=10, order="relevance", video_duration="any", video_definition="any"):
    """Search for videos with filters"""
    params = {
        "part": "snippet",
        "q": query,
        "maxResults": max_results,
        "order": order,
        "type": "video",
        "key": YOUTUBE_API_KEY
    }
    
    # Add optional filters
    if video_duration != "any":
        params["videoDuration"] = video_duration  # short, medium, long
    if video_definition != "any":
        params["videoDefinition"] = video_definition  # high, standard
    
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

def fetch_related_videos(video_id, max_results=10):
    """Fetch related videos using search API"""
    return search_videos(f"related:{video_id}", max_results)

def fetch_download_clipto(video_id):
    try:
        payload = {"url": f"https://www.youtube.com/watch?v={video_id}"}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json'
        }
        r = requests.post("https://www.clipto.com/api/youtube", json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data and data.get("medias"):
                return {"download": data}
    except:
        pass
    return None

def fetch_download_vevioz(video_id):
    try:
        api_url = STREAM_APIS[1].format(video_id)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('url') or data.get('download_url'):
                stream_url = data.get('url') or data.get('download_url')
                return {
                    "download": {
                        "medias": [{
                            "url": stream_url,
                            "formatId": "audio",
                            "ext": "mp3",
                            "quality": "audio",
                            "height": 0,
                            "type": "audio"
                        }]
                    }
                }
    except:
        pass
    return None

def fetch_download_ytapi(video_id):
    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        encoded_url = urllib.parse.quote(video_url, safe='')
        api_url = STREAM_APIS[2].format(encoded_url)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('formats'):
                return {"download": {"medias": data.get('formats', [])}}
            elif data.get('url'):
                return {
                    "download": {
                        "medias": [{
                            "url": data.get('url'),
                            "formatId": data.get('itag', 'unknown'),
                            "ext": data.get('ext', 'mp4'),
                            "quality": data.get('qualityLabel', 'unknown'),
                            "height": data.get('height', 0)
                        }]
                    }
                }
    except:
        pass
    return None

def fetch_download_fallback(video_id):
    return {
        "download": {
            "medias": [{
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "formatId": "youtube",
                "ext": "youtube",
                "quality": "youtube",
                "height": 0,
                "type": "video",
                "note": "Direct stream not available, using YouTube URL"
            }],
            "fallback": True
        }
    }

def fetch_download(video_id):
    result = fetch_download_clipto(video_id)
    if result and result.get("download", {}).get("medias"):
        return result
    
    result = fetch_download_vevioz(video_id)
    if result and result.get("download", {}).get("medias"):
        return result
    
    result = fetch_download_ytapi(video_id)
    if result and result.get("download", {}).get("medias"):
        return result
    
    return fetch_download_fallback(video_id)

# ====================== API ENDPOINTS ======================

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "YouTube Complete API",
        "version": "3.0",
        "credit": "@ab_devs (Full YouTube Data API)",
        "description": "Complete YouTube Data API + Direct Stream Extraction",
        "features": [
            "Video metadata (all details)",
            "Channel information",
            "Comments with replies",
            "Playlist management",
            "Video search with filters",
            "Related videos",
            "Video categories",
            "Direct stream URLs",
            "Audio extraction"
        ],
        "endpoints": {
            "/yt": {
                "method": "GET",
                "params": {
                    "dl": "YouTube URL (required)",
                    "format": "best/audio/video (optional)",
                    "include": "comments,channel,related (optional)"
                },
                "example": "/yt?dl=https://www.youtube.com/watch?v=WOZwY8iEomg&include=comments,channel"
            },
            "/search": {
                "method": "GET",
                "params": {
                    "q": "Search query (required)",
                    "max": "Max results (default: 10)",
                    "order": "relevance/date/rating/viewCount",
                    "duration": "any/short/medium/long",
                    "definition": "any/high/standard"
                },
                "example": "/search?q=Electrostatics+JEE&max=5&duration=medium"
            },
            "/channel": {
                "method": "GET",
                "params": {"id": "Channel ID or URL"},
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
                "params": {"id": "Playlist ID or URL"},
                "example": "/playlist?id=PLWwAq55NJFmDdY7XHbDYHq1Bp4bL1K3p"
            },
            "/categories": {
                "method": "GET",
                "params": {"region": "Region code (default: US)"},
                "example": "/categories?region=IN"
            },
            "/related": {
                "method": "GET",
                "params": {
                    "id": "Video ID or URL",
                    "max": "Max results (default: 10)"
                },
                "example": "/related?id=WOZwY8iEomg&max=5"
            }
        }
    })

@app.route("/yt", methods=["GET"])
def yt_api():
    """Get video details + direct stream"""
    url = request.args.get("dl", "").strip()
    format_type = request.args.get("format", "best").lower()
    include = request.args.get("include", "").lower().split(",")
    
    if not url:
        return jsonify({"error": "Missing dl parameter"}), 400
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Fetch video details
    details = fetch_youtube_details(video_id)
    if "error" in details:
        return jsonify(details), 404
    
    # Get category name if available
    categories = fetch_video_categories()
    if categories and details.get("category_id") in categories:
        details["category_name"] = categories[details["category_id"]]
    
    # Fetch download streams
    download_data = fetch_download(video_id)
    medias = download_data.get("download", {}).get("medias", [])
    
    # Filter medias based on format
    best_stream = None
    if format_type == "audio":
        audio_formats = ['139', '140', '141', '251', 'audio']
        filtered = [m for m in medias if m.get('formatId') in audio_formats or m.get('type') == 'audio']
        best_stream = filtered[0] if filtered else None
    elif format_type == "video":
        filtered = [m for m in medias if m.get('type') == 'video' or m.get('height', 0) > 0]
        best_stream = max(filtered, key=lambda x: x.get('height', 0)) if filtered else None
    else:  # best
        audio_video_formats = ['18', '22', '37', '59', '78']
        for fmt_id in audio_video_formats:
            for m in medias:
                if m.get('formatId') == fmt_id:
                    best_stream = m
                    break
            if best_stream:
                break
        if not best_stream and medias:
            best_stream = medias[0]
    
    # Build response
    response = OrderedDict()
    response["video_id"] = video_id
    response["title"] = details.get("title")
    response["channel"] = details.get("channel_title")
    response["channel_id"] = details.get("channel_id")
    response["description"] = details.get("description")
    response["thumbnails"] = details.get("thumbnails")
    response["duration"] = details.get("duration", {}).get("readable")
    response["duration_seconds"] = details.get("duration", {}).get("seconds")
    response["published_at"] = details.get("published_at")
    response["statistics"] = details.get("statistics")
    response["category"] = details.get("category_name")
    response["category_id"] = details.get("category_id")
    response["tags"] = details.get("tags")
    response["status"] = details.get("status")
    response["content_details"] = details.get("content_details")
    response["topic_details"] = details.get("topic_details")
    response["recording_details"] = details.get("recording_details")
    response["live_streaming"] = details.get("live_streaming")
    
    # Add direct stream
    if best_stream:
        response["direct_stream"] = {
            "url": best_stream.get("url"),
            "quality": best_stream.get("quality") or best_stream.get("label"),
            "height": best_stream.get("height"),
            "ext": best_stream.get("ext"),
            "format_id": best_stream.get("formatId"),
            "type": best_stream.get("type")
        }
    else:
        response["direct_stream"] = None
    
    # Include additional data if requested
    if "comments" in include:
        comments_data = fetch_video_comments(video_id, 10)
        response["comments"] = comments_data if "error" not in comments_data else None
    
    if "channel" in include:
        channel_data = fetch_channel_details(details.get("channel_id"))
        response["channel_info"] = channel_data if "error" not in channel_data else None
    
    if "related" in include:
        related_data = fetch_related_videos(video_id, 10)
        response["related_videos"] = related_data if "error" not in related_data else None
    
    response["source"] = "YouTube Data API v3 + ytdlp"
    
    return jsonify(response)

@app.route("/search", methods=["GET"])
def search():
    """Search for videos with filters"""
    query = request.args.get("q", "").strip()
    max_results = int(request.args.get("max", 10))
    order = request.args.get("order", "relevance")
    duration = request.args.get("duration", "any")
    definition = request.args.get("definition", "any")
    
    if not query:
        return jsonify({"error": "Missing q parameter"}), 400
    
    results = search_videos(query, max_results, order, duration, definition)
    if "error" in results:
        return jsonify(results), 400
    
    return jsonify(results)

@app.route("/channel", methods=["GET"])
def channel():
    """Get channel details"""
    channel_id = request.args.get("id", "").strip()
    
    if not channel_id:
        return jsonify({"error": "Missing id parameter"}), 400
    
    # Check if it's a URL
    if "youtube.com" in channel_id or "youtu.be" in channel_id:
        # Try to extract channel ID from URL
        patterns = [
            r'youtube\.com/channel/([^/?]+)',
            r'youtube\.com/c/([^/?]+)',
            r'youtube\.com/@([^/?]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, channel_id)
            if match:
                channel_id = match.group(1)
                break
    
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
    """Get playlist details"""
    playlist_input = request.args.get("id", "").strip()
    
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
    
    return jsonify(playlist_data)

@app.route("/categories", methods=["GET"])
def categories():
    """Get video categories"""
    region = request.args.get("region", "US").upper()
    
    categories_data = fetch_video_categories(region)
    if "error" in categories_data:
        return jsonify(categories_data), 400
    
    return jsonify({
        "region": region,
        "categories": categories_data
    })

@app.route("/related", methods=["GET"])
def related():
    """Get related videos"""
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
    
    related_data = fetch_related_videos(video_id, max_results)
    if "error" in related_data:
        return jsonify(related_data), 400
    
    return jsonify({
        "video_id": video_id,
        "related_videos": related_data
    })

@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "version": "3.0",
        "apis_available": [
            "YouTube Data API v3",
            "Clipto.com",
            "Vevioz API",
            "YT-API.com"
        ]
    })

if __name__ == "__main__":
    print("\n" + "="*80)
    print("🎯 YouTube Complete API v3.0")
    print("="*80)
    print("✨ All YouTube Data API Features + Direct Streams")
    print("\n📌 Endpoints:")
    print("   /yt         - Get video details + direct stream")
    print("   /search     - Search videos with filters")
    print("   /channel    - Get channel details")
    print("   /comments   - Get video comments with replies")
    print("   /playlist   - Get playlist details")
    print("   /categories - Get video categories")
    print("   /related    - Get related videos")
    print("   /health     - Health check")
    print("\n📖 Examples:")
    print("   /yt?dl=https://www.youtube.com/watch?v=WOZwY8iEomg&include=comments,channel")
    print("   /search?q=Electrostatics+JEE&max=5&duration=medium")
    print("   /channel?id=UC_x5XG1OV2P6uZZ5FSM9Ttw")
    print("   /comments?id=WOZwY8iEomg&max=10")
    print("   /playlist?id=PLWwAq55NJFmDdY7XHbDYHq1Bp4bL1K3p")
    print("   /categories?region=IN")
    print("   /related?id=WOZwY8iEomg&max=5")
    print("\n" + "="*80 + "\n")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
