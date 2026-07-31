from django.db import migrations


# PAC / Venta Directa (cod. 129-153): campaña de venta de vehiculo, no gestion de cobranza -- la
# paleta oficial de Tanner los marca "NO VAN A GESTIONES USUARIOS". Corrige las filas de Resultado
# ya sembradas en la base (ver actions/arbol_templates.py, que ya trae la regla para instalaciones
# nuevas/reimportaciones).
TANNER_CODIGOS_NO_MANUAL = {str(c) for c in range(129, 154)}


def marcar_no_manual(apps, schema_editor):
    Resultado = apps.get_model('actions', 'Resultado')
    Resultado.objects.filter(
        cartera__nombre='Tanner', codigo__in=TANNER_CODIGOS_NO_MANUAL,
    ).update(permite_manual=False)


def revertir(apps, schema_editor):
    Resultado = apps.get_model('actions', 'Resultado')
    Resultado.objects.filter(
        cartera__nombre='Tanner', codigo__in=TANNER_CODIGOS_NO_MANUAL,
    ).update(permite_manual=True)


class Migration(migrations.Migration):

    dependencies = [
        ('actions', '0030_resultado_permite_manual'),
    ]

    operations = [
        migrations.RunPython(marcar_no_manual, revertir),
    ]
