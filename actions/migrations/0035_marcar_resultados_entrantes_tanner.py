"""
Marca como "siempre entrante" los resultados de Tanner que solo pueden darse si el cliente
contesto. La lista sale de medir los 2 meses de reportes que el sistema anterior envio y Tanner
acepto (jun-jul 2026, 55.266 gestiones): son los codigos donde el 95%+ de las gestiones se
reportaron con origen INBOUND.

Los codigos que en esa medicion salen repartidos (ej. 100 PROMESA DE PAGO, 48% entrante) NO se
marcan: ahi el origen depende de quien llamo, y lo elige el gestor en el formulario.
"""
from django.db import migrations

# codigo Tanner -> nombre (solo informativo, el match es por codigo)
CODIGOS_ENTRANTES = {
    '143': 'SIN RESPUESTA CLIENTE',      # 98% entrante en el historico
    '215': 'SIN DINERO',                 # 99%
    '208': 'PROMESA DE PAGO (aval)',     # 100% (volumen bajo)
    '223': 'OTROS (aval)',               # 100% (volumen bajo)
}


def marcar(apps, schema_editor):
    Resultado = apps.get_model('actions', 'Resultado')
    Resultado.objects.filter(
        cartera__nombre__iexact='Tanner', codigo__in=CODIGOS_ENTRANTES,
    ).update(siempre_entrante=True)


def desmarcar(apps, schema_editor):
    Resultado = apps.get_model('actions', 'Resultado')
    Resultado.objects.filter(
        cartera__nombre__iexact='Tanner', codigo__in=CODIGOS_ENTRANTES,
    ).update(siempre_entrante=False)


class Migration(migrations.Migration):

    dependencies = [
        ('actions', '0034_action_origen_resultado_siempre_entrante'),
    ]

    operations = [
        migrations.RunPython(marcar, desmarcar),
    ]
