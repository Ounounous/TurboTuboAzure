"""
Carga el arbol de gestiones de Tanner. A diferencia de Galgo, Tanner no entrega un Excel
con columnas Medio/Resultado/Contactabilidad -- el "Instructivo base de gestiones - Tanner
Automotriz (version 11)" define dos tablas de codigos independientes:

  Tabla 6 "Medio contacto" (codigo 1-8): Manual, Discador, Terreno, IVR, SMS, Email, WhatsApp, Bot
  Tabla 5 "Paleta de respuestas" (codigo 100-800): TIPO_CONTACTO + RESPUESTA + si exige fecha
  de compromiso ("FECHA COMPROMISO" = OBLIGATORIO en el instructivo)

Los datos de ambas tablas se transcribieron a mano desde el .docx (no hay Excel/CSV fuente
para parsear automaticamente). Este comando no necesita argumentos de archivo.
"""
from django.core.management.base import BaseCommand, CommandError

from actions.models import Medio, Resultado
from cartera.models import Cartera

MEDIOS = [
    # (codigo, nombre, canal, es_llamada)
    ('1', 'Manual', Medio.CANAL_TELEFONO, True),
    ('2', 'Discador', Medio.CANAL_TELEFONO, True),
    ('3', 'Terreno', Medio.CANAL_TELEFONO, False),
    ('4', 'IVR', Medio.CANAL_TELEFONO, True),
    ('5', 'SMS', Medio.CANAL_TELEFONO, False),
    ('6', 'Email', Medio.CANAL_EMAIL, False),
    ('7', 'WhatsApp', Medio.CANAL_TELEFONO, False),
    ('8', 'Bot', Medio.CANAL_TELEFONO, False),
]

