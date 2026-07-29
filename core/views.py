from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connection
from django.shortcuts import render, redirect
from django.http import JsonResponse

def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')
    return render(request, 'core/index.html')

@login_required
def about(request):
    # "About" es el punto de entrada (logo -> about -> dashboard real). No renderiza datos
    # propios: reusa el dashboard ya scopeado por rol (lead.permissions) para no duplicar
    # logica ni arriesgar exponer datos de otro alcance. login_required: sin esto, un
    # visitante sin sesion veia deuda/nombres reales de clientes (Ley 20.575/21.719).
    return redirect('dashboard:index')

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