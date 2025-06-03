from gradescopeapi.classes.connection import GSConnection
import json
from enums import DateStrictness
import datetime
import zoneinfo
import time
from datetime import timedelta
import os.path
import customtkinter as ctk
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import CTkMessagebox

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CONFIG_PATH = "config.json"
SELECTIVITY = DateStrictness.ALL
DARK_MODE = True
COLOR_THEME = "blue"
CURRENT_FRAME = None
APP = None
GRADESCOPE_SAVED = False


def selectivity_combobox_callback(choice):
    global SELECTIVITY
    match choice:
        case "Sync ALL":
            SELECTIVITY = DateStrictness.ALL
        case "Sync all except past due already submitted":
            SELECTIVITY = DateStrictness.NEVER_PAST_DUE_ALREADY_SUBMITTED
        case "Sync all but already submitted":
            SELECTIVITY = DateStrictness.NEVER_ALREADY_SUBMITTED
        case "Sync all but past due":
            SELECTIVITY = DateStrictness.NEVER_PAST_DUE
        case "Sync all except past due unless late submission open":
            SELECTIVITY = DateStrictness.NEVER_PAST_DUE_UNLESS_LATE_OPEN
        case "Sync all except past due unless late submission open and no submission":
            SELECTIVITY = DateStrictness.NEVER_PAST_DUE_UNLESS_LATE_OPEN_AND_NO_SUBMISSION


def color_theme_combobox_callback(choice):
    global COLOR_THEME
    COLOR_THEME = choice
    ctk.set_default_color_theme(COLOR_THEME)


def get_gradescope_credentials(root):
    result = {}

    popup = ctk.CTkToplevel(root)
    popup.title("Enter Gradescope Credentials")
    popup.geometry("300x200")
    popup.grab_set()

    ctk.CTkLabel(popup, text="Gradescope Login").pack(pady=10)

    user_entry = ctk.CTkEntry(popup, placeholder_text="Username")
    user_entry.pack(pady=5)

    pass_entry = ctk.CTkEntry(popup, placeholder_text="Password", show="*")
    pass_entry.pack(pady=5)

    def submit():
        result["gs_user"] = user_entry.get()
        result["gs_pass"] = pass_entry.get()
        popup.destroy()

    ctk.CTkButton(popup, text="Submit", command=submit).pack(pady=10)

    popup.wait_window()

    return result


def show_success_message():
    msg = CTkMessagebox.CTkMessagebox(
        title="Sync Successful!",
        message="Sync completed successfully!",
        icon="check"
    )
    return msg.get()


def show_error_message(message):
    msg = CTkMessagebox.CTkMessagebox(
        title="Sync Error!",
        message=message,
        icon="cancel"
    )
    return msg.get()


def update_gradescope_credentials(new_user, new_pass):
    try:
        with open(CONFIG_PATH, 'r') as config_file:
            config_data = json.load(config_file)

        config_data["gs_user"] = new_user
        config_data["gs_pass"] = new_pass

        with open(CONFIG_PATH, 'w') as config_file:
            json.dump(config_data, config_file, indent=2)

    except FileNotFoundError:
        print("Config file not found")
    except json.JSONDecodeError:
        print("Invalid JSON in config file")


