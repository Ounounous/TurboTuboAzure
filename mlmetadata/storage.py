"""
Destino de los exports anonimizados (JSONL). Reutiliza las mismas credenciales de Azure Blob
que ya usa la media operativa (AZURE_STORAGE_ACCOUNT/_KEY/_CONNECTION_STRING), pero en un
contenedor SEPARADO (AZURE_ML_CONTAINER) -- el dataset de entrenamiento no tiene el mismo
perfil de acceso/retencion que grabaciones o comprobantes. En local, sin esas variables, cae a
un directorio propio fuera de MEDIA_ROOT (nunca se sirve por HTTP).
"""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def get_ml_storage():
    account = os.environ.get('AZURE_STORAGE_ACCOUNT')
    conn = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if account or conn:
        from storages.backends.azure_storage import AzureStorage
        return AzureStorage(
            account_name=account,
            account_key=os.environ.get('AZURE_STORAGE_KEY'),
            connection_string=conn,
            azure_container=os.environ.get('AZURE_ML_CONTAINER', 'ml-training-data'),
            overwrite_files=False,
        )
    location = settings.BASE_DIR / 'ml_exports'
    location.mkdir(parents=True, exist_ok=True)
    return FileSystemStorage(location=str(location))
