import os
import google.generativeai as genai

# Configure the API key from environment variable
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# Test the model
model = genai.GenerativeModel('gemini-1.5-pro-latest')
response = model.generate_content("Hello, are you working?")
print(response.text)