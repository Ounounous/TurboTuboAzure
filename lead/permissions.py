"""
Alcance de visibilidad por rol, centralizado. Un solo lugar decide que ve cada usuario, para
que todas las vistas queden consistentes:

  - admin / owner        -> todo.
  - supervisor           -> solo las SUBcarteras donde esta asignado (Subcartera.supervisores).
  - cobrador (collector) -> solo sus leads (asignados o creados).

La supervision es por Subcartera, no por Cartera: varias subcarteras pueden compartir una misma
Cartera (ej. "Tanner" con una subcartera por supervisor, para que el reporte regulatorio -- que
busca la cartera por nombre exacto -- siga viendo todo junto) sin que sus supervisores se vean
los clientes entre si. Con una sola subcartera por cartera (el caso comun), el comportamiento es
identico a cuando la supervision era por cartera.

Owner ve todo lo operativo pero NO entra al Django admin (eso depende de is_staff/is_superuser,
no del user_type).
"""
from django.db.models import Q


def _tipo(user):
    profile = getattr(user, 'userprofile', None)
    return profile.user_type if profile else None


def es_admin_owner(user):
    return _tipo(user) in ('admin', 'owner')


def es_supervisor(user):
    """admin/owner/supervisor: todos cuentan como 'supervisor' para lo operativo."""
    return _tipo(user) in ('admin', 'owner', 'supervisor')


def subcarteras_visibles(user):
    """Subcarteras que el usuario puede ver/gestionar (la unidad real de alcance de un
    supervisor). admin/owner: todas. cobrador: no navega subcarteras -- devuelve vacio."""
    from cartera.models import Subcartera
    if es_admin_owner(user):
        return Subcartera.objects.all()
    if _tipo(user) == 'supervisor':
        return Subcartera.objects.filter(supervisores=user)
    return Subcartera.objects.none()


def carteras_visibles(user):
    """Carteras que el usuario puede ver/gestionar (tiene 1+ subcartera visible dentro)."""
    from cartera.models import Cartera
    if es_admin_owner(user):
        return Cartera.objects.all()
    if _tipo(user) == 'supervisor':
        return Cartera.objects.filter(subcarteras__supervisores=user).distinct()
    # cobrador: no navega carteras; derivadas de sus leads si hiciera falta.
    return Cartera.objects.filter(subcarteras__leads__assigned_to=user).distinct()


def leads_visibles(user, base=None):
    """Filtra un queryset de Lead (o arranca de todos) segun el alcance del usuario."""
    from .models import Lead
    qs = Lead.objects.all() if base is None else base
    if es_admin_owner(user):
        return qs
    if _tipo(user) == 'supervisor':
        return qs.filter(subcartera__supervisores=user)
    return qs.filter(Q(assigned_to=user) | Q(created_by=user))


def scope_por_lead(qs, user, lead_field='lead'):
    """Filtra cualquier queryset que cuelgue de un Lead (Payment, Compromiso, Grabacion, Phone...)
    al alcance del usuario. admin/owner no filtran (evita el subquery innecesario)."""
    if es_admin_owner(user):
        return qs
    return qs.filter(**{f'{lead_field}__in': leads_visibles(user)})
