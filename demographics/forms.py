from django import forms
from .models import IDItem, Phone, IDDemographics, AvalDemographics

class UploadIDItemForm(forms.ModelForm):
    class Meta:
        model = IDItem
        fields = '__all__'

class UploadPhoneForm(forms.ModelForm):
    class Meta:
        model = Phone
        fields = '__all__'

class UploadIDDemographicsForm(forms.ModelForm):
    class Meta:
        model = IDDemographics
        fields = '__all__'

class UploadAvalDemographicsForm(forms.ModelForm):
    class Meta:
        model = AvalDemographics
        fields = '__all__'