"""
Alcance de visibilidad por rol, centralizado. Un solo lugar decide que ve cada usuario, para
que todas las vistas queden consistentes:

  - admin / owner        -> todo.
  - supervisor           -> solo las carteras donde esta asignado (Cartera.supervisores).
  - cobrador (collector) -> solo sus leads (asignados o creados).

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


def carteras_visibles(user):
    """Carteras que el usuario puede ver/gestionar."""
    from cartera.models import Cartera
    if es_admin_owner(user):
        return Cartera.objects.all()
    if _tipo(user) == 'supervisor':
        return Cartera.objects.filter(supervisores=user)
    # cobrador: no navega carteras; derivadas de sus leads si hiciera falta.
    return Cartera.objects.filter(subcarteras__leads__assigned_to=user).distinct()


def leads_visibles(user, base=None):
    """Filtra un queryset de Lead (o arranca de todos) segun el alcance del usuario."""
    from .models import Lead
    qs = Lead.objects.all() if base is None else base
    if es_admin_owner(user):
        return qs
    if _tipo(user) == 'supervisor':
        return qs.filter(subcartera__cartera__supervisores=user)
    return qs.filter(Q(assigned_to=user) | Q(created_by=user))


def scope_por_lead(qs, user, lead_field='lead'):
    """Filtra cualquier queryset que cuelgue de un Lead (Payment, Compromiso, Grabacion, Phone...)
    al alcance del usuario. admin/owner no filtran (evita el subquery innecesario)."""
    if es_admin_owner(user):
        return qs
    return qs.filter(**{f'{lead_field}__in': leads_visibles(user)})
