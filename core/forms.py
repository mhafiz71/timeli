# core/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from .models import TimetableSource

User = get_user_model()


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'login-input block w-full px-3 py-2.5 rounded-lg text-sm',
            'placeholder': 'username'
        })
        self.fields['password1'].widget.attrs.update({
            'class': 'login-input block w-full px-3 py-2.5 rounded-lg text-sm',
            'placeholder': '••••••••'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'login-input block w-full px-3 py-2.5 rounded-lg text-sm',
            'placeholder': '••••••••'
        })

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
        return user


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'role')
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'placeholder': 'First Name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'placeholder': 'Last Name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'placeholder': 'your.email@example.com'
            }),
            'role': forms.Select(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
            }),
        }


class TimetableSourceForm(forms.ModelForm):
    class Meta:
        model = TimetableSource
        fields = ['academic_year', 'semester',
                  'display_name', 'timetable_type', 'description', 'source_json']
        widgets = {
            'academic_year': forms.TextInput(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'placeholder': 'e.g., 2024/2025'
            }),
            'semester': forms.TextInput(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'placeholder': 'e.g., First Semester'
            }),
            'display_name': forms.TextInput(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'placeholder': 'e.g., Computer Science - Level 300'
            }),
            'timetable_type': forms.Select(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg'
            }),
            'description': forms.Textarea(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'rows': 3,
                'placeholder': 'Optional: Add description for this timetable (e.g., Computer Science Department, First Year Students, etc.)'
            }),
            'source_json': forms.FileInput(attrs={
                'class': 'input-modern block w-full px-4 py-3 rounded-lg',
                'accept': '.json'
            }),
        }
