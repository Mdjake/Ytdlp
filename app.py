from flask import Flask, request, jsonify
import requests
import re
from collections import OrderedDict

app = Flask(__name__)

YOUTUBE_API_KEY = "AIzaSyAJrpKVk0Ds5dHlayD5f6W2moeJMMF51JI"
YOUTUBE_SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"


def extract_video_id(url):
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([^&?\s]+)',
        r'(?:https?://)?youtu\.be/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([^&?\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([^&?\s]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def parse_duration(duration):
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


def fetch_youtube_details(video_id):
    url = f"{YOUTUBE_VIDEOS_API_URL}?part=snippet,statistics,contentDetails&id={video_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(url)

    if r.status_code != 200:
        return {"error": "YouTube API failed"}

    data = r.json()
    if not data.get("items"):
        return {"error": "Video not found"}

    v = data["items"][0]
    sn = v["snippet"]
    st = v["statistics"]
    cd = v["contentDetails"]

    return {
        "title": sn.get("title"),
        "channel": sn.get("channelTitle"),
        "description": sn.get("description"),
        "imageUrl": sn.get("thumbnails", {}).get("high", {}).get("url"),
        "duration": parse_duration(cd.get("duration")),
        "views": st.get("viewCount"),
        "likes": st.get("likeCount"),
        "comments": st.get("commentCount"),
        "tags": sn.get("tags", [])
    }


def fetch_download(video_id):
    try:
        payload = {"url": f"https://www.youtube.com/watch?v={video_id}"}
        r = requests.post("https://www.clipto.com/api/youtube", json=payload)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None


# ✅ INDEX / USAGE
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "YouTube API",
        "version": "1.0",
        "credit": "@ab_devs",
        "usage": {
            "endpoint": "/yt",
            "method": "GET",
            "param": "dl (YouTube URL)"
        },
        "example": [
            "/yt?dl=https://www.youtube.com/watch?v=WOZwY8iEomg",
            "/yt?dl=https://youtu.be/WOZwY8iEomg"
        ]
    })


# ✅ MAIN API
@app.route("/yt", methods=["GET"])
def yt_api():
    url = request.args.get("dl", "").strip()

    if not url:
        return jsonify({"error": "Missing dl parameter"}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    details = fetch_youtube_details(video_id)

    fallback_thumb = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    clipto_data = fetch_download(video_id)

    response = OrderedDict()

    response["video_id"] = video_id
    response["title"] = details.get("title", "N/A")
    response["channel"] = details.get("channel", "N/A")
    response["description"] = details.get("description", "N/A")
    response["thumbnail"] = details.get("imageUrl") or fallback_thumb
    response["duration"] = details.get("duration")
    response["views"] = details.get("views")
    response["likes"] = details.get("likes")
    response["comments"] = details.get("comments")
    response["tags"] = details.get("tags")

    if clipto_data:
        response["download"] = clipto_data

    return jsonify(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)