def resync():
    if GRADESCOPE_SAVED:
        gs_user = None
        gs_pass = None
        try:
            with open(CONFIG_PATH, 'r') as config_file:
                config_data = json.load(config_file)
                gs_user = config_data["gs_user"]
                gs_pass = config_data["gs_pass"]
        except FileNotFoundError:
            result = get_gradescope_credentials(APP)
            if "gs_user" not in result or "gs_pass" not in result:
                print("User cancelled login.")
                return
            gs_user = result["gs_user"]
            gs_pass = result["gs_pass"]
    else:
        result = get_gradescope_credentials(APP)
        if "gs_user" not in result or "gs_pass" not in result:
            print("User cancelled login.")
            return
        gs_user = result["gs_user"]
        gs_pass = result["gs_pass"]

    gs_connection = GSConnection()
    login_successful = False
    while not login_successful:
        try:
            gs_connection.login(gs_user, gs_pass)
            login_successful = True
        except:
            show_error_message("Gradescope Login Invalid!")
            result = get_gradescope_credentials(APP)
            if "gs_user" not in result or "gs_pass" not in result:
                print("User cancelled login.")
                return
            gs_user = result["gs_user"]
            gs_pass = result["gs_pass"]
    if GRADESCOPE_SAVED:
        update_gradescope_credentials(gs_user, gs_pass)


    # google login
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Token refresh failed: {e}")
                if os.path.exists("token.json"):
                    os.remove("token.json")
                creds = None  # Force reauth
    if not creds:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        except Exception as e:
            print(f"Google Auth failed, please make sure you properly followed the setup: {e}")

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    try:
        service = build("calendar", "v3", credentials=creds)
        calendar_id = get_or_create_calendar(service, "Gradescope CalSync")

    except Exception as e:
        show_error_message(f"Sync unsucessful! Please make sure all login info and setup is correct. Error: {e}")
    syncing_label = ctk.CTkLabel(CURRENT_FRAME, text="ReSyncing... Please Wait⏳", font=("Segoe UI", 16, "bold"))
    syncing_label.pack(pady=(10, 5))
    CURRENT_FRAME.update()
    try:
        with open('synced_assignments.json', 'r') as psa_file:
            psa_data = json.load(psa_file)
            courses = gs_connection.account.get_courses()
            for course in courses["student"]:
                assignments = gs_connection.account.get_assignments(course)
                for assignment in assignments:
                    if assignment.assignment_id in psa_data:
                        event_id = psa_data[assignment.assignment_id]
                        try:
                            event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

                            event['start']['dateTime'] = (assignment.due_date - timedelta(hours=1)).isoformat()
                            event['end']['dateTime'] = assignment.due_date.isoformat()

                            service.events().update(
                                calendarId=calendar_id,
                                eventId=event_id,
                                body=event
                            ).execute()

                        except Exception as e:
                            print(f"Failed to update event: {e}")
                            return None
            show_success_message()
    except FileNotFoundError:
        show_error_message("Sync Error! No Synced assignments file!")
    finally:
        syncing_label.destroy()


def sync_startup():
    if GRADESCOPE_SAVED:
        gs_user = None
        gs_pass = None
        try:
            with open(CONFIG_PATH, 'r') as config_file:
                config_data = json.load(config_file)
                gs_user = config_data["gs_user"]
                gs_pass = config_data["gs_pass"]
        except FileNotFoundError:
            result = get_gradescope_credentials(APP)
            if "gs_user" not in result or "gs_pass" not in result:
                print("User cancelled login.")
                return
            gs_user = result["gs_user"]
            gs_pass = result["gs_pass"]
    else:
        result = get_gradescope_credentials(APP)
        if "gs_user" not in result or "gs_pass" not in result:
            print("User cancelled login.")
            return
        gs_user = result["gs_user"]
        gs_pass = result["gs_pass"]

    gs_connection = GSConnection()
    login_successful = False
    while not login_successful:
        try:
            gs_connection.login(gs_user, gs_pass)
            login_successful = True
        except:
            show_error_message("Gradescope Login Invalid!")
            result = get_gradescope_credentials(APP)
            if "gs_user" not in result or "gs_pass" not in result:
                print("User cancelled login.")
                return
            gs_user = result["gs_user"]
            gs_pass = result["gs_pass"]
    if GRADESCOPE_SAVED:
        update_gradescope_credentials(gs_user, gs_pass)
    # google login
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Token refresh failed: {e}")
                if os.path.exists("token.json"):
                    os.remove("token.json")
                creds = None  # Force reauth
    if not creds:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        except Exception as e:
            print(f"Google Auth failed, please make sure you properly followed the setup. Error: {e}")

        with open("token.json", "w") as token:
            token.write(creds.to_json())
    syncing_label = ctk.CTkLabel(CURRENT_FRAME, text="Syncing... Please Wait⏳", font=("Segoe UI", 16, "bold"))
    syncing_label.pack(pady=(10, 5))
    CURRENT_FRAME.update()
    try:
        service = build("calendar", "v3", credentials=creds)
        calendar_id = get_or_create_calendar(service, "Gradescope CalSync")
        process_courses_gs(gs_connection, service, calendar_id)
        show_success_message()
    except Exception as e:
        show_error_message(f"Sync unsucessful! Please make sure all login info and setup is correct. Error: {e}")
    finally:
        syncing_label.destroy()


