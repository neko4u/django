from django import forms
from django.core.exceptions import ValidationError

from apps.pointsBalanceSystem.models import (
    UserPoint
)


class ExchangeFRPForm(forms.Form):

    quantity = forms.IntegerField(
        min_value=1,
        label='兑换数量',
        help_text='请输入想要兑换的份数',
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'placeholder': '输入数量'
            }
        )
    )

    def __init__(self, *args, **kwargs):

        self.user = kwargs.pop('user', None)
        self.activity = kwargs.pop('activity', None)

        super().__init__(*args, **kwargs)

    def clean(self):

        cleaned_data = super().clean()

        quantity = cleaned_data.get('quantity')

        # 用户检查
        if not self.user:
            raise ValidationError('用户信息缺失')

        # 活动检查
        if not self.activity:
            raise ValidationError('活动信息缺失')

        # 数量检查
        if quantity is None:
            return cleaned_data

        try:

            user_point = UserPoint.objects.get(
                user=self.user
            )

        except UserPoint.DoesNotExist:

            raise ValidationError('积分账户不存在')

        if not user_point.enable:
            raise ValidationError('积分账户已停用')

        required_points = (
            self.activity.points_required * quantity
        )

        if user_point.points_balance < required_points:

            raise ValidationError(
                f'积分不足，当前余额 '
                f'{user_point.points_balance}，'
                f'需要 {required_points} 积分'
            )

        return cleaned_data