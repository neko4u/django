from django import forms
from django.core.exceptions import ValidationError
from .models import UserInfo
import re

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
        pwd = self.cleaned_data.get('pwd')
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[\w!@#$%^&*()_+\-=\[\]{}|;:\'",.<>/?]{8,20}$', pwd):
            raise ValidationError("密码需8-20位且包含大小写字母和数字")
        return pwd

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
        email = self.cleaned_data.get('email')
        if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(\.[a-zA-Z]{2,})?$', email):
            raise ValidationError("请填写正确的邮箱格式")
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
    """处理用户信息修改的表单"""
    class Meta:
        model = UserInfo
        fields = ['name', 'email', 'phone']

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
        email = self.cleaned_data.get('email')
        if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(\.[a-zA-Z]{2,})?$', email):
            raise ValidationError("请填写正确的邮箱格式")
        return email