def main_frame():
    global DARK_MODE
    global COLOR_THEME
    global GRADESCOPE_SAVED
    global CURRENT_FRAME
    try:
        with open(CONFIG_PATH, 'r') as config_file:
            config_data = json.load(config_file)
    except FileNotFoundError:
        print("Uh oh")
        config_data = dict()
    DARK_MODE = config_data["dark_mode"]
    COLOR_THEME = config_data["color_theme"]
    GRADESCOPE_SAVED = config_data["gs_saved"]
    if DARK_MODE:
        ctk.set_appearance_mode("dark")
    else:
        ctk.set_appearance_mode("light")
    ctk.set_default_color_theme(COLOR_THEME)
    CURRENT_FRAME = ctk.CTkFrame(APP)
    CURRENT_FRAME.pack(fill="both", expand=True)
    APP.title("CalSync")
    ctk.CTkLabel(CURRENT_FRAME, text="CalSync", font=("Segoe UI", 24, "bold")).pack(side=ctk.TOP,
                                                                                                 anchor=ctk.NW, pady=20,
                                                                                                 padx=20)

    ctk.CTkLabel(CURRENT_FRAME, text="Start Sync (for bringing in new assignments)", font=("Segoe UI", 16, "underline")).pack(side=ctk.TOP,
                                                                                                                 anchor=ctk.NW,
                                                                                                           pady=(10,0),
                                                                                                           padx=(
                                                                                                               20, 40))
    sync_btn = ctk.CTkButton(CURRENT_FRAME, text="Start Sync →", command=sync_startup)
    sync_btn.pack(side=ctk.TOP, anchor=ctk.NW, pady=(20,30), padx=20)

    ctk.CTkLabel(CURRENT_FRAME, text="Start ReSync (for updating old assignments)", font=("Segoe UI", 16, "underline")).pack(side=ctk.TOP,
                                                                                                                 anchor=ctk.NW,
                                                                                                           pady=(10,0),
                                                                                                           padx=(
                                                                                                               20, 40))
    re_btn = ctk.CTkButton(CURRENT_FRAME, text="Start ReSync →", command=resync)
    re_btn.pack(side=ctk.TOP, anchor=ctk.NW, pady=20, padx=20)

    ctk.CTkLabel(CURRENT_FRAME, text="Settings (for changing your config)",
                 font=("Segoe UI", 16, "underline")).pack(side=ctk.TOP,
                                                          anchor=ctk.NW,
                                                          pady=(10, 0),
                                                          padx=(
                                                              20, 40))
    re_btn = ctk.CTkButton(CURRENT_FRAME, text="View Settings", command=switch_to_settings)
    re_btn.pack(side=ctk.TOP, anchor=ctk.NW, pady=20, padx=20)

def switch_to_settings():
    global CURRENT_FRAME
    CURRENT_FRAME.destroy()
    show_first_run(True)

def switch_to_main_frame():
    global CURRENT_FRAME
    CURRENT_FRAME.destroy()
    main_frame()


