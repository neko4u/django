# apps/suadmin/views.py

from django.shortcuts import render

from .decorators import admin_required


@admin_required
def admin_home(request):
    return render(request, 'suadmin/home.html')
