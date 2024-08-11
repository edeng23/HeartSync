import xml.etree.ElementTree as ET
import pandas as pd
import argparse
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import datetime
import pytz
from rich.console import Console
from rich.table import Table


logging.basicConfig(level=logging.INFO)

console = Console()


def display_leaderboard(events, title):
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Rank", style="dim", width=12)
    table.add_column("Event", style="bold", width=40)
    table.add_column("Average Heart Rate", justify="right")
    table.add_column("Max Heart Rate", justify="right")

    for i, event in enumerate(events):
        table.add_row(
            str(i + 1),
            event["summary"],
            str(event.get("average_heart_rate", "N/A")),
            str(event.get("max_heart_rate", "N/A")),
        )

    console.print(title, style="bold green")
    console.print(table)


def authenticate_google_calendar(credentials_path="credentials.json"):
    scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes=scopes)
    credentials = flow.run_local_server(port=0)
    service = build("calendar", "v3", credentials=credentials)
    logging.info("Authenticated with Google Calendar API")
    return service


def extract_heart_rate_data(file_path):
    try:
        tree = ET.parse(file_path)
    except ET.ParseError as e:
        logging.error(f"Error parsing XML file: {e}")
        return pd.DataFrame()
    except FileNotFoundError as e:
        logging.error(f"File not found: {e}")
        return pd.DataFrame()

    root = tree.getroot()
    records = []
    for record in root.findall(".//Record[@type='HKQuantityTypeIdentifierHeartRate']"):
        records.append(
            {"time": record.attrib["startDate"], "value": record.attrib["value"]}
        )

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_convert("UTC")
    logging.debug(f"Heart Rate Data Sample: {df.head()}")
    return df


def get_calendar_events(service):
    now = datetime.datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
    one_year_ago = (
        datetime.datetime.utcnow() - datetime.timedelta(days=365)
    ).isoformat() + "Z"
    page_token = None
    events = []

    while True:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=one_year_ago,
                timeMax=now,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,  # Adjust this number if you want to try smaller batches
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(events_result.get("items", []))
        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    logging.debug(f"Total number of events retrieved: {len(events)}")

    event_list = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        end = event["end"].get("dateTime", event["end"].get("date"))
        start_dt = pd.to_datetime(start)
        end_dt = pd.to_datetime(end)

        # Localize or convert to UTC as necessary
        if start_dt.tzinfo is None:
            start_dt = start_dt.tz_localize("UTC")
        else:
            start_dt = start_dt.tz_convert("UTC")
        if end_dt.tzinfo is None:
            end_dt = end_dt.tz_localize("UTC")
        else:
            end_dt = end_dt.tz_convert("UTC")

        event_list.append(
            {"summary": event["summary"], "start": start_dt, "end": end_dt}
        )
        logging.debug(f"Event: {event['summary']}, Start: {start_dt}, End: {end_dt}")

    return event_list


def safe_float(num, default=float("-inf")):
    return num if num is not None else default


# Main execution block:
if __name__ == "__main__":
    # Parsing arguments and initializing data extraction
    parser = argparse.ArgumentParser()
    parser.add_argument("export_file_path", help="Path to the exported XML file")
    parser.add_argument(
        "google_credentials_path", help="Path to the Google credentials file"
    )
    args = parser.parse_args()
    df = extract_heart_rate_data(args.export_file_path)
    service = authenticate_google_calendar(args.google_credentials_path)
    event_list = get_calendar_events(service)

    # Processing events and heart rate matches
    for event in event_list:
        mask = (df["time"] >= event["start"]) & (df["time"] <= event["end"])
        matching_records = df.loc[mask, "value"].astype(float)
        logging.debug(
            f"Event: {event['summary']}, Start: {event['start']}, End: {event['end']}, Matching Records: {len(matching_records)}"
        )
        if not matching_records.empty:
            event["average_heart_rate"] = matching_records.mean()
            event["max_heart_rate"] = matching_records.max()
        else:
            event["average_heart_rate"] = None
            event["max_heart_rate"] = None

    event_list_sorted_avg = sorted(
        event_list, key=lambda x: safe_float(x.get("average_heart_rate")), reverse=True
    )[:50]

    event_list_sorted_max = sorted(
        event_list, key=lambda x: safe_float(x.get("max_heart_rate")), reverse=True
    )[:50]

    display_leaderboard(
        event_list_sorted_avg, "Top 50 Events with the Highest Average Heart Rate"
    )
    display_leaderboard(
        event_list_sorted_max, "Top 50 Events with the Highest Maximum Heart Rate"
    )