def show_first_run(asSettings):
    global CURRENT_FRAME
    global APP
    global GRADESCOPE_SAVED
    first_window = ctk.CTkFrame(APP)
    first_window.pack(fill="both", expand=True)
    CURRENT_FRAME = first_window
    ctk.CTkLabel(first_window, text="Settings" if asSettings else "Welcome to Gradescope CalSync! Let's get things set up :)",
                 font=("Segoe UI", 24, "bold")).pack(side=ctk.TOP, anchor=ctk.NW, pady=20, padx=20)

    # if we are using it as a settings page we need to load in stuff from the config as the new defaults
    if asSettings:
        try:
            with open(CONFIG_PATH, 'r') as config_file:
                config_data = json.load(config_file)
        except FileNotFoundError:
            print("Uh oh in as settings")
            config_data = dict()

    # Gradescope password saving
    gradescope_frame = ctk.CTkFrame(first_window)
    gradescope_frame.pack(anchor=ctk.W, padx=20, pady=(10, 0))

    ctk.CTkLabel(gradescope_frame, text="Gradescope Password Storing Config:", font=("Segoe UI", 16)).pack(side=ctk.TOP,
                                                                                                           pady=10,
                                                                                                           padx=(
                                                                                                               20, 40))

    gradescope_user_entry = ctk.CTkEntry(gradescope_frame, placeholder_text="GS User")
    gradescope_pass_entry = ctk.CTkEntry(gradescope_frame, placeholder_text="GS Pass", show="*")

    save_gradescope_var = ctk.BooleanVar()
    if asSettings:
        if config_data['gs_saved'] == True:
            save_gradescope_var.set(True)

    def toggle_gradescope_entries():
        global GRADESCOPE_SAVED
        if save_gradescope_var.get():
            gradescope_user_entry.pack(anchor=ctk.W, padx=(40, 0), pady=(0, 10))
            gradescope_pass_entry.pack(anchor=ctk.W, padx=(40, 0), pady=(10, 10))
            GRADESCOPE_SAVED = True
        else:
            gradescope_user_entry.pack_forget()
            gradescope_pass_entry.pack_forget()
            GRADESCOPE_SAVED = False



    save_gradescope_cb = ctk.CTkCheckBox(gradescope_frame, text="Save Gradescope Info", variable=save_gradescope_var,
                                         command=toggle_gradescope_entries)
    save_gradescope_cb.pack(anchor=ctk.W, padx=(20, 40), pady=(10, 10))

    if asSettings:
        if config_data['gs_saved'] == True:
            toggle_gradescope_entries()
            gradescope_user_entry.insert(0, config_data["gs_user"])
            gradescope_pass_entry.insert(0, config_data["gs_pass"])

    # Selectivity combobox
    selectivity_frame = ctk.CTkFrame(first_window)
    selectivity_frame.pack(anchor=ctk.W, padx=20, pady=(10, 0))

    ctk.CTkLabel(selectivity_frame, text="Syncing Selectivity Config:", font=("Segoe UI", 16)).pack(side=ctk.TOP,
                                                                                                    anchor=ctk.W,
                                                                                                    pady=(10, 0),
                                                                                                    padx=(20, 40))
    selectivity_combobox = ctk.CTkComboBox(selectivity_frame,
                                           values=["Sync ALL", "Sync all except past due already submitted",
                                                   "Sync all but already submitted",
                                                   "Sync all but past due",
                                                   "Sync all except past due unless late submission open",
                                                   "Sync all except past due unless late submission open and no submission"],
                                           command=selectivity_combobox_callback, width=300, font=("Segoe UI", 16))

    def get_selectivity_message(selectivity):
        match selectivity:
            case DateStrictness.ALL:
                return "Sync ALL"
            case DateStrictness.NEVER_PAST_DUE_ALREADY_SUBMITTED:
                return "Sync all except past due already submitted"
            case DateStrictness.NEVER_ALREADY_SUBMITTED:
                return "Sync all but already submitted"
            case DateStrictness.NEVER_PAST_DUE:
                return "Sync all but past due"
            case DateStrictness.NEVER_PAST_DUE_UNLESS_LATE_OPEN:
                return "Sync all except past due unless late submission open"
            case DateStrictness.NEVER_PAST_DUE_UNLESS_LATE_OPEN_AND_NO_SUBMISSION:
                return "Sync all except past due unless late submission open and no submission"

    if asSettings:
        selectivity_enum = DateStrictness(config_data["sync_selectivity"])
        selectivity_combobox.set(get_selectivity_message(selectivity_enum))
    else:
        selectivity_combobox.set("Sync all except past due unless late submission open and no submission")
    selectivity_combobox.pack(anchor=ctk.W, padx=(20, 40), pady=(20, 20))
    # Theming
    theming_frame = ctk.CTkFrame(first_window)
    theming_frame.pack(anchor=ctk.W, padx=20, pady=(10, 0))

    ctk.CTkLabel(theming_frame, text="Theming Config (will take effect on main app):", font=("Segoe UI", 16)).pack(
        side=ctk.TOP, anchor=ctk.W, pady=(10, 0), padx=(20, 40))

    color_theme_combobox = ctk.CTkComboBox(theming_frame, values=["blue", "green"],
                                           command=color_theme_combobox_callback, width=300, font=("Segoe UI", 16))
    if asSettings:
        color_theme_combobox.set(config_data['color_theme'])
    else:
        color_theme_combobox.set("blue")
    color_theme_combobox.pack(anchor=ctk.W, padx=(20, 40), pady=(20, 20))

    def toggle_dark_mode():
        global DARK_MODE
        if dark_mode_var.get():
            DARK_MODE = True
            ctk.set_appearance_mode("dark")
        else:
            DARK_MODE = False
            ctk.set_appearance_mode("light")

    dark_mode_var = ctk.BooleanVar(value=True)
    dark_mode_cb = ctk.CTkCheckBox(theming_frame, text="Dark Mode", variable=dark_mode_var,
                                   command=toggle_dark_mode)
    dark_mode_cb.pack(anchor=ctk.W, padx=(20, 40), pady=(10, 10))

    ctk.set_appearance_mode("light" if asSettings and config_data["dark_mode"] is False else "dark")
    ctk.set_default_color_theme(color_theme_combobox.get())

    def save_config(gs_user, gs_pass):
        global DARK_MODE
        global COLOR_THEME
        global CONFIG_PATH
        global GRADESCOPE_SAVED
        config_data = dict()
        config_data["dark_mode"] = DARK_MODE
        config_data["color_theme"] = COLOR_THEME
        config_data["gs_saved"] = GRADESCOPE_SAVED
        config_data["gs_user"] = gs_user
        config_data["gs_pass"] = gs_pass
        config_data["sync_selectivity"] = SELECTIVITY.value
        with open(CONFIG_PATH, "w") as config_file:
            json.dump(config_data, config_file, indent=2)

    # Proceed arrow

    def proceed_button_onclick(gs_user, gs_pass):
        save_config(gs_user, gs_pass)
        switch_to_main_frame()

    proceed_button = ctk.CTkButton(first_window, text="Proceed →", command=lambda: proceed_button_onclick(
        gradescope_user_entry.get() if GRADESCOPE_SAVED else "",
        gradescope_pass_entry.get() if GRADESCOPE_SAVED else ""))
    proceed_button.place(relx=1.0, rely=1.0, anchor="se", x=-20, y=-20)


