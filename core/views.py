from django.db import DatabaseError, connection
from django.shortcuts import render
from django.http import JsonResponse

def index(request):
    return render(request, 'core/index.html')

def about(request):
    return render(request, 'core/about.html')

def health_check(request):
    # Chequeo real y barato (un SELECT 1, no un COUNT ni nada que dependa de datos): si la base
    # no responde, Azure tiene que enterarse por este probe -- antes /health/ devolvia 200
    # siempre, incluso con la BD caida, asi que un App Service con auto-heal/rolling-restart
    # jamas hubiera detectado ni reaccionado a una caida de conexion real.
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except DatabaseError:
        return JsonResponse({'status': 'unhealthy', 'detail': 'database unreachable'}, status=503)
    return JsonResponse({'status': 'healthy'})