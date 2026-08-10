"""
Detecta (y opcionalmente elimina) gestiones duplicadas: filas identicas en cliente, medio,
resultado y fecha/hora exacta, que quedaron de una carga masiva re-subida antes de que la carga
tuviera control de duplicados.

Por defecto SOLO INFORMA (dry-run). Para borrar de verdad hay que pasar --eliminar, y siempre
conserva la gestion MAS ANTIGUA de cada grupo (la original) borrando solo las copias.

Ejemplos:
    manage.py limpiar_gestiones_duplicadas --cartera Tanner
    manage.py limpiar_gestiones_duplicadas --cartera Tanner --desde 2026-07-29 --hasta 2026-07-31
    manage.py limpiar_gestiones_duplicadas --cartera Tanner --eliminar
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from actions.models import Action


class Command(BaseCommand):
    help = "Informa y opcionalmente elimina gestiones duplicadas (mismo cliente, medio, resultado y fecha/hora)."

    def add_arguments(self, parser):
        parser.add_argument('--cartera', help='Nombre de la cartera (ej. Tanner). Sin esto, revisa todas.')
        parser.add_argument('--desde', help='Fecha inicial YYYY-MM-DD (sobre la fecha de la gestion).')
        parser.add_argument('--hasta', help='Fecha final YYYY-MM-DD (inclusive).')
        parser.add_argument(
            '--eliminar', action='store_true',
            help='Elimina de verdad las copias. Sin esta bandera solo informa.',
        )

    def handle(self, *args, **opts):
        qs = Action.objects.select_related('lead', 'medio', 'resultado')

        cartera = opts.get('cartera')
        if cartera:
            qs = qs.filter(subcartera__cartera__nombre__iexact=cartera)
            if not qs.exists():
                raise CommandError(f"No hay gestiones para la cartera '{cartera}'.")

        for clave, lookup in (('desde', 'created_at__date__gte'), ('hasta', 'created_at__date__lte')):
            valor = opts.get(clave)
            if valor:
                fecha = parse_date(valor)
                if not fecha:
                    raise CommandError(f"--{clave}: '{valor}' no es una fecha valida (usa YYYY-MM-DD).")
                qs = qs.filter(**{lookup: fecha})

        # Agrupa por la misma huella que usa la carga masiva para detectar re-subidas.
        grupos = defaultdict(list)
        for accion in qs.order_by('id').iterator():
            huella = (accion.lead_id, accion.medio_id, accion.resultado_id, accion.created_at)
            grupos[huella].append(accion)

        duplicados = {h: acciones for h, acciones in grupos.items() if len(acciones) > 1}

        total_gestiones = sum(len(a) for a in grupos.values())
        total_sobrantes = sum(len(a) - 1 for a in duplicados.values())

        self.stdout.write(f"Gestiones revisadas:        {total_gestiones}")
        self.stdout.write(f"Grupos con duplicados:      {len(duplicados)}")
        self.stdout.write(self.style.WARNING(f"Copias sobrantes a borrar:  {total_sobrantes}"))

        if not duplicados:
            self.stdout.write(self.style.SUCCESS("\nNo hay gestiones duplicadas."))
            return

        self.stdout.write("\nEjemplos (hasta 15 grupos):")
        for huella, acciones in list(duplicados.items())[:15]:
            base = acciones[0]
            ids_borrar = [a.id for a in acciones[1:]]
            momento = base.created_at.strftime('%d-%m-%Y %H:%M:%S')
            self.stdout.write(
                f"  OP={base.lead.op:<10} {momento}  medio={base.medio.nombre[:14]:<14} "
                f"resultado={base.resultado.nombre[:22]:<22} x{len(acciones)}  "
                f"conserva id={base.id}, borra {ids_borrar}"
            )

        if not opts['eliminar']:
            self.stdout.write(self.style.NOTICE(
                "\nModo informativo (dry-run): no se borro nada.\n"
                "Para eliminar las copias, repite el comando agregando --eliminar"
            ))
            return

        ids_a_borrar = [a.id for acciones in duplicados.values() for a in acciones[1:]]
        with transaction.atomic():
            borradas, _ = Action.objects.filter(id__in=ids_a_borrar).delete()
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {len(ids_a_borrar)} gestion(es) duplicada(s) eliminada(s). "
            f"Se conservo la mas antigua de cada grupo."
        ))
