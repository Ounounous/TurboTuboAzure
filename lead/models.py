from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.db import models
from django.apps import apps

from team.models import Team

class Lead(models.Model):
    JUDICIAL = 'judicial'
    EXTRAJUDICIAL = 'extra judicial'

    CHOICES_TIPO_COBRANZA = (
        (JUDICIAL, 'Judicial'),
        (EXTRAJUDICIAL, 'Extra judicial')
    )

    RECIEN_ASIGNADO = 'recien asignado'
    INUBICABLE = 'inubicable'
    NO_CONTACTADO = 'no contactado'
    CONTACTADO = 'contactado'
    COMPROMISO = 'compromiso'
    COMPROMISO_ROTO = 'compromiso roto'
    PAGANDO = 'pagando'
    AL_DIA = 'al dia'

    CHOICES_STATUS = (
        (RECIEN_ASIGNADO, 'Recién asignado'),
        (INUBICABLE, 'Inubicable'),
        (NO_CONTACTADO, 'No contactado'),
        (CONTACTADO, 'Contactado'),
        (COMPROMISO, 'Compromiso de pago'),
        (COMPROMISO_ROTO, 'Compromiso roto'),
        (PAGANDO, 'Pagando'),
        (AL_DIA, 'Al dia'),
    )

    # Ranking para status_historico ("el mejor status que el lead alcanzo alguna vez"): mas alto
    # = mejor. Compromiso roto queda al nivel de Contactado (una promesa incumplida no es un
    # logro), no entre Compromiso y Pagando.
    STATUS_RANK = {
        RECIEN_ASIGNADO: 0,
        INUBICABLE: 0,
        NO_CONTACTADO: 1,
        CONTACTADO: 2,
        COMPROMISO_ROTO: 2,
        COMPROMISO: 3,
        PAGANDO: 4,
        AL_DIA: 5,
    }

    VIGENTE = 'vigente'
    CASTIGO = 'castigo'

    CHOICES_CICLO_CARTERA = (
        (VIGENTE, 'Vigente'),
        (CASTIGO, 'Castigo'),
    )


    C1 = 'C1'
    C2 = 'C2'
    C3 = 'C3'
    C4 = 'C4'
    C5 = 'C5'
    C6 = 'C6'
    C7 = 'C7'
    C8 = 'C8'
    C9 = 'C9'
    C10 = 'C10'
    C11 = 'C11'
    C12 = 'C12'
    C13 = 'C13'
    CASTIGO = 'castigo'
    NO_DEFINIDO = 'no definido'
   

    CHOICES_CICLO = (
        (C1, 'C1'),
        (C2, 'C2'), 
        (C3, 'C3'),
        (C4, 'C4'),
        (C5, 'C5'),
        (C6, 'C6'),
        (C7, 'C7'),
        (C8, 'C8'),
        (C9, 'C9'),
        (C10, 'C10'),
        (C11, 'C11'),
        (C12, 'C12'),
        (C13, 'C13'),
        (CASTIGO, 'Castigo'),
        (NO_DEFINIDO, 'No definido'),
    )

    # "activo" es el ciclo de vida del lead (distinto del status de cobranza): dice si hay que
    # gestionarlo y, cuando ya no, por que. Se maneja desde el menu Suspensiones y por la
    # transicion automatica al dia -> terminado (ver lead/lifecycle.py y actions/status_logic.py).
    ACTIVO = 'activo'
    SUSPENDIDO = 'suspendido'
    TERMINADO = 'terminado'
    DESASIGNADO = 'desasignado'

    CHOICES_ACTIVO = (
        (ACTIVO, 'Activo'),
        (SUSPENDIDO, 'Suspendido'),
        (TERMINADO, 'Terminado'),
        (DESASIGNADO, 'Desasignado'),
    )

    # Estados en los que NO se puede ingresar una gestion (Action) ni originar llamada/whatsapp/
    # mail: suspendido (orden judicial o del cliente) y terminado (ya pago toda la deuda). Las
    # notas siguen permitidas siempre. Desasignado no bloquea: al no tener asignado, simplemente
    # nadie lo gestiona hasta reasignarlo (y reasignar lo vuelve a activo).
    ACTIVO_NO_GESTIONABLE = (SUSPENDIDO, TERMINADO)

    SI = 'si'
    NO = 'no'
   

    CHOICES_AVAL = (
        (SI, 'Si'),
        (NO, 'No'),
    )

    team = models.ForeignKey(Team, related_name='leads', on_delete=models.CASCADE)
    op = models.CharField(max_length=16)
    name = models.CharField(max_length=255)
    rut = models.IntegerField()
    dv = models.CharField(max_length=255)
    saldo_insoluto = models.IntegerField()
    saldo_deuda = models.IntegerField()
    valor_cuota = models.IntegerField()
    cuotas_atrasadas = models.IntegerField()
    subcartera = models.ForeignKey('cartera.Subcartera', related_name='leads', on_delete=models.PROTECT)
    tipo_cobranza = models.CharField(max_length=15, choices=CHOICES_TIPO_COBRANZA, default=EXTRAJUDICIAL)
    status = models.CharField(max_length=20, choices=CHOICES_STATUS, default=RECIEN_ASIGNADO)
    # Mejor status que el lead alcanzo alguna vez (no baja aunque "status" si, ej. tras el
    # reseteo mensual o un compromiso roto). Se actualiza junto con "status" en apply_status()
    # (actions/status_logic.py), nunca a mano.
    status_historico = models.CharField(max_length=20, choices=CHOICES_STATUS, default=RECIEN_ASIGNADO)
    ciclo_cartera = models.CharField(max_length=255, choices=CHOICES_CICLO_CARTERA, default=VIGENTE)
    ciclo = models.CharField(max_length=255, choices=CHOICES_CICLO, default=NO_DEFINIDO)
    activo = models.CharField(max_length=255, choices=CHOICES_ACTIVO, default=ACTIVO)
    # Momento en que el lead entro a cada estado no-activo. Se llenan solos en la transicion
    # (lead/lifecycle.py) y son la base del calculo de purga de datos (fase 2): terminado se
    # purga a los N dias del fin del mes en que se declaro; desasignado a los M dias.
    terminado_at = models.DateField(null=True, blank=True)
    desasignado_at = models.DateField(null=True, blank=True)
    suspendido_at = models.DateField(null=True, blank=True)
    # Fecha en que se purgaron los datos accesorios (gestiones, notas) de este lead por retencion
    # (actions.tasks.purgar_gestiones_ciclo_vida, fase 2). Deja la purga idempotente (no re-escanea
    # ni re-purga) y sirve de evidencia de cumplimiento (Ley 21.719): consta cuando se depuro. Se
    # limpia si el lead se reactiva (vuelve a gestionarse). Ley 21.719: al cesar la finalidad del
    # tratamiento, los datos accesorios no se conservan indefinidamente.
    datos_purgados_at = models.DateField(null=True, blank=True)
    motivo_suspension = models.CharField(max_length=255, blank=True)
    tiene_aval = models.CharField(max_length=2, choices=CHOICES_AVAL, default=NO)
    fecha_compromiso_pago = models.DateField(null=True, blank=True)
    # SET_NULL (no CASCADE): quien creo/subio el lead es solo metadata de origen -- borrar a ese
    # usuario (ver configuracion/user_deletion.py) NO debe destruir clientes reales.
    created_by = models.ForeignKey(User, related_name='leads', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    assigned_to = models.ForeignKey(User, related_name='assigned_leads', on_delete=models.SET_NULL, null=True, blank=True)
    # Favoritos por usuario: cada ejecutivo marca sus propios clientes destacados.
    favorited_by = models.ManyToManyField(User, related_name='favorite_leads', blank=True)

    # Color semántico del status para la UI (separado del color de marca).
    STATUS_COLOR = {
        RECIEN_ASIGNADO: 'blue',
        INUBICABLE: 'amber',
        NO_CONTACTADO: 'slate',
        CONTACTADO: 'blue',
        COMPROMISO: 'teal',
        COMPROMISO_ROTO: 'red',
        PAGANDO: 'green',
        AL_DIA: 'green',
    }

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.op

    @property
    def status_color(self):
        return self.STATUS_COLOR.get(self.status, 'slate')

    @property
    def es_gestionable(self):
        """False si no se le puede ingresar una gestion (suspendido o terminado)."""
        return self.activo not in self.ACTIVO_NO_GESTIONABLE

    @property
    def motivo_no_gestionable(self):
        """Texto a mostrar cuando se intenta gestionar un lead no gestionable."""
        if self.activo == self.SUSPENDIDO:
            base = 'Cliente suspendido'
            return f'{base}: {self.motivo_suspension}' if self.motivo_suspension else base
        if self.activo == self.TERMINADO:
            return 'Cliente terminado (deuda pagada)'
        return ''

class StatusChangeLog(models.Model):
    lead = models.ForeignKey('Lead', on_delete=models.CASCADE)
    # Null = cambio automatico sin un usuario detras (reseteo mensual, compromiso roto detectado
    # por la tarea diaria). Antes era obligatorio porque solo el editor manual escribia aca.
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    new_status = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        quien = self.changed_by.username if self.changed_by else 'sistema'
        return f"Lead {self.lead.id} status changed to {self.new_status} by {quien}"

class LeadFile(models.Model):
    # Tope de archivos por lead y de tamano por archivo. Se validan en la vista/form; se dejan
    # aca como fuente unica de verdad.
    MAX_POR_LEAD = 3
    MAX_BYTES = 10 * 1024 * 1024  # 10 MB
    EXTENSIONES = ['png', 'jpg', 'jpeg', 'pdf', 'mp3']

    team = models.ForeignKey(Team, related_name='lead_files', on_delete=models.CASCADE)
    lead = models.ForeignKey(Lead, related_name='files', on_delete=models.CASCADE)
    file = models.FileField(upload_to='leadfiles/', validators=[FileExtensionValidator(EXTENSIONES)])
    # SET_NULL (no CASCADE): borrar a quien lo subio no debe borrar el archivo adjunto.
    created_by = models.ForeignKey(User, related_name='lead_files', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def filename(self):
        """Nombre del archivo subido, sin la ruta de almacenamiento (leadfiles/...)."""
        import os
        return os.path.basename(self.file.name) if self.file else ''

    def __str__(self):
        return self.created_by.username if self.created_by else self.filename

class LeadAssignment(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='lead_assignments')
    # SET_NULL (no CASCADE): borrar a quien hizo la asignacion no debe borrar el rastro historico.
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments_made'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)


class LeadNote(models.Model):
    """
    Nota interna sobre un lead. A diferencia de una gestión (Action), la nota NO entra en los
    reportes de cartera (Tanner/Nuevo Capital/Galgo): es un recordatorio del equipo, visible al
    abrir el detalle del lead y el formulario de gestión.

    Pensada como base del futuro motor de tareas: una nota podrá convertirse en tarea con fecha
    de vencimiento y responsable. Por ahora se mantiene simple (solo el texto y quién la creó).
    """
    lead = models.ForeignKey(Lead, related_name='notes', on_delete=models.CASCADE)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='lead_notes')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Nota de {self.author} en {self.lead.op}"