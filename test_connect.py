import gspread
from oauth2client.service_account import ServiceAccountCredentials

print("Attempting to connect...")

# 1. Define the scope
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 2. Authenticate using your JSON key
creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
client = gspread.authorize(creds)

# 3. Open the Sheet
try:
    sheet = client.open("Honest_Plate_DB")
    worksheet = sheet.worksheet("User_Profiles")

    # 4. Write a test value
    worksheet.update_cell(2, 1, "Test_User") # Row 2, Col 1
    print("SUCCESS! Connected to Google Sheets and wrote 'Test_User'.")

except Exception as e:
    print(f"FAILED: {e}")