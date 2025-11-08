#!/usr/bin/env python3
"""
Test script for Product Information Form
Run this after starting the Django server to verify all test cases
"""

import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options

def setup_driver():
    """Setup Chrome driver with headless option"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    return webdriver.Chrome(options=options)

def test_form_layout(driver):
    """TC-001: Verify form layout"""
    driver.get("http://127.0.0.1:8000")
    
    # Check all fields are present
    assert driver.find_element(By.ID, "product-name")
    assert driver.find_element(By.ID, "category")
    assert driver.find_element(By.ID, "price")
    assert driver.find_element(By.ID, "description")
    assert driver.find_element(By.ID, "in-stock")
    assert driver.find_element(By.ID, "submit-btn")
    print("✓ TC-001: Form layout verified")

def test_required_name(driver):
    """TC-002: Validate required field: Product Name"""
    driver.get("http://127.0.0.1:8000")
    
    submit_btn = driver.find_element(By.ID, "submit-btn")
    submit_btn.click()
    
    error = driver.find_element(By.ID, "name-error")
    assert "Product Name is required" in error.text
    print("✓ TC-002: Product Name required validation")

def test_name_length(driver):
    """TC-003: Validate Product Name length"""
    driver.get("http://127.0.0.1:8000")
    
    name_field = driver.find_element(By.ID, "product-name")
    name_field.send_keys("AB")
    name_field.click()
    
    # Trigger validation by clicking elsewhere
    driver.find_element(By.ID, "category").click()
    
    error = driver.find_element(By.ID, "name-error")
    assert "must be at least 3 characters" in error.text
    print("✓ TC-003: Product Name length validation")

def run_all_tests():
    """Run all test cases"""
    print("Starting Product Form Tests...")
    print("Make sure Django server is running on http://127.0.0.1:8000")
    
    try:
        driver = setup_driver()
        
        test_form_layout(driver)
        test_required_name(driver)
        test_name_length(driver)
        
        print("\n✅ All tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_all_tests()
