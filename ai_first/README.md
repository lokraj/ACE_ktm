# Product Information Form - Django Implementation

## Overview
A Django-based product information form with frontend validation that meets all SCRUM-1 requirements.

## Features
- ✅ Product Name (required, min 3 characters)
- ✅ Product Category (required dropdown)
- ✅ Product Price (required, positive number)
- ✅ Description (optional, max 300 characters)
- ✅ In Stock checkbox
- ✅ Real-time validation
- ✅ Disabled submit button until valid
- ✅ Success message and form reset
- ✅ Responsive design

## Quick Start
```bash
# Start the Django server
python manage.py runserver

# Open browser to:
http://127.0.0.1:8000
```

## Project Structure
```
├── product_manager/          # Django project
│   ├── settings.py          # Project settings
│   └── urls.py              # Main URL configuration
├── products/                # Products app
│   ├── views.py             # View logic
│   ├── urls.py              # App URLs
│   └── templates/products/  # Templates
│       └── product_form.html # Main form template
├── TESTING_GUIDE.md         # Manual testing guide
└── test_form.py             # Automated test script
```

## Validation Rules
- **Product Name**: Required, minimum 3 characters
- **Category**: Required selection from dropdown
- **Price**: Required, must be positive number
- **Description**: Optional, maximum 300 characters
- **Submit Button**: Disabled until all validations pass

## Testing
See `TESTING_GUIDE.md` for complete test cases and manual testing instructions.

## Technical Details
- Django 5.x compatible
- No backend data storage (as per requirements)
- Pure JavaScript validation
- Responsive CSS styling
- PEP8 compliant Python code