# (codigo, tipo_contacto, respuesta, requiere_fecha_pago)
RESULTADOS = [
    ('100', 'DIRECTO', 'PROMESA DE PAGO', True),
    ('101', 'DIRECTO', 'INTENCION DE PAGO', True),
    ('102', 'DIRECTO', 'YA PAGO', False),
    ('103', 'DIRECTO', 'PAGADO', False),
    ('104', 'DIRECTO', 'EN PROCESO DE DACION', False),
    ('105', 'DIRECTO', 'EN PROCESO DE RENEGOCIACION', False),
    ('106', 'DIRECTO', 'INCAUTADO/REMATADO', False),
    ('107', 'DIRECTO', 'NO ES LA FECHA QUE PACTO', False),
    ('108', 'DIRECTO', 'DICE HABER PAGADO', False),
    ('109', 'DIRECTO', 'SIN MODALIDAD DE PAGO', False),
    ('110', 'DIRECTO', 'SINIESTRO', False),
    ('111', 'DIRECTO', 'DESCONOCE DEUDA', False),
    ('112', 'DIRECTO', 'PAGA TERCERO O AVAL', False),
    ('113', 'DIRECTO', 'CESANTE', False),
    ('114', 'DIRECTO', 'ENFERMEDAD / LICENCIA MEDICA', False),
    ('115', 'DIRECTO', 'PROBLEMAS FINANCIEROS', False),
    ('116', 'DIRECTO', 'SOLICITA LLAMADO POSTERIOR', False),
    ('117', 'DIRECTO', 'NO QUIERE PAGAR', False),
    ('118', 'DIRECTO', 'NEGOCIACIÓN POR EMAIL', False),
    ('119', 'DIRECTO', 'NEGOCIACIÓN POR WHATSAPP', False),
    ('120', 'DIRECTO', 'VACACIONES', False),
    ('121', 'DIRECTO', 'TRAMITANDO SEGURO', False),
    ('122', 'DIRECTO', 'CONTINGENCIA', False),
    ('123', 'DIRECTO', 'RESPUESTA AGRESIVA', False),
    ('124', 'DIRECTO', 'OTROS', False),
    ('125', 'DIRECTO', 'INTENCION DE DACIÓN', True),
    ('126', 'DIRECTO', 'INTENCION DE RENEGOCIACIÓN', True),
    ('127', 'DIRECTO', 'CITACIÓN ENTREGADA A TITULAR', False),
    ('128', 'DIRECTO', 'AUTORIZA LLAMADO POSTERIOR', False),
    ('129', 'DIRECTO', 'PAC INTERESADO', False),
    ('130', 'DIRECTO', 'PAC CONTRATADO WEB', False),
    ('131', 'DIRECTO', 'PAC CONTRATADO FÍSICO', False),
    ('132', 'DIRECTO', 'PAGARA POR OTROS MEDIOS', False),
    ('133', 'DIRECTO', 'NO BANCARIZADO', False),
    ('134', 'DIRECTO', 'BANCO SIN CONVENIO', False),
    ('135', 'DIRECTO', 'NO INTERESADO SIN MOTIVO', False),
    ('136', 'DIRECTO', 'YA TIENE PAC', False),
    ('137', 'DIRECTO', 'INTERESADO EN VENTA DIRECTA', False),
    ('138', 'DIRECTO', 'NO INTERESADO EN VENTA DIRECTA (OTROS)', False),
    ('139', 'DIRECTO', 'REGULARIZARA POR OTRO MEDIO', False),
    ('140', 'DIRECTO', 'VEHICULO COMO HERRAMIENTA DE TRABAJO', False),
    ('141', 'DIRECTO', 'INFORMACION ENVIADA A TANNER', False),
    ('142', 'DIRECTO', 'EN LICITACIÓN CONCESIONARIOS', False),
    ('143', 'DIRECTO', 'SIN RESPUESTA CLIENTE', False),
    ('144', 'DIRECTO', 'SIN GESTION CONCESIONARIO', False),
    ('145', 'DIRECTO', 'EN PROCESO REVISION VEHICULO', False),
    ('146', 'DIRECTO', 'DISCONFORMIDAD POR PRECIO', False),
    ('147', 'DIRECTO', 'SIN RESPUESTA OFERTA', False),
    ('148', 'DIRECTO', 'SIN CONTACTO CONCESIONARIO', False),
    ('149', 'DIRECTO', 'VEHICULO EN MAL ESTADO', False),
    ('150', 'DIRECTO', 'VEHICULO CON DEMASIADO KM', False),
    ('151', 'DIRECTO', 'VEHICULO CON ANOTACIONES EN TRAMITE', False),
    ('152', 'DIRECTO', 'VEHICULO NO COMERCIAL', False),
    ('153', 'DIRECTO', 'VENDIDO', False),
    ('200', 'DIRECTO AVAL', 'PROMESA DE PAGO', True),
    ('201', 'DIRECTO AVAL', 'INTENCION DE PAGO', True),
    ('202', 'DIRECTO AVAL', 'YA PAGO', False),
    ('203', 'DIRECTO AVAL', 'PAGADO', False),
    ('204', 'DIRECTO AVAL', 'EN PROCESO DE DACION', False),
    ('205', 'DIRECTO AVAL', 'EN PROCESO DE RENEGOCIACION', False),
    ('206', 'DIRECTO AVAL', 'INCAUTADO/REMATADO', False),
    ('207', 'DIRECTO AVAL', 'NO ES LA FECHA QUE PACTO', False),
    ('208', 'DIRECTO AVAL', 'DICE HABER PAGADO', False),
    ('209', 'DIRECTO AVAL', 'SIN MODALIDAD DE PAGO', False),
    ('210', 'DIRECTO AVAL', 'SINIESTRO', False),
    ('211', 'DIRECTO AVAL', 'DESCONOCE DEUDA', False),
    ('213', 'DIRECTO AVAL', 'CESANTE', False),
    ('214', 'DIRECTO AVAL', 'ENFERMO', False),
    ('215', 'DIRECTO AVAL', 'SIN DINERO', False),
    ('216', 'DIRECTO AVAL', 'SOLICITA LLAMADO POSTERIOR', False),
    ('217', 'DIRECTO AVAL', 'NO QUIERE PAGAR', False),
    ('218', 'DIRECTO AVAL', 'VACACIONES', False),
    ('219', 'DIRECTO AVAL', 'TRAMITANDO SEGURO', False),
    ('220', 'DIRECTO AVAL', 'CONTINGENCIA', False),
    ('221', 'DIRECTO AVAL', 'RESPUESTA AGRESIVA', False),
    ('222', 'DIRECTO AVAL', 'OTROS', False),
    ('223', 'DIRECTO AVAL', 'AUTORIZA LLAMADO POSTERIOR', False),
    ('300', 'INDIRECTO', 'FALLECIDO', False),
    ('301', 'INDIRECTO', 'PAGA TERCERO', False),
    ('302', 'INDIRECTO', 'SE DEJA RECADO CON FAMILIAR', False),
    ('303', 'INDIRECTO', 'SE DEJA RECADO CON TERCERO', False),
    ('304', 'INDIRECTO', 'TERCERO / FAMILIAR LLAMAR MAS TARDE', False),
    ('305', 'INDIRECTO', 'TERCERO NO CONOCE A DEUDOR', False),
    ('306', 'INDIRECTO', 'DIRECCIÓN CONFIRMADA CON VECINO', False),
    ('307', 'INDIRECTO', 'CITACIÓN RECIBIDA POR TERCERO', False),
    ('308', 'INDIRECTO', 'TERCERO CONFIRMA CAMBIO DE DOMICILIO', False),
    ('309', 'INDIRECTO', 'REHUSA ATENCIÓN', False),
    ('310', 'INDIRECTO', 'AUTORIZA LLAMADO POSTERIOR', False),
    ('400', 'SIN CONTACTO OPERADOR', 'SIN CONTACTO BUZON DE VOZ', False),
    ('401', 'SIN CONTACTO OPERADOR', 'SIN CONTACTO NO CONTESTA', False),
    ('402', 'SIN CONTACTO OPERADOR', 'TELEFONO NO CORRESPONDE', False),
    ('403', 'SIN CONTACTO OPERADOR', 'CORTA LLAMADO', False),
    ('404', 'SIN CONTACTO OPERADOR', 'BUSQUEDA DE DATOS', False),
    ('405', 'SIN CONTACTO OPERADOR', 'SIN DATOS DEMOGRAFICOS', False),
    ('500', 'SIN CONTACTO MAQUINA', 'SIN OPERADOR DISPONIBLE (DROP)', False),
    ('501', 'SIN CONTACTO MAQUINA', 'SIN CONTACTO MAQUINA', False),
    ('510', 'SIN CONTACTO TERRENO', 'DIRECCIÓN NO CORRESPONDE', False),
    ('511', 'SIN CONTACTO TERRENO', 'DIRECCIÓN INEXISTENTE', False),
    ('512', 'SIN CONTACTO TERRENO', 'DIRECCIÓN DE CONOCIDO', False),
    ('513', 'SIN CONTACTO TERRENO', 'SIN MORADORES', False),
    ('514', 'SIN CONTACTO TERRENO', 'LUGAR INACCESIBLE', False),
    ('600', 'ACCION MASIVA', 'ENVIO SMS ENTREGADO', False),
    ('601', 'ACCION MASIVA', 'ENVIO CARTA ENTREGADO', False),
    ('602', 'ACCION MASIVA', 'ENVIO EMAIL ENTREGADO', False),
    ('603', 'ACCION MASIVA', 'ENVIO WHATSAPP ENTREGADO', False),
    ('604', 'ACCION MASIVA', 'ENVIO IVR ENTREGADO', False),
    ('605', 'ACCION MASIVA', 'ENVIO SMS NO ENTREGADO', False),
    ('606', 'ACCION MASIVA', 'ENVIO CARTA NO ENTREGADO', False),
    ('607', 'ACCION MASIVA', 'ENVIO EMAIL NO ENTREGADO', False),
    ('608', 'ACCION MASIVA', 'ENVIO WHATSAPP NO ENTREGADO', False),
    ('609', 'ACCION MASIVA', 'ENVIO IVR INCOMPLETO', False),
    ('610', 'ACCION MASIVA', 'ENVIO IVR NO ENTREGADO', False),
    ('800', 'SIN GESTION', 'SIN GESTION', False),
]

