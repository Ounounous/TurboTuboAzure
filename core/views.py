from django.db import DatabaseError, connection
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils.timezone import localdate
from django.db.models import Sum

from actions.models import Action, PaymentCommitment, Resultado
from lead.models import Lead
from lead.permissions import leads_visibles, scope_por_lead

def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard:dashboard')
    return render(request, 'core/index.html')

def about(request):
    if request.user.is_authenticated:
        return redirect('dashboard:dashboard')

    # Datos de About (sin login): datos globales del sistema, no por usuario
    today = localdate()
    mes_inicio = today.replace(day=1)

    # Todo el sistema (sin filtro por usuario)
    leads_activos = Lead.objects.filter(activo=Lead.ACTIVO)
    n_clientes = leads_activos.count()
    saldo_total = leads_activos.aggregate(total=Sum('saldo_insoluto'))['total'] or 0

    gestiones_mes = Action.objects.filter(created_at__date__gte=mes_inicio)
    total_gestiones_mes = gestiones_mes.count()
    con_contacto_mes = gestiones_mes.filter(resultado__contactabilidad=Resultado.CON_CONTACTO).count()
    contactabilidad_pct = round(100 * con_contacto_mes / total_gestiones_mes) if total_gestiones_mes else 0

    compromisos_qs = (
        PaymentCommitment.objects.filter(fecha_compromiso__gte=today)
        .select_related('lead', 'subcartera__cartera')
        .order_by('fecha_compromiso')
    )
    compromisos_count = compromisos_qs.count()
    compromisos_total = compromisos_qs.aggregate(total=Sum('monto'))['total'] or 0

    return render(request, 'core/about.html', {
        'n_clientes': n_clientes,
        'saldo_total': saldo_total,
        'contactabilidad_pct': contactabilidad_pct,
        'total_gestiones_mes': total_gestiones_mes,
        'compromisos': compromisos_qs[:20],
        'compromisos_count': compromisos_count,
        'compromisos_total': compromisos_total,
    })

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