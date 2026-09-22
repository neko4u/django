from django.db import migrations, models


class Migration(migrations.Migration):
    """email 长度 32 -> 254 并加索引。

    注意：只加长度和索引，**没有加 unique**。
    如果历史数据里已经有重复邮箱，加 unique 会让迁移直接失败。
    唯一性改由表单层保证（新注册/改邮箱都会校验），
    查询命中多条时业务层会拒绝并提示联系管理员。
    """

    dependencies = [
        ('login', '0006_auto_20260313_2339'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userinfo',
            name='email',
            field=models.CharField(
                db_index=True,
                help_text='找回密码 / 修改密码 / 修改邮箱时会向该邮箱发送验证码',
                max_length=254,
                verbose_name='邮箱',
            ),
        ),
    ]
