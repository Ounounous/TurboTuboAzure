from django.shortcuts import render
from django.http import JsonResponse

def index(request):
    return render(request, 'core/index.html')

def about(request):
    return render(request, 'core/about.html')

def health_check(request):
    return JsonResponse({"status": "healthy"})

#intento 2