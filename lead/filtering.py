"""
Filtros de la pagina Clientes, extraidos para reusarlos donde haga falta el mismo criterio sobre
Lead (hoy: Clientes y los exports de demografia en Estado de Telefonos/Correos). Un solo lugar
evita que las dos vistas terminen filtrando distinto.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils.timezone import localdate

# Filtros por columna (ademas del buscador general por ID/RUT/nombre). Nombre del parametro GET
# -> lookup en el queryset.
COLUMN_FILTERS = {
    'op': 'op__icontains',
    'name': 'name__icontains',
    'rut': 'rut__icontains',
    'status': 'status',
    'ciclo': 'ciclo',
    'ciclo_cartera': 'ciclo_cartera',
    'activo': 'activo',
    'tipo_cobranza': 'tipo_cobranza',
    'tiene_aval': 'tiene_aval',
    'cartera': 'subcartera__cartera__nombre__icontains',
    # Opcion cerrada (select), no texto libre: el valor es el id de la subcartera, no el nombre --
    # evita ambiguedad si dos carteras distintas tienen una subcartera con el mismo nombre.
    'subcartera': 'subcartera_id',
}

# Columnas numericas con filtro de rango (parametros "<clave>_min"/"<clave>_max" en la URL).
RANGE_FILTERS = {
    'insoluto': 'saldo_insoluto',
    'deuda': 'saldo_deuda',
    'cuota': 'valor_cuota',
    'atrasadas': 'cuotas_atrasadas',
}


def aplicar_filtros_clientes(queryset, params, user):
    """Aplica al queryset (ya acotado por leads_visibles) los mismos filtros que la pagina
    Clientes: favoritos, buscador general (op/nombre/rut), columnas, rangos y dias desde la
    ultima gestion. Si se van a usar dias_min/dias_max, el queryset debe traer el annotate
    last_action_at=Max('actions__created_at')."""
    if params.get('fav') == '1':
        queryset = queryset.filter(favorited_by=user)

    q = (params.get('q') or '').strip()
    if q:
        queryset = queryset.filter(Q(op__icontains=q) | Q(name__icontains=q) | Q(rut__icontains=q))

    for param, lookup in COLUMN_FILTERS.items():
        value = (params.get(param) or '').strip()
        if value:
            queryset = queryset.filter(**{lookup: value})

    for param, field in RANGE_FILTERS.items():
        min_raw = (params.get(f'{param}_min') or '').strip()
        max_raw = (params.get(f'{param}_max') or '').strip()
        if min_raw:
            try:
                queryset = queryset.filter(**{f'{field}__gte': int(min_raw)})
            except ValueError:
                pass
        if max_raw:
            try:
                queryset = queryset.filter(**{f'{field}__lte': int(max_raw)})
            except ValueError:
                pass

    # "Dias desde ultima gestion": min = al menos N dias sin gestionar (incluye los que NUNCA se
    # han gestionado, ya que tambien califican como "al menos N dias"); max = como maximo N dias
    # (excluye los nunca gestionados, que no tienen una gestion "reciente").
    dias_min = (params.get('dias_min') or '').strip()
    dias_max = (params.get('dias_max') or '').strip()
    if dias_min:
        try:
            corte = localdate() - timedelta(days=int(dias_min))
            queryset = queryset.filter(Q(last_action_at__date__lte=corte) | Q(last_action_at__isnull=True))
        except ValueError:
            pass
    if dias_max:
        try:
            corte = localdate() - timedelta(days=int(dias_max))
            queryset = queryset.filter(last_action_at__date__gte=corte)
        except ValueError:
            pass

    return queryset


def filtros_activos(params):
    """Dict {param: valor} de todos los filtros de Clientes presentes en params, para volver a
    pintar el formulario ya lleno (usado por la pagina Clientes y por los exports de demografia)."""
    range_params = [f'{p}_min' for p in RANGE_FILTERS] + [f'{p}_max' for p in RANGE_FILTERS]
    range_params += ['dias_min', 'dias_max']
    keys = list(COLUMN_FILTERS) + range_params
    return {p: params.get(p, '') for p in keys}
