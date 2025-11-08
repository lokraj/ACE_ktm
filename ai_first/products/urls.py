from django.urls import path
from . import views

urlpatterns = [
    path("", views.product_form, name="product_form"),
]
