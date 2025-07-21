import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel("gemini-1.5-pro")

response = model.generate_content("List 5 Python web development skills")
print("✅ Gemini response:\n", response.text)
