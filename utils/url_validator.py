import re

# Havola (URL) formatini va ijtimoiy tarmoq havolalarini tekshirish uchun pattern
URL_PATTERN = re.compile(
    r'^(https?://)?'  # http:// yoki https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domen nomi
    r'localhost|'  # localhost
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP manzil
    r'(?::\d+)?'  # port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE
)

def is_valid_url(url: str) -> bool:
    """
    Kiritilgan matn to'g'ri URL havola ekanligini tekshiradi.
    Agar havola bo'lsa True, aks holda False qaytaradi.
    """
    if not url or not isinstance(url, str):
        return False
    
    return bool(URL_PATTERN.match(url.strip()))
