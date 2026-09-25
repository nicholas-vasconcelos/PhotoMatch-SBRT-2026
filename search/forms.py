from django import forms


class QueryUploadForm(forms.Form):
    selfie_capture = forms.ImageField(required=False)
    selfie_file = forms.ImageField(required=False)

    def clean(self):
        cleaned = super().clean()
        capture = cleaned.get("selfie_capture")
        upload = cleaned.get("selfie_file")
        if not capture and not upload:
            raise forms.ValidationError("Please provide a selfie photo.")
        return cleaned