def get_or_create_calendar(service, calendar_name="Gradescope Sync"):
    # List all calendars
    calendar_list = service.calendarList().list().execute()

    # Look for existing calendar
    for calendar in calendar_list.get('items', []):
        if calendar.get('summary') == calendar_name:
            print(f"Found existing calendar: {calendar_name}")
            return calendar['id']

    primary_calendar = service.calendars().get(calendarId='primary').execute()
    # If calendar doesn't exist make it
    calendar_body = {
        'summary': calendar_name,
        'description': f'Custom calendar for {calendar_name}',
        'timeZone': primary_calendar['timeZone']
    }

    created_calendar = service.calendars().insert(body=calendar_body).execute()
    calendar_id = created_calendar['id']

    calendar_list_entry = {
        'id': calendar_id
    }
    service.calendarList().insert(body=calendar_list_entry).execute()

    print(f"Created calendar with ID: {calendar_id}")
    return calendar_id


def get_gcal_friendly_timezone(assignment):
    if assignment.due_date and assignment.due_date.tzinfo:
        try:
            offset_seconds = int(assignment.due_date.utcoffset().total_seconds())
            offset_hours = offset_seconds // 3600
            if offset_hours == 0:
                return "UTC"
            elif offset_hours > 0:
                return f"Etc/GMT-{offset_hours}"
            else:
                return f"Etc/GMT+{abs(offset_hours)}"
        except:
            print("Error with timezone management")
    return "America/New_York"  # default case


