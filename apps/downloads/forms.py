# apps/downloads/forms.py
"""后台「上传新版本」表单：只负责校验，落盘在 services.store_upload 里做。

文件名由管理员自己填（上传页那个「文件名称」输入框），留空才用上传文件的原始名字。
"""

from django import forms

from .conf import conf
from .services import final_filename
from .versioning import display_version, parse_version

def _allowed_exts():
    """把配置里的扩展名统一成「小写、不带点」的集合，方便比较。"""
    raw = conf.ALLOWED_EXTENSIONS or ()
    if isinstance(raw, str):
        raw = raw.split(',')
    return {str(item).strip().lstrip('.').lower() for item in raw if str(item).strip()}

class VersionUploadForm(forms.Form):
    """后台新增版本用。``version 字段校验后是 6 位内部格式（如 010001）。"""

    version = forms.CharField(
        max_length=16,
        label='版本号',
        help_text='形如 1.0.1（3 段，每段 1~2 位数字）',
    )
    file_name = forms.CharField(
        max_length=255,
        required=False,
        label='文件名称',
        help_text='服务器上保存的名字，也是客户端下载下来的名字。留空则用上传文件的原始名字。',
    )
    file = forms.FileField(label='客户端文件')
    enable = forms.BooleanField(required=False, initial=True, label='上传后立即展示')
    replace = forms.BooleanField(required=False, initial=False,
                                label='该版本号已存在时覆盖重传')

    def clean_version(self):
        six, err = parse_version(self.cleaned_data['version'])
        if err:
            raise forms.ValidationError(err)
        return six

    def clean_file(self):
        upload = self.cleaned_data['file']
        limit = int(conf.UPLOAD_MAX_BYTES)

        if upload.size <= 0:
            raise forms.ValidationError('文件是空的')
        if upload.size > limit:
            raise forms.ValidationError('文件太大：%.1f MB，上限 %.1f MB'
                                        % (upload.size / 1048576.0, limit / 1048576.0))

        allowed = _allowed_exts()
        name = getattr(upload, 'name', '') or ''
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        if allowed and ext not in allowed:
            raise forms.ValidationError('不支持的文件类型「.%s」，只允许：%s'
                                        % (ext, '、'.join(sorted(allowed))))
        return upload

    def clean(self):
        """把「文件名称」定下来，并检查它的扩展名。"""
        cleaned = super().clean()
        upload = cleaned.get('file')
        if upload is None:
            return cleaned

        final = final_filename(cleaned.get('file_name') or '',
                               getattr(upload, 'name', ''))
        if not final:
            raise forms.ValidationError('文件名称不能为空')

        allowed = _allowed_exts()
        ext = final.rsplit('.', 1)[-1].lower() if '.' in final else ''
        if allowed and ext not in allowed:
            raise forms.ValidationError('文件名称的扩展名「.%s」不在允许范围内，只允许：%s'
                                        % (ext, '、'.join(sorted(allowed))))

        cleaned['file_name'] = final          # 定稿：后面视图直接用这个名字落盘
        return cleaned

    # ---- 给视图用的小工具 ----

    @property
    def six(self):
        """6 位内部格式（校验失败时是空串）。"""
        return (self.cleaned_data.get('version') or '') if self.is_valid() else ''

    @property
    def display(self):
        """给人看的简写（校验失败时是空串）。"""
        six = self.six
        return display_version(six) if six else ''

    @property
    def disk_name(self):
        """最终落盘 / 下载用的文件名（校验失败时是空串）。"""
        return (self.cleaned_data.get('file_name') or '') if self.is_valid() else ''