import os
import json
import requests
import pandas as pd
from app.extractor import extract_text, generate_uk_restaurant_prompt
from app.vapi_client import create_assistant

# 1. Generate Test Assets
print("Generating test assets...")
df = pd.DataFrame({
    "Item": ["Margherita Pizza", "Pepperoni Pizza", "Garlic Bread", "Coke"],
    "Price": [8.50, 10.00, 3.50, 1.50],
    "Description": ["Classic cheese and tomato", "Spicy pepperoni", "With cheese", "Chilled 330ml can"]
})
df.to_excel("test_menu.xlsx", index=False)

rules = """
Business Name: The London Slice
Tone: Extremely friendly, polite, and conversational UK tone. Use standard greetings.
Rules: 
- We do not sell alcohol.
- Delivery takes 45 minutes and costs £2.50. Minimum order for delivery is £10.
- Collection is ready in 15 minutes.
- If the user asks for anything not on the menu, politely tell them we don't serve it.
"""
with open("test_rules.txt", "w", encoding="utf-8") as f:
    f.write(rules)

# 2. Extract Text
print("Extracting text from files...")
rules_text = extract_text("test_rules.txt")
menu_text = extract_text("test_menu.xlsx")

# 3. Generate Prompt
prompt = generate_uk_restaurant_prompt(rules_text, menu_text)
print("System Prompt Generated successfully. Snippet:")
print(prompt[:300] + "...\n")

# 4. Call Vapi
print("Calling Vapi to provision the agent...")
try:
    response = create_assistant("TEST-BUSINESS-001", prompt)
    print("\nSUCCESS! Assistant created on Vapi.")
    print("Assistant ID:", response.get("id"))
    print("\nYou can now check your Vapi Dashboard. You should see a new assistant named 'Assistant_for_TEST-BUSINESS-001'.")
except requests.exceptions.HTTPError as e:
    print("\nFAILED to create assistant.")
    print("HTTP Error:", e)
    print("Vapi Response Body:", e.response.text)
except Exception as e:
    print("\nFAILED to create assistant.")
    print("Error:", str(e))
