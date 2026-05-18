from apps.login.models import FrpPermission
from apps.login.services import JwtService

def authenticate_user(request):
    """
    从 session 或 JWT token 中统一提取 user_id。
    成功返回 user_id (str/int)，失败返回 None。
    """
    # 方式1: session 登录
    if request.session.get('is_logged_in'):
        info = request.session.get('info', {})
        uid = info.get('uid') or info.get('id')
        if uid:
            return uid

    # 方式2: JWT token 登录
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        try:
            payload = JwtService.verify_token(token)
            if payload:
                return payload.get('user_id') or payload.get('uid') or payload.get('id')
        except Exception:
            pass  # 校验失败统一在外部处理
    return None


def check_frp_permission(user_id, perm_name='can_access'):
    """
    检查用户是否拥有指定的 FRP 权限。
    返回 (success: bool, result: FrpPermission or error_message: str)
    """
    try:
        perm = FrpPermission.objects.get(user_id=user_id)
    except FrpPermission.DoesNotExist:
        return False, '未配置权限'

    if not perm.can_access:
        return False, '无FRP权限'

    if perm_name and not getattr(perm, perm_name, False):
        return False, '权限不足'

    return True, perm
