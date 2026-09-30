# 签到活动模块 批①：SignInActivity / SignInRecord + PointRecord.business_id

from django.db import migrations, models
import django.db.models.deletion
import django.db.models.expressions


class Migration(migrations.Migration):

    dependencies = [
        ('login', '0007_alter_userinfo_email'),
        ('pointsBalanceSystem', '0005_pointrecord_activity'),
    ]

    operations = [
        migrations.CreateModel(
            name='SignInActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128, verbose_name='活动名称')),
                ('description', models.TextField(blank=True, default='', verbose_name='活动说明')),
                ('enable', models.BooleanField(db_index=True, default=True, verbose_name='是否启用')),
                ('start_at', models.DateTimeField(verbose_name='活动开始时间')),
                ('end_at', models.DateTimeField(verbose_name='活动结束时间')),
                ('points_per_sign_in', models.PositiveIntegerField(default=0, verbose_name='每次签到赠送积分')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '签到活动',
                'verbose_name_plural': '签到活动',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SignInRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sign_date', models.DateField(verbose_name='签到日期')),
                ('sign_time', models.DateTimeField(verbose_name='签到时间')),
                ('points_awarded', models.PositiveIntegerField(default=0, verbose_name='本次获得积分')),
                ('operator_ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='签到IP')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
            ],
            options={
                'verbose_name': '签到记录',
                'verbose_name_plural': '签到记录',
                'ordering': ['-sign_time'],
            },
        ),
        migrations.AddField(
            model_name='pointrecord',
            name='business_id',
            field=models.CharField(blank=True, default=None, help_text='同一次业务动作只允许写一条流水（配合唯一约束做幂等）', max_length=64, null=True, verbose_name='业务ID'),
        ),
        migrations.AddConstraint(
            model_name='pointrecord',
            constraint=models.UniqueConstraint(fields=('user', 'scene', 'business_id'), name='uniq_point_record_user_scene_business'),
        ),
        migrations.AddField(
            model_name='signinrecord',
            name='activity',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sign_in_records', to='pointsBalanceSystem.signinactivity', verbose_name='签到活动'),
        ),
        migrations.AddField(
            model_name='signinrecord',
            name='user',
            field=models.ForeignKey(db_column='uid', on_delete=django.db.models.deletion.PROTECT, related_name='sign_in_records', to='login.userinfo', verbose_name='用户'),
        ),
        migrations.AddIndex(
            model_name='signinactivity',
            index=models.Index(fields=['enable', 'start_at', 'end_at'], name='pointsBalan_enable_6c8a43_idx'),
        ),
        migrations.AddConstraint(
            model_name='signinactivity',
            constraint=models.CheckConstraint(check=models.Q(('end_at__gt', django.db.models.expressions.F('start_at'))), name='signin_activity_time_order'),
        ),
        migrations.AddIndex(
            model_name='signinrecord',
            index=models.Index(fields=['user', 'sign_date'], name='pointsBalan_uid_dc67d4_idx'),
        ),
        migrations.AddIndex(
            model_name='signinrecord',
            index=models.Index(fields=['activity', 'sign_date'], name='pointsBalan_activit_67c1ed_idx'),
        ),
        migrations.AddConstraint(
            model_name='signinrecord',
            constraint=models.UniqueConstraint(fields=('activity', 'user', 'sign_date'), name='uniq_signin_activity_user_date'),
        ),
    ]
