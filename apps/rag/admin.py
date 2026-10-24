from django.contrib import admin

from .models import (RagChunk, RagPage, RagQueryLog, RagSetting,
                     RagTokenBalance, RagTokenRecord)


@admin.register(RagSetting)
class RagSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'remark', 'updated_at')
    search_fields = ('key',)


@admin.register(RagPage)
class RagPageAdmin(admin.ModelAdmin):
    list_display = ('page_id', 'title', 'revid', 'chunk_count', 'updated_raw')
    search_fields = ('title',)


@admin.register(RagChunk)
class RagChunkAdmin(admin.ModelAdmin):
    list_display = ('page_id', 'chunk_index', 'content_type', 'char_count', 'header_path')
    list_filter = ('content_type',)
    search_fields = ('content',)


@admin.register(RagQueryLog)
class RagQueryLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'question', 'hit_count', 'latency_ms', 'feedback', 'created_at')
    list_filter = ('feedback', 'mode')
    search_fields = ('question', 'answer')


@admin.register(RagTokenBalance)
class RagTokenBalanceAdmin(admin.ModelAdmin):
    list_display = ('uid', 'balance_units', 'total_earned', 'total_spent', 'enable')


@admin.register(RagTokenRecord)
class RagTokenRecordAdmin(admin.ModelAdmin):
    list_display = ('uid', 'direction', 'scene', 'amount', 'balance_after', 'created_at')
