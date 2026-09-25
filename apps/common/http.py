# apps/common/http.py
def client_ip(request):
    """取真实客户端 IP

    优先级：
      1) X-Forwarded-For 的第一段（nginx 透传的真实来源 IP）
      2) X-Real-IP
      3) REMOTE_ADDR（直连时兜底）

    """
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip()

    real_ip = (request.META.get('HTTP_X_REAL_IP') or '').strip()
    if real_ip:
        return real_ip

    return (request.META.get('REMOTE_ADDR') or '').strip()
