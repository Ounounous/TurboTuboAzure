# Generated by Django 5.1.1 on 2024-10-16 16:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lead', '0006_leadfile'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='lead',
            name='description',
        ),
        migrations.RemoveField(
            model_name='lead',
            name='email',
        ),
        migrations.RemoveField(
            model_name='lead',
            name='priority',
        ),
        migrations.AddField(
            model_name='lead',
            name='activo',
            field=models.CharField(choices=[('activo', 'Activo'), ('suspendido', 'Suspendido'), ('terminado', 'Terminado')], default='activo', max_length=255),
        ),
        migrations.AddField(
            model_name='lead',
            name='cartera',
            field=models.CharField(choices=[('tanner', 'Tanner'), ('galgo', 'Galgo')], default='galgo', max_length=255),
        ),
        migrations.AddField(
            model_name='lead',
            name='ciclo',
            field=models.CharField(choices=[('C1', 'C1'), ('C2', 'C2'), ('C3', 'C3'), ('C4', 'C4'), ('C5', 'C5'), ('C6', 'C6'), ('C7', 'C7'), ('C8', 'C8'), ('C9', 'C9'), ('C10', 'C10'), ('C11', 'C11'), ('C12', 'C12'), ('C13', 'C13'), ('castigo', 'Castigo'), ('no definido', 'No definido')], default='no definido', max_length=255),
        ),
        migrations.AddField(
            model_name='lead',
            name='ciclo_cartera',
            field=models.CharField(choices=[('vigente', 'Vigente'), ('castigo', 'Castigo')], default='vigente', max_length=255),
        ),
        migrations.AddField(
            model_name='lead',
            name='cuotas_atrasadas',
            field=models.IntegerField(default=99),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='lead',
            name='dv',
            field=models.IntegerField(default=99),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='lead',
            name='op',
            field=models.CharField(default=0, max_length=16),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='lead',
            name='rut',
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='lead',
            name='saldo_deuda',
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='lead',
            name='saldo_insoluto',
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='lead',
            name='tiene_aval',
            field=models.CharField(choices=[('si', 'Si'), ('no', 'No')], default='no', max_length=2),
        ),
        migrations.AddField(
            model_name='lead',
            name='tipo_cobranza',
            field=models.CharField(choices=[('judicial', 'Judicial'), ('extra judicial', 'Extra judicial')], default='extra judicial', max_length=15),
        ),
        migrations.AddField(
            model_name='lead',
            name='valor_cuota',
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='lead',
            name='status',
            field=models.CharField(choices=[('inubicable', 'Inubicable'), ('no contactado', 'No contactado'), ('contactado', 'Contactado'), ('compromiso', 'Compromiso'), ('pagando', 'Pagando'), ('al dia', 'Al dia')], default='no contactado', max_length=15),
        ),
    ]
