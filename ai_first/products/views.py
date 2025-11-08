from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

def product_form(request):
    return render(request, 'products/product_form.html')
