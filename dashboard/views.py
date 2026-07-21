from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils.timezone import localdate

from actions.models import Action, PaymentCommitment, Resultado
from lead.models import Lead
from lead.permissions import leads_visibles, scope_por_lead


@login_required
def dashboard(request):
    user = request.user
    today = localdate()
    mes_inicio = today.replace(day=1)

    # Alcance por rol (cobrador: sus leads; supervisor: su cartera; admin/owner: todo), acotado
    # a leads activos -- lo que la persona esta trabajando hoy, no su historial completo.
    leads_base = leads_visibles(user).filter(activo=Lead.ACTIVO)
    n_clientes = leads_base.count()
    saldo_total = leads_base.aggregate(total=Sum('saldo_insoluto'))['total'] or 0

    gestiones_mes = scope_por_lead(Action.objects.filter(created_at__date__gte=mes_inicio), user)
    total_gestiones_mes = gestiones_mes.count()
    con_contacto_mes = gestiones_mes.filter(resultado__contactabilidad=Resultado.CON_CONTACTO).count()
    contactabilidad_pct = round(100 * con_contacto_mes / total_gestiones_mes) if total_gestiones_mes else 0

    compromisos_qs = scope_por_lead(
        PaymentCommitment.objects.filter(fecha_compromiso__gte=today)
        .select_related('lead', 'subcartera__cartera'),
        user,
    ).order_by('fecha_compromiso')
    compromisos_count = compromisos_qs.count()
    compromisos_total = compromisos_qs.aggregate(total=Sum('monto'))['total'] or 0

    return render(request, 'dashboard/dashboard.html', {
        'n_clientes': n_clientes,
        'saldo_total': saldo_total,
        'contactabilidad_pct': contactabilidad_pct,
        'total_gestiones_mes': total_gestiones_mes,
        'compromisos': compromisos_qs[:20],
        'compromisos_count': compromisos_count,
        'compromisos_total': compromisos_total,
    })
