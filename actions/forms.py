from django import forms
from .models import Action, Lead
from demographics.models import Phone, IDDemographics, AvalDemographics
import logging

logger = logging.getLogger(__name__)

class LeadSearchForm(forms.Form):
    query = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Search by OP, RUT, or Aval RUT...'})
    )

class DemographicSelectionForm(forms.Form):
    phone = forms.ModelChoiceField(queryset=Phone.objects.none(), required=False)
    email = forms.ChoiceField(choices=[], required=False)

    def __init__(self, *args, **kwargs):
        lead = kwargs.pop('lead', None)
        super().__init__(*args, **kwargs)

        if lead:
            # Filter phones related to the lead
            self.fields['phone'].queryset = Phone.objects.filter(lead=lead)
            self.fields['phone'].label_from_instance = lambda \
                obj: f'{obj.phone_number} ({obj.get_phone_type_display()})'

            # Email choice field setup
            id_demographics = IDDemographics.objects.filter(lead=lead).first()
            aval_demographics = AvalDemographics.objects.filter(id_demographics=id_demographics)

            email_choices = []
            if id_demographics and id_demographics.principal_email:
                email_choices.append(
                    (id_demographics.principal_email, f'{id_demographics.principal_email} (principal)'))
            for aval in aval_demographics:
                if aval.aval_email:
                    email_choices.append((aval.aval_email, f'{aval.aval_email} (aval)'))

            self.fields['email'].choices = email_choices



class ActionForm(forms.ModelForm):
    class Meta:
        model = Action
        fields = [
            'action_type',
            'result',
            'comment',
            'target',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['target'].required = True
        self.fields['result'].required = True

        # Debug logging
        logger.debug(f"Form initialized with fields: {self.fields}")

    def clean(self):
        cleaned_data = super().clean()

        action_type = cleaned_data.get('action_type')
        result = cleaned_data.get('result')
        target = cleaned_data.get('target')

        logger.debug(f"Cleaned data - Action Type: {action_type}, Result: {result}, Target: {target}")

        # Perform any additional validation as needed
        if not action_type or not result or not target:
            raise forms.ValidationError("All fields are required.")

        return cleaned_data