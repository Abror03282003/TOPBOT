import re

URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?"
    r"(instagram\.com|tiktok\.com|youtube\.com|youtu\.be|"
    r"facebook\.com|fb\.watch|twitter\.com|x\.com)/\S+",
    re.IGNORECASE,
)


def extract_url(text: str) -> str | None:
    if not text:
        return None
    match = URL_PATTERN.search(text)
    if not match:
        return None
    url = match.group(0)
    if not url.startswith("http"):
        url = "https://" + url
    return url


def detect_platform(url: str) -> str:
    url = url.lower()
    if "instagram.com" in url:
        return "Instagram"
    if "tiktok.com" in url:
        return "TikTok"
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    if "facebook.com" in url or "fb.watch" in url:
        return "Facebook"
    if "twitter.com" in url or "x.com" in url:
        return "Twitter/X"
    return "Noma'lum"
