import os
import sys
import requests
from dotenv import load_dotenv

# Load env from root
load_dotenv()

# Add project root to path
sys.path.append(os.getcwd())

from app.vapi_client import create_assistant

try:
    print("Testing create_assistant...")
    res = create_assistant("debug_test", "This is a test prompt.")
    print("Success!")
    print(res)
except requests.exceptions.HTTPError as e:
    print(f"HTTP Error: {e}")
    if e.response is not None:
        print(f"Response Body: {e.response.text}")
except Exception as e:
    print(f"Error: {e}")
