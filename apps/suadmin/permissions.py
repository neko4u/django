# apps/suadmin/permissions.py

# ---------------- 帮助中心 ----------------
PERM_HELPCENTER_DOC_VIEW = 'helpcenter.doc.view'
PERM_HELPCENTER_DOC_EDIT = 'helpcenter.doc.edit'
PERM_HELPCENTER_DOC_DELETE = 'helpcenter.doc.delete'
PERM_HELPCENTER_IMAGE_UPLOAD = 'helpcenter.image.upload'
PERM_HELPCENTER_IMAGE_DELETE = 'helpcenter.image.delete'


# ---------------- 积分签到 ----------------
PERM_POINTS_SIGNIN_VIEW = 'points.signin.view'
PERM_POINTS_SIGNIN_EDIT = 'points.signin.edit'

# ---------------- 客户端版本管理（FRPClient） ----------------
PERM_DOWNLOAD_VERSION_VIEW = 'download.version.view'
PERM_DOWNLOAD_VERSION_EDIT = 'download.version.edit'


# ---------------- 论坛（现有 ad_create_comment 那个功能） ----------------
PERM_FORUM_COMMENT_CREATE = 'forum.comment.create'


# 权限码 -> 中文名。同时充当「合法权限码白名单」：
# 配置管理员时只允许填这里面有的码，防止打错字导致权限莫名其妙不生效。
ALL_PERMISSIONS = {
    PERM_HELPCENTER_DOC_VIEW: '帮助中心 - 查看文档',
    PERM_HELPCENTER_DOC_EDIT: '帮助中心 - 编辑文档',
    PERM_HELPCENTER_DOC_DELETE: '帮助中心 - 删除文档',
    PERM_HELPCENTER_IMAGE_UPLOAD: '帮助中心 - 上传图片',
    PERM_HELPCENTER_IMAGE_DELETE: '帮助中心 - 删除图片',
    PERM_FORUM_COMMENT_CREATE: '论坛 - 生成回复',
    PERM_POINTS_SIGNIN_VIEW: '积分签到 - 查看活动',
    PERM_POINTS_SIGNIN_EDIT: '积分签到 - 管理活动',
    PERM_DOWNLOAD_VERSION_VIEW: '客户端版本 - 查看版本',
    PERM_DOWNLOAD_VERSION_EDIT: '客户端版本 - 上传/上下架',

}


def all_codes():
    """全部合法权限码。"""
    return set(ALL_PERMISSIONS.keys())


def label_of(code):
    """权限码 -> 中文名（没有则返回码本身）。"""
    return ALL_PERMISSIONS.get(code, code)
