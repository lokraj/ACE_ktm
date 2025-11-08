# Product Form Testing Guide

## Setup
1. Start Django server: `python manage.py runserver`
2. Open browser to: `http://127.0.0.1:8000`

## Manual Test Cases

### TC-001: Form Layout
- ✅ All fields visible: Name, Category, Price, Description, In Stock, Submit

### TC-002: Product Name Required
- Leave Product Name empty → click Submit
- ✅ Error: "Product Name is required"

### TC-003: Product Name Length
- Enter "AB" in Product Name → click elsewhere
- ✅ Error: "Product Name must be at least 3 characters"

### TC-004: Category Required
- Leave Category unselected → click Submit
- ✅ Error: "Please select a category"

### TC-005: Price Required
- Leave Price empty → click Submit
- ✅ Error: "Price is required"

### TC-006: Price Numeric
- Enter "abc" in Price field
- ✅ Browser validation prevents non-numeric input

### TC-007: Price Positive
- Enter "0" or negative number in Price
- ✅ Error: "Price must be greater than 0"

### TC-008: Description Length
- Enter 301+ characters in Description
- ✅ Error: "Description cannot exceed 300 characters"
- ✅ Character counter shows current count

### TC-009: Success Flow
- Fill all required fields with valid data → Submit
- ✅ Success message: "Product information submitted successfully!"
- ✅ Form resets after submission

### TC-010: Submit Button State
- Keep any required field invalid
- ✅ Submit button remains disabled

### TC-011: Checkbox Behavior
- Toggle In Stock checkbox
- ✅ Value changes without validation errors

## Expected Behavior
- Real-time validation on input/blur events
- Submit button disabled until all validations pass
- Success message appears for 3 seconds after valid submission
- Form resets after successful submission
