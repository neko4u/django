from django import forms
from django.core.exceptions import ValidationError
from .models import UserInfo
import re

PWD_REGEX = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[\w!@#$%^&*()_+\-=$$$${}|;:\'",.<>/?]{8,20}$'

EMAIL_REGEX = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(\.[a-zA-Z]{2,})?$'


def validate_password_strength(pwd):
    """统一的密码强度校验（注册 / 改密码共用）"""
    if not re.match(PWD_REGEX, pwd or ''):
        raise ValidationError("密码需8-20位且包含大小写字母和数字")
    return pwd


def validate_email_format(email):
    if not re.match(EMAIL_REGEX, email or ''):
        raise ValidationError("请填写正确的邮箱格式")
    return email


class LoginForm(forms.Form):

    user = forms.CharField(label="账户", max_length=100)
    pwd = forms.CharField(label="密码", widget=forms.PasswordInput)

class RegisterForm(forms.ModelForm):
    pwd = forms.CharField(
        label="密码",
        widget=forms.PasswordInput,
        min_length=8,
        max_length=20,
        help_text="密码需8-20位且包含大小写字母和数字"
    )
    pwd_confirm = forms.CharField(
        label="确认密码",
        widget=forms.PasswordInput
    )

    class Meta:
        model = UserInfo
        fields = ['account', 'name', 'email', 'phone', 'avatar']
        help_texts = {
            'account': '4-20位英文与数字组合',
            'name': '4-16位英文与数字组合',
        }

    def clean_account(self):
        account = self.cleaned_data.get('account')
        if not re.match(r'^[A-Za-z0-9]{4,20}$', account):
            raise ValidationError("账户请填写为用英文与数字形式4-20位")
        if UserInfo.objects.filter(account=account).exists():
            raise ValidationError("该账户名已被注册")
        return account

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not re.match(r'^[A-Za-z0-9]{4,16}$', name):
            raise ValidationError("昵称请填写为用英文与数字形式4-16位")
        return name

    def clean_pwd(self):
        return validate_password_strength(self.cleaned_data.get('pwd'))


    def clean_pwd_confirm(self):
        pwd = self.cleaned_data.get('pwd')
        pwd_confirm = self.cleaned_data.get('pwd_confirm')
        if pwd and pwd_confirm and pwd != pwd_confirm:
            raise ValidationError("两次输入的密码不一致")
        return pwd_confirm
        
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not re.match(r'^1[3-9]\d{9}$', phone):
            raise ValidationError("手机号码格式错误")
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not re.match(EMAIL_REGEX, email):
            raise ValidationError("请填写正确的邮箱格式")
        if UserInfo.objects.filter(email__iexact=email).exists():
            raise ValidationError("该邮箱已被其他账号使用，请更换或使用找回密码")
        return email


    # def clean_avatar(self):
    #     avatar = self.cleaned_data.get('avatar')
    #     if avatar:
    #         if avatar.size > 2 * 1024 * 1024:
    #             raise ValidationError("头像文件大小不能超过2MB")
    #         if not avatar.name.lower().endswith(('.jpg', '.jpeg', '.png')):
    #             raise ValidationError("只支持JPG/PNG格式的图片")
    #     return avatar

class ModifyInfoForm(forms.ModelForm):
    """处理用户信息修改的表单。

    传 user 是为了在改邮箱时排除自己（避免"邮箱已被占用"误判）。
    """

    class Meta:
        model = UserInfo
        fields = ['name', 'email', 'phone']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # 原邮箱必须在 super().__init__() 之后、表单校验之前就记录下来。
        # 原因：ModelForm._post_clean() 会把 cleaned_data 写回 self.instance，
        # 等 is_valid() 之后再读 instance.email，拿到的已经是**新邮箱**了，
        # 会导致"邮箱是否变更"永远判为 False，改邮箱的验证码校验被绕过。
        self._original_email = (getattr(self.instance, 'email', '') or '').strip().lower()

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not re.match(r'^[A-Za-z0-9]{4,16}$', name):
            raise ValidationError("昵称请填写为用英文与数字形式4-16位")
        return name

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not re.match(r'^1[3-9]\d{9}$', phone):
            raise ValidationError("手机号码格式错误")
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not re.match(EMAIL_REGEX, email):
            raise ValidationError("请填写正确的邮箱格式")
        qs = UserInfo.objects.filter(email__iexact=email)
        if self.user is not None:
            qs = qs.exclude(uid=self.user.uid)
        if qs.exists():
            raise ValidationError("该邮箱已被其他账号使用，请更换")
        return email

    def email_changed(self):
        """邮箱是否真的变了（决定要不要走邮箱验证码）"""
        new = (self.cleaned_data.get('email') or '').strip().lower()
        return self._original_email != new


class ChangePasswordByOldForm(forms.Form):
    """方式一：记得原密码"""

    old_pwd = forms.CharField(label='原密码', widget=forms.PasswordInput)
    new_pwd = forms.CharField(
        label='新密码',
        widget=forms.PasswordInput,
        min_length=8,
        max_length=20,
    )
    new_pwd_confirm = forms.CharField(label='确认新密码', widget=forms.PasswordInput)

    def clean_new_pwd(self):
        return validate_password_strength(self.cleaned_data.get('new_pwd'))

    def clean(self):
        data = super().clean()
        new_pwd = data.get('new_pwd')
        confirm = data.get('new_pwd_confirm')
        old_pwd = data.get('old_pwd')

        if new_pwd and confirm and new_pwd != confirm:
            raise ValidationError('两次输入的新密码不一致')
        if new_pwd and old_pwd and new_pwd == old_pwd:
            raise ValidationError('新密码不能与原密码相同')
        return data


class ChangePasswordByEmailForm(forms.Form):
    """方式二：不记得原密码，用邮箱验证码。

    邮箱验证码的 ticket 由视图层单独校验，这里只管新密码。
    """

    new_pwd = forms.CharField(
        label='新密码',
        widget=forms.PasswordInput,
        min_length=8,
        max_length=20,
    )
    new_pwd_confirm = forms.CharField(label='确认新密码', widget=forms.PasswordInput)

    def clean_new_pwd(self):
        return validate_password_strength(self.cleaned_data.get('new_pwd'))

    def clean(self):
        data = super().clean()
        new_pwd = data.get('new_pwd')
        confirm = data.get('new_pwd_confirm')
        if new_pwd and confirm and new_pwd != confirm:
            raise ValidationError('两次输入的新密码不一致')
        return data