# Estos tipo_contacto implican que efectivamente se hablo con una persona.
TIPOS_CONTACTO_CON_CONTACTO = {'DIRECTO', 'DIRECTO AVAL', 'INDIRECTO'}


class Command(BaseCommand):
    help = "Carga el arbol de gestiones de Tanner (medios y resultados transcritos del instructivo oficial)."

    def handle(self, *args, **options):
        try:
            cartera = Cartera.objects.get(nombre__iexact='Tanner')
        except Cartera.DoesNotExist:
            raise CommandError("No existe la cartera 'Tanner'. Creala primero en /dashboard/carteras/.")

        medios_creados = 0
        for codigo, nombre, canal, es_llamada in MEDIOS:
            medio, created = Medio.objects.get_or_create(
                cartera=cartera, nombre=nombre,
                defaults={'canal': canal, 'es_llamada': es_llamada, 'codigo': codigo},
            )
            medio.codigo = codigo
            medio.canal = canal
            medio.es_llamada = es_llamada
            medio.permite_manual = medio.calcular_permite_manual()
            medio.save(update_fields=['codigo', 'canal', 'es_llamada', 'permite_manual'])
            if created:
                medios_creados += 1

        resultados_creados, resultados_actualizados = 0, 0
        for codigo, tipo_contacto, respuesta, requiere_fecha_pago in RESULTADOS:
            con_contacto = tipo_contacto in TIPOS_CONTACTO_CON_CONTACTO
            resultado, created = Resultado.objects.get_or_create(
                cartera=cartera, nombre=respuesta, tipo_contacto=tipo_contacto,
            )
            resultado.codigo = codigo
            resultado.contactabilidad = Resultado.CON_CONTACTO if con_contacto else Resultado.SIN_CONTACTO
            resultado.crea_compromiso = requiere_fecha_pago
            resultado.requiere_fecha_pago = requiere_fecha_pago
            if created:
                # Tanner no distingue por medio en su paleta -- cualquier resultado "DIRECTO"
                # puede darse por llamada manual/discador/IVR, que si tienen grabacion.
                resultado.descarga_grabacion = con_contacto
                resultados_creados += 1
            else:
                resultados_actualizados += 1
            resultado.save()

        self.stdout.write(self.style.SUCCESS(
            f"Cartera 'Tanner': {medios_creados} medio(s) nuevo(s), "
            f"{resultados_creados} resultado(s) nuevo(s), {resultados_actualizados} actualizado(s)."
        ))