def process_assignment_gs(course, assignment, psa_data, show_past_due, service, calendar_id):
    google_cal_event_id = None
    local_timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
    aware_now = datetime.datetime.now(local_timezone)
    if (assignment.due_date is None):
        return

    if assignment.due_date.tzinfo:
        assignment_due_local = assignment.due_date.astimezone(local_timezone)
    else:
        assignment_due_local = assignment.due_date.replace(tzinfo=local_timezone)
    match show_past_due:
        case DateStrictness.ALL:
            pass
        case DateStrictness.NEVER_PAST_DUE_ALREADY_SUBMITTED:
            if (assignment_due_local < aware_now and assignment.submissions_status != 'No Submission'):
                return
        case DateStrictness.NEVER_ALREADY_SUBMITTED:
            if (assignment.submissions_status != 'No Submission'):
                return
        case DateStrictness.NEVER_PAST_DUE:
            if (assignment_due_local < aware_now):
                return
        case DateStrictness.NEVER_PAST_DUE_UNLESS_LATE_OPEN:
            if (assignment_due_local < aware_now):
                if (assignment.late_due_date is None):
                    return
                if (assignment.late_due_date > aware_now):
                    return
        case DateStrictness.NEVER_PAST_DUE_UNLESS_LATE_OPEN_AND_NO_SUBMISSION:
            if (assignment.submissions_status != 'No Submission'):
                return
            if (assignment_due_local < aware_now):
                if (assignment.late_due_date is None):
                    return
                if (assignment.late_due_date < aware_now or assignment.submissions_status != 'No Submission'):
                    return
    if not (assignment.assignment_id in psa_data):
        # Handle adding the assignment to google calendar and to the json
        # Handle course id in description
        assignment_timezone = get_gcal_friendly_timezone(assignment)
        cal_event = {
            'summary': assignment.name,
            'start': {
                'dateTime': (assignment.due_date - timedelta(hours=1)).isoformat(),
                'timeZone': assignment_timezone
            },
            'end': {
                'dateTime': assignment.due_date.isoformat(),
                'timeZone': assignment_timezone
            }

        }

        event = service.events().insert(calendarId=calendar_id,
                                        body=cal_event).execute()
        psa_data[assignment.assignment_id] = event['id']


def process_courses_gs(gs_connection, service, calendar_id):
    # psa stands for previously_synced_assignments!
    try:
        with open('synced_assignments.json', 'r') as psa_file:
            psa_data = json.load(psa_file)
    except FileNotFoundError:
        psa_data = dict()

    courses = gs_connection.account.get_courses()
    for course in courses["student"]:
        assignments = gs_connection.account.get_assignments(course)
        for assignment in assignments:
            process_assignment_gs(course, assignment, psa_data, DateStrictness.ALL, service, calendar_id)

    with open('synced_assignments.json', 'w') as psa_file:
        json.dump(psa_data, psa_file, indent=2)


def main():
    global APP
    app = ctk.CTk()
    app.title("CalSync Setup")
    app.geometry("800x600")
    APP = app
    if (os.path.exists(CONFIG_PATH)):
        main_frame()
    else:
        show_first_run(False)
    app.mainloop()


if __name__ == "__main__":
    main()
