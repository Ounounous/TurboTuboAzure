"""Formato de montos en pesos chilenos: $1.000.000 (sin decimales, punto como separador de
miles, nunca coma). Se usa para saldo insoluto/deuda, cuotas, y montos de pagos/compromisos en
los templates -- reemplaza el patron viejo "${{ valor|floatformat:0 }}", que no agrupaba miles."""
from django import template

register = template.Library()


@register.filter
def clp(value):
    if value in (None, ''):
        return '-'
    try:
        numero = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    negativo = numero < 0
    texto = f'{abs(numero):,}'.replace(',', '.')
    return f'{"-" if negativo else ""}${texto}'
