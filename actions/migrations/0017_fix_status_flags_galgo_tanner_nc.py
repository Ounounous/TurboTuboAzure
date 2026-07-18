# Corrige los Resultado ya sembrados en la BD para que el status calculado (ver
# actions/status_logic.py) coincida con lo que se definio revisando los arboles de gestion de
# Galgo, Tanner y Nuevo Capital fila por fila:
#   - Galgo: DACION crea compromiso (con fecha); PAGO / CONTENIDO y PAGO / AL DIA marcan pago.
#   - Tanner: "intencion de pago/dacion/renegociacion" dejan de crear compromiso (hoy si lo
#     hacen) -- quedan en Contactado. "Paga tercero (o aval)" marca Pagando.
#   - Nuevo Capital: "paga tercero (o aval)" marca Pagando.
from django.db import migrations


def fix_resultados(apps, schema_editor):
    Resultado = apps.get_model('actions', 'Resultado')

    # --- Galgo: tipo_contacto siempre vacio (no distingue por medio). ---
    Resultado.objects.filter(cartera__nombre__iexact='Galgo', nombre__iexact='DACION').update(
        crea_compromiso=True, requiere_fecha_pago=True,
    )
    Resultado.objects.filter(cartera__nombre__iexact='Galgo', nombre__iexact='PAGO / CONTENIDO').update(
        efecto_pago='pagando',
    )
    Resultado.objects.filter(cartera__nombre__iexact='Galgo', nombre__iexact='PAGO / AL DIA').update(
        efecto_pago='al_dia',
    )

    # --- Tanner: "intencion de" ya no crea compromiso (queda en Contactado). ---
    Resultado.objects.filter(
        cartera__nombre__iexact='Tanner',
        nombre__iexact='INTENCION DE PAGO',
        tipo_contacto__in=['DIRECTO', 'DIRECTO AVAL'],
    ).update(crea_compromiso=False, requiere_fecha_pago=False)
    Resultado.objects.filter(
        cartera__nombre__iexact='Tanner', nombre__istartswith='INTENCION DE DACI', tipo_contacto='DIRECTO',
    ).update(crea_compromiso=False, requiere_fecha_pago=False)
    Resultado.objects.filter(
        cartera__nombre__iexact='Tanner', nombre__istartswith='INTENCION DE RENEGOCIACI', tipo_contacto='DIRECTO',
    ).update(crea_compromiso=False, requiere_fecha_pago=False)

    # --- Tanner y Nuevo Capital: "paga tercero (o aval)" marca Pagando. ---
    Resultado.objects.filter(
        cartera__nombre__iexact='Tanner', nombre__icontains='PAGA TERCERO',
    ).update(efecto_pago='pagando')
    Resultado.objects.filter(
        cartera__nombre__iexact='Nuevo Capital', nombre__icontains='PAGA TERCERO',
    ).update(efecto_pago='pagando')


class Migration(migrations.Migration):

    dependencies = [
        ('actions', '0016_resultado_efecto_pago'),
    ]

    operations = [
        migrations.RunPython(fix_resultados, migrations.RunPython.noop),
    ]
