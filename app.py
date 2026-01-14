import streamlit as st
import pandas as pd
import numpy as np
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from PIL import Image

# --- 1. CONFIGURATION & SETUP ---
st.set_page_config(page_title="The Honest Plate", page_icon="🥑", layout="centered")

# Initialize Gemini
try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    else:
        st.error("Missing Gemini API Key in secrets.toml")
except Exception as e:
    st.error(f"Gemini Config Error: {e}")

# Initialize Google Sheets Connection
def get_db_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # CHECK: Are we on Cloud or Local?
    if "GCP_CREDENTIALS" in st.secrets:
        # Cloud Mode (Deployment)
        creds_dict = dict(st.secrets["GCP_CREDENTIALS"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # Local Mode (Development)
        # It looks for the file you created in Phase 1
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    
    client = gspread.authorize(creds)
    return client.open("Honest_Plate_DB") 

# --- 2. CORE LOGIC (DATA ENGINEERING) ---

def calculate_tdee(age, gender, height, weight, activity):
    # Mifflin-St Jeor Equation
    if gender == 'Male':
        bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else:
        bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161
    
    multipliers = {
        "Sedentary": 1.2,
        "Lightly Active": 1.375,
        "Moderately Active": 1.55,
        "Very Active": 1.725
    }
    return int(bmr * multipliers.get(activity, 1.2))

def get_or_create_profile(user_id):
    try:
        conn = get_db_connection()
        ws = conn.worksheet("User_Profiles")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # Check if user exists
        if not df.empty and "User_ID" in df.columns:
            # Convert User_ID to string to be safe
            df["User_ID"] = df["User_ID"].astype(str)
            user_row = df[df["User_ID"] == str(user_id)]
            
            if not user_row.empty:
                return user_row.iloc[0].to_dict()
        
        return None 
    except Exception as e:
        st.error(f"DB Error: {e}")
        return None

def run_calibration_engine(user_id):
    """
    The Linear Regression Logic.
    """
    try:
        conn = get_db_connection()
        weight_data = conn.worksheet("Weight_Logs").get_all_records()
        food_data = conn.worksheet("Food_Logs").get_all_records()
        
        if not weight_data or not food_data:
            return 1.0, "Not enough data"

        w_df = pd.DataFrame(weight_data)
        f_df = pd.DataFrame(food_data)
        
        # Filter for User
        # Ensure User_ID columns match types
        w_df = w_df[w_df["User_ID"].astype(str) == str(user_id)]
        f_df = f_df[f_df["User_ID"].astype(str) == str(user_id)]
        
        if len(w_df) < 5: 
            return 1.0, "Need 5+ weigh-ins"
            
        # --- SIMPLE REGRESSION ---
        w_df['DateObj'] = pd.to_datetime(w_df['Date'])
        w_df['DayIndex'] = (w_df['DateObj'] - w_df['DateObj'].min()).dt.days
        
        x = w_df['DayIndex'].values
        y = w_df['Weight_kg'].values
        slope, intercept = np.polyfit(x, y, 1) # Slope = kg change per day
        
        avg_reported_cals = f_df['Final_Cals'].mean()
        tdee = st.session_state.get('profile', {}).get('TDEE', 2000)
        
        expected_intake = tdee + (slope * 7700) 
        
        if avg_reported_cals > 0:
            inflation_factor = expected_intake / avg_reported_cals
        else:
            inflation_factor = 1.0
            
        inflation_factor = max(0.8, min(inflation_factor, 1.5))
        
        return round(inflation_factor, 2), f"Slope: {slope:.3f} kg/day"

    except Exception as e:
        # st.error(f"Engine Error: {e}") # Uncomment to debug
        return 1.0, "Insufficient Data"

# --- 3. UI: LOGIN ---

# Magic Link Check
if "user" in st.query_params:
    st.session_state["user_id"] = st.query_params["user"]

if "user_id" not in st.session_state:
    st.title("🥑 The Honest Plate")
    st.write("### Who is eating?")
    
    c1, c2 = st.columns(2)
    if c1.button("Mom", use_container_width=True):
        st.session_state["user_id"] = "Mom"
        st.rerun()
    if c2.button("Dad", use_container_width=True):
        st.session_state["user_id"] = "Dad"
        st.rerun()
        
    custom = st.text_input("Or nickname:")
    if st.button("Enter"):
        st.session_state["user_id"] = custom
        st.rerun()
    st.stop()

# --- 4. MAIN DASHBOARD ---

USER = st.session_state["user_id"]
PROFILE = get_or_create_profile(USER)

if not PROFILE:
    st.warning(f"Welcome {USER}! One-time setup:")
    with st.form("setup"):
        age = st.number_input("Age", 10, 90, 50)
        gender = st.selectbox("Gender", ["Male", "Female"])
        height = st.number_input("Height (cm)", 100, 220, 160)
        weight = st.number_input("Weight (kg)", 40, 150, 70)
        act = st.selectbox("Activity", ["Sedentary", "Lightly Active", "Moderately Active"])
        
        if st.form_submit_button("Save Profile"):
            tdee = calculate_tdee(age, gender, height, weight, act)
            conn = get_db_connection()
            ws = conn.worksheet("User_Profiles")
            ws.append_row([USER, age, gender, height, weight, act, tdee, 1.0])
            st.success("Saved!")
            st.rerun()
    st.stop()

st.session_state['profile'] = PROFILE
INFLATION_FACTOR = float(PROFILE.get("Inflation_Factor", 1.0))

# --- 5. TABS ---

st.subheader(f"Hi, {USER} 👋")
if INFLATION_FACTOR > 1.05:
    st.caption(f"ℹ️ System adds {int((INFLATION_FACTOR-1)*100)}% buffer based on trends.")

tab_log, tab_stats, tab_weight = st.tabs(["🍽️ Log Meal", "📊 Truth Dashboard", "⚖️ Weigh-In"])

# LOGGING TAB
with tab_log:
    if "log_stage" not in st.session_state:
        st.session_state.log_stage = "input"

    if st.session_state.log_stage == "input":
        method = st.radio("Input", ["📷 Camera", "⌨️ Type"], horizontal=True, label_visibility="collapsed")
        
        content = None
        mode = "Text"

        if method == "📷 Camera":
            img = st.camera_input("Snap photo")
            if img:
                content = Image.open(img)
                mode = "Image"
        else:
            txt = st.text_area("Describe food")
            if txt:
                content = txt

        offset = st.selectbox("When?", ["Just now", "30 mins ago", "1 hr ago"])

        if st.button("Analyze 🚀", type="primary"):
            if not content:
                st.error("Input needed")
            else:
                with st.spinner("AI Analyzing..."):
                    try:
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        prompt = "Analyze meal. Assume Indian Home Cooking. Return: 'Food Name | Calories (int) | Flag'"
                        
                        # Gemini Call
                        resp = model.generate_content([prompt, content])
                        
                        parts = resp.text.split("|")
                        st.session_state.temp_log = {
                            "food": parts[0].strip(),
                            "cals": int(parts[1].strip()),
                            "flag": parts[2].strip() if len(parts)>2 else "None",
                            "mode": mode,
                            "offset": offset
                        }
                        st.session_state.log_stage = "review"
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI Error: {e}")

    if st.session_state.log_stage == "review":
        data = st.session_state.temp_log
        st.info(f"**{data['food']}** (~{data['cals']} kcal)")
        
        if st.button("Save ✅", use_container_width=True):
            # Save Logic
            final_cals = int(data['cals'] * INFLATION_FACTOR)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            today = datetime.now().strftime("%Y-%m-%d")
            
            conn = get_db_connection()
            conn.worksheet("Food_Logs").append_row([
                now, today, USER, "Meal", data['mode'], data['food'], data['cals'], final_cals, data['flag'], data['offset']
            ])
            st.success("Logged!")
            st.session_state.log_stage = "input"
            st.rerun()
            
        if st.button("Cancel"):
            st.session_state.log_stage = "input"
            st.rerun()

# STATS TAB
with tab_stats:
    if st.button("Run Calibration"):
        fac, msg = run_calibration_engine(USER)
        st.info(f"Factor: {fac}x ({msg})")

# WEIGHT TAB
with tab_weight:
    w = st.number_input("Weight (kg)", 40.0, 150.0)
    if st.button("Log Weight"):
        d = datetime.now().strftime("%Y-%m-%d")
        get_db_connection().worksheet("Weight_Logs").append_row([d, USER, w])
        st.success("Logged!")