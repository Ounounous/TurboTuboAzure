import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils.timezone import localdate

from actions.models import Action, PaymentCommitment, Resultado
from lead.models import Lead
from lead.permissions import es_admin_owner, leads_visibles, scope_por_lead, subcarteras_visibles


def _metricas(leads_qs, actions_qs):
    n_clientes = leads_qs.count()
    saldo_total = leads_qs.aggregate(total=Sum('saldo_insoluto'))['total'] or 0
    total_gestiones = actions_qs.count()
    con_contacto = actions_qs.filter(resultado__contactabilidad=Resultado.CON_CONTACTO).count()
    contactabilidad_pct = round(100 * con_contacto / total_gestiones) if total_gestiones else 0
    return {
        'n_clientes': n_clientes,
        'saldo_total': saldo_total,
        'contactabilidad_pct': contactabilidad_pct,
        'total_gestiones_mes': total_gestiones,
    }


@login_required
def dashboard(request):
    user = request.user
    today = localdate()
    mes_inicio = today.replace(day=1)

    # Alcance por rol (cobrador: sus leads; supervisor: sus subcarteras; admin/owner: todo),
    # acotado a leads activos -- lo que la persona esta trabajando hoy, no su historial completo.
    leads_base = leads_visibles(user).filter(activo=Lead.ACTIVO)
    # Rango con zona en vez de created_at__date__gte: mismo criterio (mes en hora chilena) pero
    # usa el indice de Action.created_at -- ver core/timeutils.py.
    from core.timeutils import rango_local
    mes_ini_dt, _ = rango_local(mes_inicio, today + datetime.timedelta(days=1))
    gestiones_mes = scope_por_lead(Action.objects.filter(created_at__gte=mes_ini_dt), user)
    totales = _metricas(leads_base, gestiones_mes)

    # Desglose por subcartera, ademas del total: solo tiene sentido para un supervisor con 2+
    # subcarteras visibles (ej. supervisa 2 zonas de una misma cartera). Con 1 sola subcartera el
    # desglose seria identico al total de arriba, asi que no se duplica. admin/owner no lo ven
    # (podrian tener decenas de subcarteras visibles; para eso esta el listado de Carteras).
    desglose_subcarteras = []
    if not es_admin_owner(user):
        subs = list(subcarteras_visibles(user).select_related('cartera'))
        if len(subs) > 1:
            for sub in subs:
                metricas_sub = _metricas(
                    leads_base.filter(subcartera=sub), gestiones_mes.filter(subcartera=sub),
                )
                desglose_subcarteras.append({'subcartera': sub, **metricas_sub})

    compromisos_qs = scope_por_lead(
        PaymentCommitment.objects.filter(fecha_compromiso__gte=today)
        .select_related('lead', 'subcartera__cartera'),
        user,
    ).order_by('fecha_compromiso')
    compromisos_count = compromisos_qs.count()
    compromisos_total = compromisos_qs.aggregate(total=Sum('monto'))['total'] or 0

    return render(request, 'dashboard/dashboard.html', {
        **totales,
        'desglose_subcarteras': desglose_subcarteras,
        'compromisos': compromisos_qs[:20],
        'compromisos_count': compromisos_count,
        'compromisos_total': compromisos_total,
    })
